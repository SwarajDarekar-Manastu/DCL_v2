"""One runner for every route's document task (A1, A2, D, F): S1's side around a route's build step.

``run_document`` loads the PROCESSING document, its primary blob and location (derived blobs included),
the root's ``cloud_allowed``, CIR and asset stores under ``{sha}/{route}/v{parser_version}/``; calls the
route's ``build(ctx)``; records the flags through the review gate (HALTED on HARD); indexes and commits a
clean result, or keeps it as ``processed.json`` and parks it when the models role is unreachable.
``resume_staged`` continues a HALTED document whose HARD flags a person decided from its staged payload. Route
C keeps its own pipeline (series runs, resume from Parquet).
"""

import logging
import mimetypes
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import ProcessedDocument
from backend.dispatcher.folder_context import FolderContext, with_folder_labels
from backend.dispatcher.location import Location, primary_location
from backend.dispatcher.routing import PROCESSED_MARK
from backend.indexing.card import models_embedder, write_halted_card
from backend.indexing.commit import Indexer, commit_document
from backend.llm_engine.local_models import ModelServerUnavailable
from backend.postgres.enums import DocumentSourceRole, DocumentStatus, DriveItemStatus, Route
from backend.postgres.models import Blob, Document, DocumentSource, DriveItem, SyncRoot
from backend.review.staged import GateResult, gate, load_staged
from backend.storage.minio import ASSETS, CIR, RAW, BucketStore, parse_uri

PIPELINE_VERSION = 1
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Outcome:
    doc_id: uuid.UUID
    status: str
    hard_flags: int
    soft_flags: int


def content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


def read_object(minio: Minio, minio_uri: str) -> bytes:
    bucket, key = parse_uri(minio_uri)
    response = minio.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


@dataclass
class RunContext:
    session: Session
    minio: Minio
    document: Document
    blob: Blob
    where: Location
    cloud_allowed: bool
    cir: BucketStore
    assets: BucketStore
    prefix: str  # "{sha}/{route}/v{n}/"
    _data: bytes | None = field(default=None, repr=False)

    @property
    def data(self) -> bytes:
        if self._data is None:
            self._data = read_object(self.minio, self.blob.minio_uri)
        return self._data

    @property
    def folder(self) -> FolderContext:
        return FolderContext.model_validate(self.document.folder_context)

    def put_cir(self, key: str, data: bytes) -> str:
        return self.cir.put(self.prefix + key, data)

    def put_asset(self, key: str, data: bytes) -> str:
        return self.assets.put(key, data, content_type(key))


Build = Callable[[RunContext], ProcessedDocument]


@lru_cache(maxsize=1)
def _gateway():
    from backend.llm_engine.gemini_client import GeminiClient, result_cache_store
    from backend.llm_engine.vision.service import vision_cache

    return GeminiClient(result_cache=result_cache_store()), vision_cache()


def vision_for(session: Session, file=None):
    """The production VisionService: one gateway client per worker, the safety setting read per document, and
    ``file`` (``file_metadata(ctx)``) so every image call of this document carries the file's own metadata."""
    from backend.llm_engine.vision.service import VisionService, extraction_safety_from

    client, cache = _gateway()
    return VisionService(client, cache, extraction_safety=extraction_safety_from(session), file=file)


def file_metadata(ctx: "RunContext"):
    """The ingestion metadata of the document's file for the image prompt (``image_context``)."""
    from backend.llm_engine.vision.service import FileMetadata

    folder = ctx.folder
    items = ctx.session.scalars(
        select(DriveItem)
        .where(DriveItem.blob_sha256 == ctx.blob.sha256, DriveItem.status != DriveItemStatus.DELETED)
        .order_by(DriveItem.path_cached)
        .limit(20)
    ).all()
    here = next((i for i in items if i.path_cached == folder.path_cached), items[0] if items else None)
    derived = (ctx.document.metadata_sources or {}).get("derived_from") or {}
    parent = None
    if derived.get("doc_id"):
        parent_doc = ctx.session.get(Document, uuid.UUID(derived["doc_id"]))
        parent = f"{parent_doc.title if parent_doc else 'another file'} (member {derived.get('member_path')})"
    return FileMetadata(
        file_name=ctx.where.name,
        folder_path="/".join(folder.breadcrumb) or None,
        site=ctx.where.root_name,
        created_at=here.created_at_source.date().isoformat() if here and here.created_at_source else None,
        modified_at=here.last_modified_at.date().isoformat() if here and here.last_modified_at else None,
        parent=parent,
        test_plan_id=folder.test_plan_id,
        test_run_id=folder.test_run_id,
        hardware_item=folder.hardware_item,
        source_origin=str(folder.source_origin) if folder.source_origin else None,
        other_locations=tuple(i.path_cached for i in items if i is not here and i.path_cached)[:5],
    )


