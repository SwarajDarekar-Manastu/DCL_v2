"""Phase 2 tasks. ``dcl.process.dispatch`` turns landed blobs inside ``processing.scope`` into documents
(backend/dispatcher/routing.py) and enqueues every PROCESSING document on its adapter's task;
``dcl.process.route_c`` runs Route C on ``telemetry_stream``; ``dcl.process.route_a1`` runs Route A1 (PDF)
on ``cpu_parse``."""

import uuid
from functools import lru_cache

from sqlalchemy.orm import Session

from backend.celery_redis.app import app
from backend.celery_redis.queues import POOLS, Queue
from backend.config import get_settings
from backend.dispatcher.routing import Release, sweep_documents
from backend.dispatcher.routing import dispatch as dispatch_scope
from backend.indexing.commit import default_indexer
from backend.llm_engine.gemini_types import BudgetExhausted, GatewayUnavailable
from backend.llm_engine.local_models import ModelServerUnavailable
from backend.postgres.enums import DocumentStatus
from backend.postgres.models import Document
from backend.postgres.session import engine_from_settings
from backend.routes.c_telemetry.pipeline import halted_documents_for_rule, process_document, resume_document
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
# Transient: the document stays PROCESSING and the task retries with backoff (S2: retry with a countdown).
RETRYABLE = (ConnectionError, TimeoutError, ModelServerUnavailable, BudgetExhausted, GatewayUnavailable)


@app.task(
    name="dcl.process.route_c",
    queue=TELEMETRY_STREAM,
    autoretry_for=RETRYABLE,
    retry_backoff=30,
    max_retries=POOLS[Queue.TELEMETRY_STREAM].max_retries,
)
def route_c(doc_id: str) -> dict[str, object]:
    """One Route C document (LabJack ``.dat``): raw Parquet, stats, channel resolution, gate."""
    minio = client_from_settings(get_settings())
    with Session(_engine(), expire_on_commit=False) as session:
        try:
            outcome = process_document(session, minio, uuid.UUID(doc_id), indexer=_indexer(minio))
        except RETRYABLE:
            session.rollback()
            raise
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


@app.task(
    name="dcl.process.resume_route_c",
    queue=TELEMETRY_STREAM,
    autoretry_for=RETRYABLE,
    retry_backoff=30,
    max_retries=POOLS[Queue.TELEMETRY_STREAM].max_retries,
)
def resume_route_c(doc_id: str) -> dict[str, object]:
    """``resume_from_staged`` for a HALTED Route C run (file 06 §7): rebuilt from its raw.parquet."""
    minio = client_from_settings(get_settings())
    with Session(_engine(), expire_on_commit=False) as session:
        try:
            outcome = resume_document(session, minio, uuid.UUID(doc_id), indexer=_indexer(minio))
        except RETRYABLE:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            _fail(session, uuid.UUID(doc_id), exc)
            raise
        session.commit()
    return {"doc_id": doc_id, "status": outcome.status, "hard_flags": outcome.hard_flags}


CPU_PARSE = str(Queue.CPU_PARSE)


@lru_cache(maxsize=1)
def _a1_build():
    from backend.dispatcher.office_run import default_build

    return default_build()


@app.task(
    name="dcl.process.route_a1",
    queue=CPU_PARSE,
    autoretry_for=RETRYABLE,
    retry_backoff=30,
    max_retries=POOLS[Queue.CPU_PARSE].max_retries,
)
def route_a1(doc_id: str) -> dict[str, object]:
    """One Route A1 document (PDF) through S2's ``process_pdf``, then the gate and the commit path."""
    from backend.dispatcher.office_run import process_a1_document

    minio = client_from_settings(get_settings())
    with Session(_engine(), expire_on_commit=False) as session:
        try:
            outcome = process_a1_document(
                session, minio, uuid.UUID(doc_id), _a1_build(), indexer=_indexer(minio)
            )
        except RETRYABLE:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            _fail(session, uuid.UUID(doc_id), exc)
            raise
        session.commit()
    return {
        "doc_id": doc_id,
        "status": outcome.status,
        "hard_flags": outcome.hard_flags,
        "soft_flags": outcome.soft_flags,
    }


@app.task(name="dcl.process.relocate_route_c_tables", queue=IO_LIGHT)
def relocate_route_c_tables() -> dict[str, int]:
    """One-off backfill: re-run Route C for committed documents whose table/row nodes have no locator, so
    the commit rewrites the nodes with sheet + cell_range or file lines (vectors reused by hash)."""
    from backend.routes.c_telemetry.pipeline import unlocated_table_documents

    with Session(_engine(), expire_on_commit=False) as session:
        doc_ids = unlocated_table_documents(session)
        for doc_id in doc_ids:
            session.get(Document, doc_id).status = DocumentStatus.PROCESSING
        session.commit()
    for doc_id in doc_ids:
        app.send_task("dcl.process.route_c", args=[str(doc_id)], queue=TELEMETRY_STREAM)
    return {"documents": len(doc_ids)}


@app.task(name="dcl.process.resume_for_rule", queue=IO_LIGHT)
def resume_for_rule(rule_id: str) -> dict[str, int]:
    """Retroactive pass after a channel_map rule is created or changed (file 06 §8): every HALTED Route C
    run the rule applies to is resumed on telemetry_stream."""
    with Session(_engine(), expire_on_commit=False) as session:
        doc_ids = halted_documents_for_rule(session, uuid.UUID(rule_id))
    for doc_id in doc_ids:
        app.send_task("dcl.process.resume_route_c", args=[str(doc_id)], queue=TELEMETRY_STREAM)
    return {"resumed": len(doc_ids)}


def _indexer(minio):
    """S2's indexing through the models role; without ``DCL_MODELS_URL`` a clean run is parked instead."""
    url = get_settings().models_url
    return default_indexer(str(url), minio) if url else None


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
