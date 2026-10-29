"""Where each file is in the pipeline, for the Ops page (user request 2026-10-27): a count per step and, on
demand, the files in one step.

OneDrive steps count locations (``drive_items``); the processing steps count documents. A downloaded file
whose content belongs to no document yet is "waiting to start" inside ``processing.scope`` and "outside the
processing scope" otherwise, by the dispatcher's own test (dispatcher/routing.py). A PROCESSING document is
"processing now" while a worker holds one of its jobs and "in line" otherwise: tasks are acked late, so a
held job sits in Redis ``unacked`` until it ends.
"""

import json
import re
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.celery_redis.queues import Queue
from backend.postgres import pipeline_config
from backend.postgres.enums import DocumentSourceRole, DocumentStatus, DriveItemStatus
from backend.postgres.models import Blob, Document, DocumentSource, DriveItem


class Step(StrEnum):
    TO_DOWNLOAD = "to_download"
    HELD = "held"
    SKIPPED = "skipped"
    OUTSIDE_SCOPE = "outside_scope"
    WAITING = "waiting"
    IN_LINE = "in_line"
    PROCESSING = "processing"
    REVIEW = "review"
    FAILED = "failed"
    IN_SEARCH = "in_search"
    TAKEN_OUT = "taken_out"


LOCATION_STEP = {
    DriveItemStatus.SEEN: Step.TO_DOWNLOAD,
    DriveItemStatus.PENDING_DOWNLOAD: Step.TO_DOWNLOAD,
    DriveItemStatus.HELD_LARGE_FILE: Step.HELD,
    DriveItemStatus.HELD_BY_SCOPE: Step.HELD,
    DriveItemStatus.QUARANTINED: Step.HELD,
    DriveItemStatus.DOWNLOAD_FAILED: Step.HELD,
    DriveItemStatus.SKIPPED_JUNK: Step.SKIPPED,
    DriveItemStatus.SKIPPED_EMPTY: Step.SKIPPED,
    DriveItemStatus.SKIPPED_SHORTCUT: Step.SKIPPED,
    DriveItemStatus.SKIPPED_UNSUPPORTED_PACKAGE: Step.SKIPPED,
}
DOCUMENT_STEP = {
    DocumentStatus.WAITING_FOR_ROUTE: Step.WAITING,
    DocumentStatus.HALTED: Step.REVIEW,
    DocumentStatus.FAILED: Step.FAILED,
    DocumentStatus.ACTIVE: Step.IN_SEARCH,
    DocumentStatus.ACTIVE_WITH_SOFT_FLAGS: Step.IN_SEARCH,
    DocumentStatus.QUARANTINED: Step.TAKEN_OUT,
    DocumentStatus.SUPERSEDED: Step.TAKEN_OUT,
    DocumentStatus.DELETED: Step.TAKEN_OUT,
}
LOCATION_DETAIL = {
    DriveItemStatus.HELD_LARGE_FILE: "too large to download",
    DriveItemStatus.HELD_BY_SCOPE: "outside the download scope",
    DriveItemStatus.QUARANTINED: "in a quarantine folder",
    DriveItemStatus.SKIPPED_JUNK: "junk",
    DriveItemStatus.SKIPPED_EMPTY: "empty",
    DriveItemStatus.SKIPPED_SHORTCUT: "a shortcut",
    DriveItemStatus.SKIPPED_UNSUPPORTED_PACKAGE: "an unsupported package",
}
DOCUMENT_DETAIL = {
    DocumentStatus.ACTIVE_WITH_SOFT_FLAGS: "has open questions",
    DocumentStatus.QUARANTINED: "taken out",
    DocumentStatus.SUPERSEDED: "replaced by a newer version",
    DocumentStatus.DELETED: "deleted in OneDrive",
}
UNCLAIMED_DETAIL = {Step.HELD: "restricted content", Step.WAITING: "not yet made into a document"}
NOT_QUEUED = "no job queued; sent again on its own after 2 hours"
DOC_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass(frozen=True)
class Jobs:
    held: dict[str, str]  # doc_id -> queue of a job a worker holds
    waiting: dict[str, tuple[str, int]]  # doc_id -> (queue, place in line, 1 = next)


