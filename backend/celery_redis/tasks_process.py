"""Phase 2 tasks. ``dcl.process.dispatch`` turns landed blobs inside ``processing.scope`` into documents
(backend/dispatcher/routing.py) and enqueues every PROCESSING document on its adapter's task;
``dcl.process.route_c`` runs Route C on ``telemetry_stream``."""

import uuid
from functools import lru_cache

from sqlalchemy.orm import Session

from backend.celery_redis.app import app
from backend.celery_redis.queues import POOLS, Queue
from backend.config import get_settings
from backend.dispatcher.routing import Release, sweep_documents
from backend.dispatcher.routing import dispatch as dispatch_scope
from backend.postgres.enums import DocumentStatus
from backend.postgres.models import Document
from backend.postgres.session import engine_from_settings
from backend.routes.c_telemetry.pipeline import process_document
from backend.storage.minio import client_from_settings

IO_LIGHT = str(Queue.IO_LIGHT)


@lru_cache(maxsize=1)
def _engine():
    return engine_from_settings(get_settings())


@app.task(name="dcl.process.dispatch", queue=IO_LIGHT)
def dispatch() -> dict[str, int]:
    with Session(_engine(), expire_on_commit=False) as session:
        result = dispatch_scope(session, client_from_settings(get_settings()), enqueue=enqueue_release)
    return {
        "created": result.created,
        "waiting": result.waiting,
        "halted": result.halted,
        "released": result.released,
        "enqueued": len(result.to_process),
    }


@app.task(name="dcl.process.sweep_documents", queue=IO_LIGHT)
def sweep() -> dict[str, int]:
    """Daily safety net for document states (superseded, deleted, quarantined)."""
    with Session(_engine(), expire_on_commit=False) as session:
        counts = sweep_documents(session)
        session.commit()
    return counts


TELEMETRY_STREAM = str(Queue.TELEMETRY_STREAM)


@app.task(
    name="dcl.process.route_c",
    queue=TELEMETRY_STREAM,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=30,
    max_retries=POOLS[Queue.TELEMETRY_STREAM].max_retries,
)
def route_c(doc_id: str) -> dict[str, object]:
    """One Route C document (LabJack ``.dat``): raw Parquet, stats, channel resolution, gate."""
    with Session(_engine(), expire_on_commit=False) as session:
        try:
            outcome = process_document(session, client_from_settings(get_settings()), uuid.UUID(doc_id))
        except Exception as exc:
            session.rollback()
            _fail(session, uuid.UUID(doc_id), exc)
            raise
        session.commit()
    return {
        "doc_id": doc_id,
        "status": outcome.status,
        "rows": outcome.rows,
        "channels": outcome.channels,
        "hard_flags": outcome.hard_flags,
        "soft_flags": outcome.soft_flags,
    }


def _fail(session: Session, doc_id: uuid.UUID, exc: Exception) -> None:
    """An unexpected error leaves the document FAILED with the error recorded, never half-written."""
    document = session.get(Document, doc_id)
    if document is not None and document.status == DocumentStatus.PROCESSING:
        document.status = DocumentStatus.FAILED
        document.metadata_sources = {
            **(document.metadata_sources or {}),
            "error": f"{type(exc).__name__}: {exc}",
        }
        session.commit()


def enqueue_release(release: Release) -> None:
    app.send_task(release.task, args=[str(release.doc_id)], queue=release.queue)