def _own_flag(route: Route):
    """A flag this route raised on an earlier run of the document. A re-run that does not raise it again (the
    finding is gone, or its anchor moved) closes it as AUTO_RESOLVED instead of leaving it open beside the new
    one. The dispatcher's assembler notes carry the route too but are not the route's (label "assembler")."""

    def own(row) -> bool:
        side = (row.evidence or {}).get("a") or {}
        return row.route == str(route) and side.get("label") != "assembler"

    return own


def run_document(
    session: Session,
    minio: Minio,
    doc_id: uuid.UUID,
    route: Route,
    parser_version: int,
    build: Build,
    indexer: Indexer | None = None,
) -> Outcome:
    document = session.get(Document, doc_id)
    if document is None:
        raise LookupError(f"document {doc_id} does not exist")
    if document.status != DocumentStatus.PROCESSING:
        return Outcome(doc_id, document.status, 0, 0)  # settled meanwhile
    blob = session.scalar(
        select(Blob)
        .join(DocumentSource, DocumentSource.blob_sha256 == Blob.sha256)
        .where(DocumentSource.doc_id == doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY)
    )
    where = primary_location(session, blob.sha256)
    if where is None:
        raise LookupError(f"no live location holds the primary blob of {doc_id}")
    cloud_allowed = _cloud_allowed(session, where)
    cir = BucketStore(minio, CIR)
    ctx = RunContext(
        session,
        minio,
        document,
        blob,
        where,
        cloud_allowed,
        cir,
        BucketStore(minio, ASSETS),
        f"{blob.sha256}/{route}/v{parser_version}/",
    )
    processed = with_folder_labels(build(ctx), ctx.folder)
    result = gate(session, cir, document, processed, stale=_own_flag(route))
    if result.halted:
        write_halted_card(document, processed.document, embed=models_embedder())
    plan = _index(session, document, result, cloud_allowed, indexer)
    if plan is not None:
        committed = commit_document(
            session, document, result.document, plan, PIPELINE_VERSION, raw=BucketStore(minio, RAW)
        )
        return Outcome(doc_id, committed.status, 0, result.soft)
    if not result.halted:
        uri = ctx.put_cir("processed.json", processed.model_dump_json().encode())
        document.status = DocumentStatus.WAITING_FOR_ROUTE
        document.staged_payload_uri = None
        document.metadata_sources = {
            **(document.metadata_sources or {}),
            PROCESSED_MARK: {"route": str(route), "parser_version": parser_version, "uri": uri},
        }
    session.flush()
    return Outcome(doc_id, document.status, result.hard, result.soft)


def resume_staged(session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer) -> Outcome:
    """``resume_from_staged`` (file 06 §7) for every route but C: a HALTED document goes on from its staged
    payload without parsing again; the gate runs again (a decided HARD flag no longer halts), then index and
    commit. An open HARD flag keeps it HALTED. The models role unreachable raises: the task rolls back to
    HALTED and retries."""
    document = session.get(Document, doc_id)
    if document is None:
        raise LookupError(f"document {doc_id} does not exist")
    if document.status != DocumentStatus.HALTED or document.route == Route.C:
        return Outcome(doc_id, document.status, 0, 0)
    cir = BucketStore(minio, CIR)
    staged = with_folder_labels(
        load_staged(cir, document), FolderContext.model_validate(document.folder_context)
    )
    document.status = DocumentStatus.PROCESSING
    document.staged_payload_uri = None
    session.flush()
    result = gate(session, cir, document, staged)
    if result.halted:
        write_halted_card(document, staged.document, embed=models_embedder())
        return Outcome(doc_id, document.status, result.hard, result.soft)
    where = primary_location(session, staged.blob_sha256)
    if where is None:
        raise LookupError(f"no live location holds the primary blob of {doc_id}")
    plan = indexer(session, result.document, doc_id, _cloud_allowed(session, where))
    committed = commit_document(
        session, document, result.document, plan, PIPELINE_VERSION, raw=BucketStore(minio, RAW)
    )
    return Outcome(doc_id, committed.status, 0, result.soft)


def _cloud_allowed(session: Session, where: Location) -> bool:
    return bool(session.scalar(select(SyncRoot.cloud_allowed).where(SyncRoot.root_name == where.root_name)))


def _index(session: Session, document: Document, result: GateResult, cloud_allowed: bool, indexer):
    if result.halted or indexer is None:
        return None
    try:
        return indexer(session, result.document, document.doc_id, cloud_allowed)
    except ModelServerUnavailable as exc:
        log.warning("models role unreachable for %s; the clean result is parked: %s", document.doc_id, exc)
        return None


def common_options(ctx: RunContext) -> dict[str, Any]:
    return {
        "blob_sha256": ctx.blob.sha256,
        "file_name": ctx.where.name,
        "cloud_allowed": ctx.cloud_allowed,
        "doc_id": str(ctx.document.doc_id),
    }