JobsReader = Callable[[bool], Jobs]


def _doc_ids(message: dict) -> set[str]:
    headers = message.get("headers") or {}
    return set(DOC_ID.findall(f"{headers.get('argsrepr', '')} {headers.get('kwargsrepr', '')}"))


def read_jobs(client, with_waiting: bool) -> Jobs:
    """The documents of the jobs workers hold and, when asked, of the jobs waiting per queue (``client``: the
    broker's Redis)."""
    held: dict[str, str] = {}
    for raw in client.hvals("unacked"):
        message, _exchange, queue = json.loads(raw)
        held.update(dict.fromkeys(_doc_ids(message), queue))
    waiting: dict[str, tuple[str, int]] = {}
    for queue in [str(q) for q in Queue if q != Queue.BENCHMARK] if with_waiting else []:
        # kombu pushes on the left and workers pop on the right: the last item is next
        for place, raw in enumerate(reversed(client.lrange(queue, 0, -1)), 1):
            for doc in _doc_ids(json.loads(raw)):
                waiting.setdefault(doc, (queue, place))
    return Jobs(held, waiting)


def get_jobs_reader() -> JobsReader:
    def read(with_waiting: bool) -> Jobs:
        from backend.celery_redis.app import broker

        return read_jobs(broker(), with_waiting)

    return read


class StepCount(BaseModel):
    step: Step
    count: int


class StepFile(BaseModel):
    name: str
    path: str | None
    doc_id: uuid.UUID | None
    route: str | None
    updated_at: datetime | None
    detail: str | None


class StepFiles(BaseModel):
    step: Step
    total: int
    files: list[StepFile]


def _unclaimed(session: Session) -> dict[Step, list[DriveItem]]:
    """Downloaded locations whose content no document holds, sorted as dispatch would treat them."""
    from backend.dispatcher.routing import folder_tree
    from backend.sync.scope import in_scope

    scope = pipeline_config.processing_scope(session)
    _, ancestors = folder_tree(session)
    rows = session.execute(
        select(DriveItem, Blob.restricted)
        .join(Blob, Blob.sha256 == DriveItem.blob_sha256)
        .where(
            DriveItem.status == DriveItemStatus.LANDED,
            DriveItem.blob_sha256.not_in(select(DocumentSource.blob_sha256)),
        )
        .order_by(DriveItem.path_cached)
    ).all()
    out: dict[Step, list[DriveItem]] = defaultdict(list)
    for item, restricted in rows:
        chain = ancestors.get(item.parent_item_id or "", [])
        if not item.path_cached or not in_scope(scope, item.root_name, chain, item.path_cached):
            out[Step.OUTSIDE_SCOPE].append(item)
        else:
            out[Step.HELD if restricted else Step.WAITING].append(item)
    return out


def _processing(session: Session, jobs: Jobs) -> dict[Step, list[uuid.UUID]]:
    ids = session.scalars(select(Document.doc_id).where(Document.status == DocumentStatus.PROCESSING))
    out: dict[Step, list[uuid.UUID]] = defaultdict(list)
    for doc_id in ids:
        out[Step.PROCESSING if str(doc_id) in jobs.held else Step.IN_LINE].append(doc_id)
    return out


def count_steps(session: Session, jobs: Jobs) -> list[StepCount]:
    counts = dict.fromkeys(Step, 0)
    for status_, n in session.execute(select(DriveItem.status, func.count()).group_by(DriveItem.status)):
        if status_ in LOCATION_STEP:
            counts[LOCATION_STEP[status_]] += n
    for step, items in _unclaimed(session).items():
        counts[step] += len(items)
    for status_, n in session.execute(select(Document.status, func.count()).group_by(Document.status)):
        if status_ in DOCUMENT_STEP:
            counts[DOCUMENT_STEP[status_]] += n
    for step, ids in _processing(session, jobs).items():
        counts[step] += len(ids)
    return [StepCount(step=step, count=n) for step, n in counts.items()]


