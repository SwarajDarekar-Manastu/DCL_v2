"""Phase 2 tasks. ``dcl.process.dispatch`` turns landed blobs inside ``processing.scope`` into documents
(backend/dispatcher/routing.py); route tasks are added here as the adapters land."""

from functools import lru_cache

from sqlalchemy.orm import Session

from backend.celery_redis.app import app
from backend.celery_redis.queues import Queue
from backend.config import get_settings
from backend.dispatcher.routing import dispatch as dispatch_scope
from backend.postgres.session import engine_from_settings
from backend.storage.minio import client_from_settings

IO_LIGHT = str(Queue.IO_LIGHT)


@lru_cache(maxsize=1)
def _engine():
    return engine_from_settings(get_settings())


@app.task(name="dcl.process.dispatch", queue=IO_LIGHT)
def dispatch() -> dict[str, int]:
    with Session(_engine(), expire_on_commit=False) as session:
        result = dispatch_scope(session, client_from_settings(get_settings()))
    return {"created": result.created, "waiting": result.waiting, "halted": result.halted}
