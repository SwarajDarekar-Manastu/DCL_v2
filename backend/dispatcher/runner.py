"""One runner for every route's document task (A1, A2, D, F): S1's side around a route's build step.

``run_document`` loads the PROCESSING document, its primary blob and location (derived blobs included),
the root's ``cloud_allowed``, CIR and asset stores under ``{sha}/{route}/v{parser_version}/``; calls the
route's ``build(ctx)``; records the flags through the review gate (HALTED on HARD); indexes and commits a
clean result, or keeps it as ``processed.json`` and parks it when the models role is unreachable. Route C
keeps its own pipeline (series runs, resume from Parquet).
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
from backend.dispatcher.folder_context import FolderContext
from backend.dispatcher.location import Location, primary_location
from backend.dispatcher.routing import PROCESSED_MARK
from backend.indexing.commit import Indexer, commit_document
from backend.llm_engine.local_models import ModelServerUnavailable
from backend.postgres.enums import DocumentSourceRole, DocumentStatus, Route
from backend.postgres.models import Blob, Document, DocumentSource, SyncRoot
from backend.review.staged import gate
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
    from backend.llm_engine.gemini_client import GeminiClient
    from backend.llm_engine.vision.service import vision_cache

    return GeminiClient(), vision_cache()


def vision_for(session: Session):
    """The production VisionService: one gateway client per worker, the safety setting read per document."""
    from backend.llm_engine.vision.service import VisionService, extraction_safety_from

    client, cache = _gateway()
    return VisionService(client, cache, extraction_safety=extraction_safety_from(session))


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
    cloud_allowed = bool(
        session.scalar(select(SyncRoot.cloud_allowed).where(SyncRoot.root_name == where.root_name))
    )
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
    processed = build(ctx)
    result = gate(session, cir, document, processed)
    plan = None
    if not result.halted and indexer is not None:
        try:
            plan = indexer(session, result.document, document.doc_id, cloud_allowed)
        except ModelServerUnavailable as exc:
            log.warning("models role unreachable for %s; the clean result is parked: %s", doc_id, exc)
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


def common_options(ctx: RunContext) -> dict[str, Any]:
    return {
        "blob_sha256": ctx.blob.sha256,
        "file_name": ctx.where.name,
        "cloud_allowed": ctx.cloud_allowed,
        "doc_id": str(ctx.document.doc_id),
    }
