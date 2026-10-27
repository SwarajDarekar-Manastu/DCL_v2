"""Phase 2 tasks. ``dcl.process.dispatch`` turns landed blobs inside ``processing.scope`` into documents
(backend/dispatcher/routing.py) and enqueues every PROCESSING document on its adapter's task;
``dcl.process.route_c`` runs Route C on ``telemetry_stream``; ``dcl.process.route_a1`` runs Route A1 (PDF)
on ``cpu_parse``; ``dcl.process.reconcile`` sends again the files a decision should have moved on and did not
(backend/dispatcher/reconcile.py)."""

import uuid
from collections.abc import Callable
from functools import lru_cache

from celery import current_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from backend.celery_redis.app import app
from backend.celery_redis.queues import POOLS, Queue
from backend.common.telemetry import METRICS
from backend.config import get_settings
from backend.dispatcher.reconcile import stalled
from backend.dispatcher.routing import Release, sweep_documents
from backend.dispatcher.routing import dispatch as dispatch_scope
from backend.indexing.commit import default_indexer
from backend.llm_engine.gemini_types import BudgetExhausted, GatewayError, GatewayUnavailable
from backend.llm_engine.local_models import ModelServerUnavailable
from backend.postgres.enums import DocumentStatus
from backend.postgres.models import Document
from backend.postgres.session import engine_from_settings
from backend.routes.c_telemetry.pipeline import halted_documents_for_rule, process_document, resume_document
from backend.storage.minio import client_from_settings, unavailable

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


@app.task(name="dcl.process.reconcile", queue=IO_LIGHT)
def reconcile() -> dict[str, int]:
    """Every 30 minutes: decided files that did not move on are sent again (reconcile.py)."""
    with Session(_engine(), expire_on_commit=False) as session:
        releases = stalled(session)
        session.commit()
    for release in releases:
        enqueue_release(release)
    return {"sent": len(releases)}


@app.task(name="dcl.process.sweep_documents", queue=IO_LIGHT)
def sweep() -> dict[str, int]:
    """Daily safety net for document states (superseded, deleted, quarantined)."""
    with Session(_engine(), expire_on_commit=False) as session:
        counts = sweep_documents(session)
        session.commit()
    return counts


TELEMETRY_STREAM = str(Queue.TELEMETRY_STREAM)
# Transient: the document stays PROCESSING and the task retries with backoff (S2: retry with a countdown); a
# gateway error the client marks retryable (unreachable, 429, 5xx after its own attempts) is transient too.
# After the last retry the document is FAILED (file 02 §7: "PROCESSING -> FAILED: exception after retries").
RETRYABLE = (ConnectionError, TimeoutError, ModelServerUnavailable, BudgetExhausted, GatewayUnavailable)
RETRY_BACKOFF_S = 30
MAX_CHECKPOINTS = 12  # Route F: twelve more task runs of up to an hour each for one recording
RETRY_BACKOFF_MAX_S = 600


@app.task(
    name="dcl.process.route_c",
    queue=TELEMETRY_STREAM,
    max_retries=POOLS[Queue.TELEMETRY_STREAM].max_retries,
)
def route_c(doc_id: str) -> dict[str, object]:
    """One Route C document (LabJack ``.dat``): raw Parquet, stats, channel resolution, gate."""
    minio = client_from_settings(get_settings())
    with Session(_engine(), expire_on_commit=False) as session:
        try:
            outcome = process_document(session, minio, uuid.UUID(doc_id), indexer=_indexer(minio))
        except Exception as exc:
            _settle(session, uuid.UUID(doc_id), exc)
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
    max_retries=POOLS[Queue.TELEMETRY_STREAM].max_retries,
)
def resume_route_c(doc_id: str) -> dict[str, object]:
    """``resume_from_staged`` for a HALTED Route C run (file 06 §7): rebuilt from its raw.parquet. A file that
    is no longer HALTED (resumed by an earlier message) is left alone."""
    minio = client_from_settings(get_settings())
    with Session(_engine(), expire_on_commit=False) as session:
        document = session.get(Document, uuid.UUID(doc_id))
        if document is None or document.status != DocumentStatus.HALTED:
            return {"doc_id": doc_id, "status": document.status if document else None, "hard_flags": 0}
        try:
            outcome = resume_document(session, minio, uuid.UUID(doc_id), indexer=_indexer(minio))
        except Exception as exc:
            _settle(session, uuid.UUID(doc_id), exc)
            raise
        session.commit()
    return {"doc_id": doc_id, "status": outcome.status, "hard_flags": outcome.hard_flags}


