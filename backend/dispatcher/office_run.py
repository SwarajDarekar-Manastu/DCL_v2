"""Run Route A1 (S2's ``process_pdf``) for one PROCESSING document: S1's side of the route.

Loads the primary blob and its folder context, builds the stores and the vision service, records the
flags through the review gate (HALTED on HARD) and indexes and commits a clean result. With the models
role unreachable (or no indexer) a clean result is kept as ``processed.json`` and parked, as in Route C.
Only PDFs for now: DOCX/PPTX/PPT stay WAITING_FOR_ROUTE until A1.9–A1.10 exist.
"""

import mimetypes
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import ProcessedDocument
from backend.dispatcher.folder_context import FolderContext
from backend.dispatcher.routing import PROCESSED_MARK
from backend.indexing.commit import Indexer, commit_document
from backend.llm_engine.local_models import ModelServerUnavailable
from backend.postgres import pipeline_config
from backend.postgres.enums import DocumentSourceRole, DocumentStatus, DriveItemStatus
from backend.postgres.models import Blob, Document, DocumentSource, DriveItem, SyncRoot
from backend.review.staged import gate
from backend.storage.minio import ASSETS, CIR, BucketStore, parse_uri

PIPELINE_VERSION = 1


@dataclass(frozen=True)
class OfficeOutcome:
    doc_id: uuid.UUID
    status: str
    hard_flags: int
    soft_flags: int


BuildPdf = Callable[..., ProcessedDocument]


def default_build() -> BuildPdf:
    """S2's entry point with the production vision service (Docling is imported in the parse image only)."""
    from backend.llm_engine.gemini_client import GeminiClient
    from backend.llm_engine.vision.service import VisionService, vision_cache
    from backend.routes.a1_office.route import process_pdf

    vision = VisionService(GeminiClient(), vision_cache())

    def build(pdf_bytes: bytes, **kwargs: Any) -> ProcessedDocument:
        return process_pdf(pdf_bytes, vision=vision, **kwargs)

    return build


def _content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


def _read(minio: Minio, uri: str) -> bytes:
    bucket, key = parse_uri(uri)
    response = minio.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def process_a1_document(
    session: Session,
    minio: Minio,
    doc_id: uuid.UUID,
    build: BuildPdf,
    indexer: Indexer | None = None,
) -> OfficeOutcome:
    from backend.routes.a1_office.route import PARSER_VERSION, Stores

    document = session.get(Document, doc_id)
    if document is None:
        raise LookupError(f"document {doc_id} does not exist")
    if document.status != DocumentStatus.PROCESSING:
        return OfficeOutcome(doc_id, document.status, 0, 0)  # settled meanwhile
    blob = session.scalar(
        select(Blob)
        .join(DocumentSource, DocumentSource.blob_sha256 == Blob.sha256)
        .where(DocumentSource.doc_id == doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY)
    )
    item = session.scalar(
        select(DriveItem)
        .where(DriveItem.blob_sha256 == blob.sha256, DriveItem.status != DriveItemStatus.DELETED)
        .order_by(DriveItem.path_cached)
        .limit(1)
    )
    if item is None:
        raise LookupError(f"no live location holds the primary blob of {doc_id}")
    cloud_allowed = bool(
        session.scalar(select(SyncRoot.cloud_allowed).where(SyncRoot.root_name == item.root_name))
    )
    cir, assets = BucketStore(minio, CIR), BucketStore(minio, ASSETS)
    prefix = f"{blob.sha256}/A1/v{PARSER_VERSION}/"
    stores = Stores(
        put_cir=lambda key, data: cir.put(prefix + key, data),
        put_asset=lambda key, data: assets.put(key, data, _content_type(key)),
    )
    processed = build(
        _read(minio, blob.minio_uri),
        blob_sha256=blob.sha256,
        file_name=item.name,
        folder=FolderContext.model_validate(document.folder_context),
        stores=stores,
        cloud_allowed=cloud_allowed,
        doc_id=str(doc_id),
        critical_field_patterns=tuple(
            pipeline_config.get(session, "critical_field_patterns", default=[]) or []
        ),
        engine_by_script=pipeline_config.get(session, "routes.A1.ocr_engine_by_script", default=None),
    )
    result = gate(session, cir, document, processed)
    plan = None
    if not result.halted and indexer is not None:
        try:
            plan = indexer(session, result.document, document.doc_id, cloud_allowed)
        except ModelServerUnavailable:
            plan = None
    if plan is not None:
        committed = commit_document(session, document, result.document, plan, PIPELINE_VERSION)
        return OfficeOutcome(doc_id, committed.status, 0, result.soft)
    if not result.halted:
        uri = cir.put(prefix + "processed.json", processed.model_dump_json().encode(), "application/json")
        document.status = DocumentStatus.WAITING_FOR_ROUTE
        document.staged_payload_uri = None
        document.metadata_sources = {
            **(document.metadata_sources or {}),
            PROCESSED_MARK: {"adapter": "pdf", "parser_version": PARSER_VERSION, "uri": uri},
        }
    session.flush()
    return OfficeOutcome(doc_id, document.status, result.hard, result.soft)
