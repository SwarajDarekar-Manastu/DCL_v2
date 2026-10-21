"""Sync tasks on ``io_light`` (file 02 §3.6): delta per root, downloads, token health.

Each task body calls one plain function below with its dependencies as arguments, so the logic is
tested without a worker. A delta run keeps inside the queue's soft time limit: it stops after the
first committed page past its budget and re-enqueues itself, resuming from the page checkpoint.
Beat schedules live in ``backend/celery_redis/beat.py`` (S4).
"""

import logging
import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from functools import lru_cache

import httpx
import redis
from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.celery_redis.app import app
from backend.celery_redis.queues import POOLS, Queue
from backend.config import Group, get_settings
from backend.postgres.enums import AuthStatus, DriveItemStatus, SyncRootStatus
from backend.postgres.models import DriveItem, SyncRoot
from backend.postgres.session import engine_from_settings
from backend.storage.minio import client_from_settings
from backend.sync.auth import GraphAuthConfig, ReauthRequired, TokenProvider
from backend.sync.delta import ResyncRequired, run_root, seed_roots
from backend.sync.downloader import DownloadMismatch, land_item
from backend.sync.graph_client import GraphClient

log = logging.getLogger(__name__)

IO_LIGHT = str(Queue.IO_LIGHT)
DELTA_BUDGET_S = POOLS[Queue.IO_LIGHT].soft_time_limit_s - 60
LOCK_TTL_S = POOLS[Queue.IO_LIGHT].time_limit_s + 60
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BATCH = 500


class Outcome(StrEnum):
    DONE = "done"
    CONTINUED = "continued"
    LOCKED = "locked"
    RESYNC_REQUIRED = "resync_required"
    LANDED = "landed"
    SKIPPED = "skipped"
    RETRY = "retry"
    FAILED = "failed"


# ---------------------------------------------------------------- process-wide clients (worker only)


@lru_cache(maxsize=1)
def _engine():
    return engine_from_settings(get_settings())


@lru_cache(maxsize=1)
def _tokens() -> TokenProvider:
    return TokenProvider.create(GraphAuthConfig.from_settings(get_settings()))


@lru_cache(maxsize=1)
def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().require(Group.REDIS).redis_url)


@lru_cache(maxsize=1)
def _minio() -> Minio:
    return client_from_settings(get_settings())


# ---------------------------------------------------------------- testable bodies


def run_delta(
    session: Session,
    graph: GraphClient,
    root_name: str,
    lock: redis.Redis,
    budget_s: float = DELTA_BUDGET_S,
    clock: Callable[[], float] = time.monotonic,
) -> Outcome:
    key, token = f"sync:lock:{root_name}", str(uuid.uuid4())
    if not lock.set(key, token, nx=True, ex=LOCK_TTL_S):
        return Outcome.LOCKED
    try:
        root = session.get(SyncRoot, root_name)
        if root is None:
            raise LookupError(f"no sync root {root_name!r}")
        try:
            stats = run_root(session, graph, root, deadline=clock() + budget_s, clock=clock)
        except ResyncRequired:
            session.rollback()
            root.status = SyncRootStatus.RESYNCING
            session.commit()
            log.error("delta token expired for %s; resync required", root_name)
            return Outcome.RESYNC_REQUIRED
        return Outcome.DONE if stats.finished else Outcome.CONTINUED
    finally:
        if lock.get(key) in (token, token.encode()):
            lock.delete(key)


def download_one(
    session: Session,
    graph: GraphClient,
    minio: Minio,
    content_http: httpx.Client,
    location_id: uuid.UUID,
    attempt: int,
) -> Outcome:
    item = session.get(DriveItem, location_id)
    if item is None or item.status != DriveItemStatus.PENDING_DOWNLOAD:
        return Outcome.SKIPPED
    try:
        land_item(session, graph, minio, location_id, content_http)
        session.commit()
        return Outcome.LANDED
    except DownloadMismatch as exc:
        session.rollback()
        if attempt + 1 < DOWNLOAD_ATTEMPTS:
            return Outcome.RETRY
        item = session.get(DriveItem, location_id)
        item.status, item.error_last = DriveItemStatus.DOWNLOAD_FAILED, str(exc)
        session.commit()
        return Outcome.FAILED


def pending_downloads(session: Session, limit: int = DOWNLOAD_BATCH) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(DriveItem.location_id)
            .where(DriveItem.status == DriveItemStatus.PENDING_DOWNLOAD)
            .limit(limit)
        )
    )


def check_token_health(session: Session, graph: GraphClient, drive_id: str, first_root_item_id: str) -> bool:
    """Metadata GET on the first configured root (file 02 §1); sets every root's ``auth_status``."""
    try:
        ok = (
            graph.get(f"/drives/{drive_id}/items/{first_root_item_id}", params={"$select": "id"}).status_code
            == 200
        )
    except ReauthRequired:
        ok = False
    status = AuthStatus.OK if ok else AuthStatus.REAUTH_REQUIRED
    for root in session.scalars(select(SyncRoot)):
        root.auth_status = status
    session.commit()
    if not ok:
        log.error("Graph token health check failed; device-code sign-in required")
    return ok


# ---------------------------------------------------------------- tasks


@app.task(name="dcl.sync.delta_root", queue=IO_LIGHT)
def delta_root(root_name: str) -> str:
    with Session(_engine(), expire_on_commit=False) as session, GraphClient(_tokens().access_token) as graph:
        outcome = run_delta(session, graph, root_name, _redis())
    if outcome == Outcome.CONTINUED:
        delta_root.apply_async(args=[root_name], queue=IO_LIGHT)
    return outcome


@app.task(name="dcl.sync.delta_all", queue=IO_LIGHT)
def delta_all() -> list[str]:
    with Session(_engine(), expire_on_commit=False) as session:
        names = [root.root_name for root in seed_roots(session, get_settings())]
        session.commit()
    for name in names:
        delta_root.apply_async(args=[name], queue=IO_LIGHT)
    return names


@app.task(name="dcl.sync.download", queue=IO_LIGHT, bind=True, max_retries=DOWNLOAD_ATTEMPTS)
def download(self, location_id: str) -> str:
    with (
        Session(_engine(), expire_on_commit=False) as session,
        GraphClient(_tokens().access_token) as graph,
        httpx.Client(timeout=60.0) as content_http,
    ):
        outcome = download_one(
            session, graph, _minio(), content_http, uuid.UUID(location_id), self.request.retries
        )
    if outcome == Outcome.RETRY:
        raise self.retry(countdown=30 * 2**self.request.retries)
    return outcome


@app.task(name="dcl.sync.enqueue_downloads", queue=IO_LIGHT)
def enqueue_downloads(limit: int = DOWNLOAD_BATCH) -> int:
    with Session(_engine()) as session:
        ids = pending_downloads(session, limit)
    for location_id in ids:
        download.apply_async(args=[str(location_id)], queue=IO_LIGHT)
    return len(ids)


@app.task(name="dcl.sync.token_health", queue=IO_LIGHT)
def token_health() -> bool:
    settings = get_settings()
    with Session(_engine(), expire_on_commit=False) as session, GraphClient(_tokens().access_token) as graph:
        return check_token_health(session, graph, settings.drive_id, settings.folder_ids[0])