CPU_PARSE = str(Queue.CPU_PARSE)


@lru_cache(maxsize=1)
def _a1_build():
    from backend.dispatcher.office_run import default_build

    return default_build()


def _run(
    doc_id: str,
    process,
    retryable: tuple[type[Exception], ...] = RETRYABLE,
    checkpoint: Callable[[], None] | None = None,
) -> dict[str, object]:
    """One document through a route runner; transient errors retry, anything else marks it FAILED. A route
    that saves its progress (``checkpoint``) is sent again at its soft time limit (file 03 time budget)."""
    minio = client_from_settings(get_settings())
    with Session(_engine(), expire_on_commit=False) as session:
        try:
            outcome = process(session, minio, uuid.UUID(doc_id), _indexer(minio))
        except Exception as exc:
            if checkpoint is not None and isinstance(exc, SoftTimeLimitExceeded):
                session.rollback()  # the document stays PROCESSING; the next run reads the saved parts
                checkpoint()
                return {"doc_id": doc_id, "status": "continued"}
            _settle(session, uuid.UUID(doc_id), exc, retryable)
            raise
        session.commit()
    return {
        "doc_id": doc_id,
        "status": outcome.status,
        "hard_flags": outcome.hard_flags,
        "soft_flags": outcome.soft_flags,
    }


def _route_task(name: str, queue: Queue):
    return app.task(name=name, queue=str(queue), max_retries=POOLS[queue].max_retries)


@_route_task("dcl.process.resume_staged", Queue.CPU_PARSE)
def resume_staged(doc_id: str) -> dict[str, object]:
    """A HALTED document of any route but C whose HARD flags were decided, from its staged payload (06 §7)."""
    from backend.dispatcher.runner import resume_staged as resume

    return _run(doc_id, resume)


@_route_task("dcl.process.route_a1", Queue.CPU_PARSE)
def route_a1(doc_id: str) -> dict[str, object]:
    """Route A1 (PDF, Word family, slides) through S2's ``process_office``."""
    from backend.dispatcher.office_run import process_a1_document

    return _run(doc_id, lambda s, m, d, i: process_a1_document(s, m, d, _a1_build(), indexer=i))


@_route_task("dcl.process.route_a2", Queue.CPU_PARSE)
def route_a2(doc_id: str) -> dict[str, object]:
    """Route A2 (LaTeX projects, report JSON) through S6's ``backend.routes.a2_source``."""
    from backend.dispatcher.source_run import process_a2_document

    return _run(doc_id, process_a2_document)


@_route_task("dcl.process.route_b", Queue.CPU_PARSE)
def route_b(doc_id: str) -> dict[str, object]:
    """Route B (Python, C, MATLAB, notebooks, Markdown, text) through S6's ``backend.routes.b_code``."""
    from backend.dispatcher.source_run import process_b_document

    return _run(doc_id, process_b_document)


@_route_task("dcl.process.route_e", Queue.CPU_PARSE)
def route_e(doc_id: str) -> dict[str, object]:
    """Route E (diagrams and drawings) through S6's ``backend.routes.e_diagrams``."""
    from backend.dispatcher.source_run import process_e_document

    return _run(doc_id, process_e_document)


@_route_task("dcl.process.route_g", Queue.CPU_PARSE)
def route_g(doc_id: str) -> dict[str, object]:
    """Route G (archives, ANSYS packages, CAD) through S6's ``backend.routes.g_archives``."""
    from backend.dispatcher.source_run import process_g_document

    return _run(doc_id, process_g_document)