def _location_file(item: DriveItem, detail: str | None) -> StepFile:
    return StepFile(
        name=item.name,
        path=item.path_cached,
        doc_id=None,
        route=None,
        updated_at=item.last_modified_at,
        detail=detail,
    )


def _locations(session: Session, step: Step, unclaimed: list[DriveItem], limit: int) -> tuple[int, list]:
    statuses = [s for s, st in LOCATION_STEP.items() if st == step]
    where = DriveItem.status.in_(statuses)
    total = session.scalar(select(func.count()).select_from(DriveItem).where(where)) or 0
    items = session.scalars(select(DriveItem).where(where).order_by(DriveItem.path_cached).limit(limit))
    files = []
    for item in items:
        detail = LOCATION_DETAIL.get(item.status)
        if item.status == DriveItemStatus.DOWNLOAD_FAILED:
            detail = f"download failed: {item.error_last}" if item.error_last else "download failed"
        files.append(_location_file(item, detail or item.gate_reason))
    files += [
        _location_file(item, UNCLAIMED_DETAIL.get(step)) for item in unclaimed[: max(0, limit - len(files))]
    ]
    return total + len(unclaimed), files


def _document_detail(document: Document, step: Step, jobs: Jobs) -> str | None:
    doc = str(document.doc_id)
    if step == Step.PROCESSING:
        return jobs.held.get(doc)
    if step == Step.IN_LINE:
        queue, place = jobs.waiting.get(doc, (None, 0))
        return f"place {place} in {queue}" if queue else NOT_QUEUED
    if document.status == DocumentStatus.WAITING_FOR_ROUTE:
        return f"route {document.route} is not switched on"
    if document.status == DocumentStatus.FAILED:
        error = str((document.metadata_sources or {}).get("error") or "")
        return error[:300] or None
    return DOCUMENT_DETAIL.get(document.status)


def _documents(session: Session, step: Step, jobs: Jobs, limit: int) -> tuple[int, list[StepFile]]:
    if step in (Step.PROCESSING, Step.IN_LINE):
        where = Document.doc_id.in_(_processing(session, jobs)[step])
    else:
        where = Document.status.in_([s for s, st in DOCUMENT_STEP.items() if st == step])
    total = session.scalar(select(func.count()).select_from(Document).where(where)) or 0
    path = (
        select(DocumentSource.doc_id, func.min(DriveItem.path_cached).label("path"))
        .join(DriveItem, DriveItem.blob_sha256 == DocumentSource.blob_sha256)
        .where(DocumentSource.role == DocumentSourceRole.PRIMARY)
        .group_by(DocumentSource.doc_id)
        .subquery()
    )
    rows = session.execute(
        select(Document, path.c.path)
        .outerjoin(path, path.c.doc_id == Document.doc_id)
        .where(where)
        .order_by(Document.updated_at.desc())
        .limit(limit)
    ).all()
    files = [
        StepFile(
            name=document.title or (p.rsplit("/", 1)[-1] if p else str(document.doc_id)),
            path=p,
            doc_id=document.doc_id,
            route=document.route,
            updated_at=document.updated_at,
            detail=_document_detail(document, step, jobs),
        )
        for document, p in rows
    ]
    return total, files


def list_step(session: Session, step: Step, jobs: Jobs, limit: int) -> StepFiles:
    """The files in ``step``: documents newest first, then OneDrive locations by path; at most ``limit``."""
    total, files = 0, []
    if step in DOCUMENT_STEP.values() or step in (Step.PROCESSING, Step.IN_LINE):
        total, files = _documents(session, step, jobs, limit)
    if step in LOCATION_STEP.values() or step in (Step.OUTSIDE_SCOPE, Step.WAITING):
        unclaimed = _unclaimed(session).get(step, [])
        more, located = _locations(session, step, unclaimed, limit - len(files))
        total, files = total + more, files + located
    return StepFiles(step=step, total=total, files=files)
