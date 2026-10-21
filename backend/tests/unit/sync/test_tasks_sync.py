"""Sync task bodies: time-budgeted delta with resume, per-root lock, download outcomes, token health.

Needs DCL_TEST_DATABASE_URL (fixtures shared with test_delta).
"""

import uuid

import httpx
from sqlalchemy import select

from backend.celery_redis import tasks_sync
from backend.celery_redis.tasks_sync import (
    Outcome,
    check_token_health,
    download_one,
    pending_downloads,
    run_delta,
)
from backend.postgres.enums import AuthStatus, DriveItemStatus
from backend.postgres.models import DriveItem, SyncRoot
from backend.sync import downloader
from backend.sync.auth import ReauthRequired
from backend.sync.graph_client import GraphClient
from backend.tests.unit.sync.test_delta import DELTA, NEXT, FakeGraph, crawl_pages

ROOT = "APU Injector"


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)


def graph(fake) -> GraphClient:
    return GraphClient(lambda: "t", transport=httpx.MockTransport(fake))


def test_a_delta_past_its_budget_stops_after_a_committed_page_and_the_next_run_finishes(session):
    fake = FakeGraph(crawl_pages())
    ticks = iter([0.0, 100.0, 100.0, 100.0])
    outcome = run_delta(session, graph(fake), ROOT, FakeRedis(), budget_s=10, clock=lambda: next(ticks))
    assert outcome == Outcome.CONTINUED
    assert session.get(SyncRoot, ROOT).next_link_checkpoint == NEXT
    assert run_delta(session, graph(fake), ROOT, FakeRedis()) == Outcome.DONE
    root = session.get(SyncRoot, ROOT)
    assert (root.delta_link, root.next_link_checkpoint) == (DELTA, None)
    assert fake.calls.count(NEXT) == 1


def test_a_root_that_is_already_running_is_skipped(session):
    lock = FakeRedis()
    lock.set(f"sync:lock:{ROOT}", "other-run", nx=True)
    assert run_delta(session, graph(FakeGraph(crawl_pages())), ROOT, lock) == Outcome.LOCKED
    assert lock.get(f"sync:lock:{ROOT}") == "other-run"


def test_the_lock_is_released_after_a_run(session):
    lock = FakeRedis()
    run_delta(session, graph(FakeGraph(crawl_pages())), ROOT, lock)
    assert lock.data == {}


def test_a_410_that_persists_during_the_resync_marks_the_root_resyncing(session):
    run_delta(session, graph(FakeGraph(crawl_pages())), ROOT, FakeRedis())
    expired = FakeGraph({DELTA: [(410, {"error": {"code": "resyncRequired"}}, {"Location": DELTA})]})
    assert run_delta(session, graph(expired), ROOT, FakeRedis()) == Outcome.RESYNC_REQUIRED
    assert session.get(SyncRoot, ROOT).status == "RESYNCING"


def _pending_id(session) -> uuid.UUID:
    run_delta(session, graph(FakeGraph(crawl_pages())), ROOT, FakeRedis())
    return session.scalars(select(DriveItem.location_id).where(DriveItem.item_id == "i-dat")).one()


def test_download_outcomes_skip_retry_and_fail(session, monkeypatch):
    location_id = _pending_id(session)
    assert location_id in pending_downloads(session)

    def mismatch(*args, **kwargs):
        raise downloader.DownloadMismatch("size 10 != Graph size 100")

    monkeypatch.setattr(tasks_sync, "land_item", mismatch)
    assert download_one(session, None, None, None, location_id, attempt=0) == Outcome.RETRY
    assert download_one(session, None, None, None, location_id, attempt=2) == Outcome.FAILED
    item = session.get(DriveItem, location_id)
    assert (item.status, item.error_last) == (DriveItemStatus.DOWNLOAD_FAILED, "size 10 != Graph size 100")
    assert download_one(session, None, None, None, location_id, attempt=0) == Outcome.SKIPPED


def test_download_lands_a_pending_item(session, monkeypatch):
    location_id = _pending_id(session)
    landed = []
    monkeypatch.setattr(tasks_sync, "land_item", lambda s, g, m, loc, http: landed.append(loc))
    monkeypatch.setattr(tasks_sync, "inspect_item", lambda s, m, loc: None)
    assert download_one(session, None, None, None, location_id, attempt=0) == Outcome.LANDED
    assert landed == [location_id]


def test_token_health_sets_auth_status_on_every_root(session):
    session.add(SyncRoot(root_name="APU", remote_drive_id="D", remote_item_id="R2"))
    session.commit()
    ok = GraphClient(
        lambda: "t", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "ROOT"}))
    )
    assert check_token_health(session, ok, "D", "ROOT") is True
    assert {r.auth_status for r in session.scalars(select(SyncRoot))} == {AuthStatus.OK}

    def no_token():
        raise ReauthRequired("refresh token revoked")

    assert check_token_health(session, GraphClient(no_token), "D", "ROOT") is False
    assert {r.auth_status for r in session.scalars(select(SyncRoot))} == {AuthStatus.REAUTH_REQUIRED}


def test_tasks_are_registered_on_io_light():
    names = {
        "dcl.sync.delta_root",
        "dcl.sync.delta_all",
        "dcl.sync.download",
        "dcl.sync.enqueue_downloads",
        "dcl.sync.token_health",
    }
    for name in names:
        assert tasks_sync.app.tasks[name].queue == "io_light"