def _media_retryable():
    from backend.dispatcher.media_run import RepresentativePending

    return (*RETRYABLE, RepresentativePending)


@_route_task("dcl.process.route_d", Queue.MEDIA)
def route_d(doc_id: str) -> dict[str, object]:
    """Route D (photos) through S2's ``process_photo``; burst members wait for their representative."""
    from backend.dispatcher.media_run import process_d_document

    return _run(doc_id, process_d_document, _media_retryable())


@_route_task("dcl.process.route_f", Queue.MEDIA)
def route_f(doc_id: str, checkpoints: int = 0) -> dict[str, object]:
    """Route F (videos) through S2's ``process_video`` with the local Whisper transcriber. A long recording
    keeps its finished transcription parts; at the soft time limit the task sends itself again to continue
    (at most ``MAX_CHECKPOINTS`` times, so a file that never finishes ends FAILED)."""
    from backend.dispatcher.media_run import process_f_document

    def again() -> None:
        app.send_task(
            "dcl.process.route_f",
            args=[doc_id],
            kwargs={"checkpoints": checkpoints + 1},
            queue=str(Queue.MEDIA),
        )

    return _run(doc_id, process_f_document, checkpoint=again if checkpoints < MAX_CHECKPOINTS else None)


@app.task(name="dcl.process.refresh_halted_route_c", queue=IO_LIGHT)
def refresh_halted_route_c() -> dict[str, int]:
    """One-off: resume every HALTED Route C document from its own raw.parquet so its flags carry the
    current evidence (sample rows, column index, downsampled series for the Review UI). Still HALTED after."""
    from sqlalchemy import select

    with Session(_engine(), expire_on_commit=False) as session:
        doc_ids = list(
            session.scalars(
                select(Document.doc_id).where(Document.route == "C", Document.status == DocumentStatus.HALTED)
            )
        )
    for doc_id in doc_ids:
        app.send_task("dcl.process.resume_route_c", args=[str(doc_id)], queue=TELEMETRY_STREAM)
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


def _settle(
    session: Session, doc_id: uuid.UUID, exc: Exception, retryable: tuple[type[Exception], ...] = RETRYABLE
) -> None:
    """After a route raised: a transient error with retries left schedules a retry (the document stays
    PROCESSING); any other error, or a transient one on the last retry, leaves the document FAILED. MinIO
    full, busy or unreachable is transient too, and counted (alert DclStorageUnavailable)."""
    session.rollback()
    storage = unavailable(exc)
    if storage:
        METRICS.storage_unavailable_total.add(1)
    transient = storage or isinstance(exc, retryable) or (isinstance(exc, GatewayError) and exc.retryable)
    task = current_task
    if transient and task and not task.request.called_directly and task.request.retries < task.max_retries:
        countdown = min(RETRY_BACKOFF_S * 2**task.request.retries, RETRY_BACKOFF_MAX_S)
        raise task.retry(exc=exc, countdown=countdown)
    _fail(session, doc_id, exc, transient)


def _fail(session: Session, doc_id: uuid.UUID, exc: Exception, transient: bool = False) -> None:
    """An unexpected error leaves the document FAILED with the error recorded, never half-written. A resume
    that failed has rolled its file back to HALTED: it stays HALTED with its staged payload, and the error is
    kept so the case shows it and the reconciler resumes it again. ``error_transient`` lets the reconciler
    run a FAILED file again once the cause has passed."""
    document = session.get(Document, doc_id)
    if document is None or document.status not in (DocumentStatus.PROCESSING, DocumentStatus.HALTED):
        return
    if document.status == DocumentStatus.PROCESSING:
        document.status = DocumentStatus.FAILED
    document.metadata_sources = {
        **(document.metadata_sources or {}),
        "error": f"{type(exc).__name__}: {exc}",
        "error_transient": transient,
    }
    session.commit()


def enqueue_release(release: Release) -> None:
    app.send_task(release.task, args=[str(release.doc_id)], queue=release.queue)
