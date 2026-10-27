"""Decided files that did not move on (file 06 §7 safety net, added 2026-10-27).

A decision hands its file to the next step with one task message (a resume or a rebuild), and nothing checked
that the step happened. On 2026-10-27 22 telemetry files whose units people had approved stayed HALTED: their
resumes met a full disk, rolled back, and were never sent again. ``stalled`` finds such files (beat, every 30
minutes):

- HALTED with no open HARD flag: every blocking question is answered, so the file resumes (Route C from its
  run, every other route from its staged payload). A resume that failed left it HALTED with its error in
  ``metadata_sources.error``; it is resumed again here.
- FAILED after an error that passes (storage full or unreachable, gateway or models down, retries spent:
  ``metadata_sources.error_transient``): its route runs it again.
- PROCESSING for longer than RESEND_AFTER: its run or rebuild message was lost (a stopped worker, a rebuild
  after an undo that never ran): its route runs it again.

Each file is sent again at most MAX_RERUNS times (``metadata_sources.reruns``), so a file that keeps coming
back to the same state stops costing work and waits for a person in Ops. A file that has moved on (ACTIVE)
loses these marks, so a later failure starts from zero.

A file is sent again at most once per RESEND_AFTER (``metadata_sources.resent_at``), so a stopped worker gets
one waiting message, not one per sweep.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.celery_redis.queues import Queue
from backend.dispatcher.adapters import task_for_route
from backend.dispatcher.routing import Release
from backend.postgres.enums import DocumentStatus, FlagSeverity, FlagStatus, Route
from backend.postgres.models import Document, ReviewFlag

RESEND_AFTER = timedelta(hours=2)
MAX_RERUNS = 6
OPEN = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)
RESUME_C = ("dcl.process.resume_route_c", Queue.TELEMETRY_STREAM)
RESUME_STAGED = ("dcl.process.resume_staged", Queue.CPU_PARSE)
MOVED_ON = (DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS)
MARKS = ("reruns", "resent_at", "error_transient")


def stalled(session: Session, now: datetime | None = None) -> list[Release]:
    """The files to send again, marked as sent; the caller commits, then enqueues."""
    now = now or datetime.now(UTC)
    blocked = select(ReviewFlag.doc_id).where(
        ReviewFlag.severity == FlagSeverity.HARD, ReviewFlag.status.in_(OPEN), ReviewFlag.doc_id.is_not(None)
    )
    halted = session.scalars(
        select(Document).where(Document.status == DocumentStatus.HALTED, Document.doc_id.not_in(blocked))
    ).all()
    failed = session.scalars(select(Document).where(Document.status == DocumentStatus.FAILED)).all()
    stuck = session.scalars(
        select(Document).where(
            Document.status == DocumentStatus.PROCESSING, Document.updated_at < now - RESEND_AFTER
        )
    ).all()
    releases = []
    for document in halted:
        if _due(document, now) and (document.metadata_sources or {}).get("reruns", 0) < MAX_RERUNS:
            task, queue = RESUME_C if document.route == Route.C else RESUME_STAGED
            releases.append(_send(document, task, queue, now))
    for document in failed:
        meta = document.metadata_sources or {}
        found = task_for_route(Route(document.route)) if document.route else None
        again = meta.get("error_transient") and meta.get("reruns", 0) < MAX_RERUNS
        if found and again and _due(document, now):
            document.status = DocumentStatus.PROCESSING
            document.staged_payload_uri = None
            releases.append(_send(document, *found, now))
    for document in stuck:
        found = task_for_route(Route(document.route)) if document.route else None
        if found and _due(document, now) and (document.metadata_sources or {}).get("reruns", 0) < MAX_RERUNS:
            releases.append(_send(document, *found, now))
    for document in session.scalars(
        select(Document).where(Document.status.in_(MOVED_ON), Document.metadata_sources.has_key("reruns"))
    ):
        document.metadata_sources = {k: v for k, v in document.metadata_sources.items() if k not in MARKS}
    session.flush()
    return releases


def _due(document: Document, now: datetime) -> bool:
    sent = (document.metadata_sources or {}).get("resent_at")
    return sent is None or now - datetime.fromisoformat(sent) >= RESEND_AFTER


def _send(document: Document, task: str, queue: Queue, now: datetime) -> Release:
    meta = document.metadata_sources or {}
    document.metadata_sources = {**meta, "resent_at": now.isoformat(), "reruns": meta.get("reruns", 0) + 1}
    return Release(doc_id=document.doc_id, task=task, queue=str(queue))
