import subprocess
import sys

import pytest
import redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import auth, ops

ADMINS = "group-admins"
REVIEWERS = "group-reviewers"

ENTRY = {
    "task_id": "4f1c",
    "task": "backend.celery_redis.tasks_process.process_document",
    "queue": "cpu_parse",
    "args": "('doc-1',)",
    "kwargs": "{}",
    "error": "ValueError: no unit",
    "retries": 3,
    "at": "2026-10-22T10:15:00+00:00",
}


@pytest.fixture
def reads():
    return []


@pytest.fixture
def entries():
    return [ENTRY, {**ENTRY, "task_id": "older", "queue": None, "at": "2026-10-21T08:00:00+00:00"}]


@pytest.fixture
def client(auth_config, key_resolver, reads, entries):
    def reader(limit):
        reads.append(limit)
        if isinstance(entries, Exception):
            raise entries
        return entries[:limit]

    app = FastAPI()
    app.include_router(ops.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    app.dependency_overrides[ops.get_dead_letter_reader] = lambda: reader
    return TestClient(app)


def bearer(token, groups=()):
    return {"Authorization": f"Bearer {token(groups=list(groups))}"}


def test_admins_only(client, token):
    assert client.get("/ops/failed-tasks").status_code == 401
    assert client.get("/ops/failed-tasks", headers=bearer(token)).status_code == 403
    assert client.get("/ops/failed-tasks", headers=bearer(token, [REVIEWERS])).status_code == 403
    assert client.get("/ops/failed-tasks", headers=bearer(token, [ADMINS])).status_code == 200


def test_lists_entries_newest_first_with_the_limit(client, token, reads):
    response = client.get("/ops/failed-tasks?limit=1", headers=bearer(token, [ADMINS]))
    assert response.json() == {"items": [{**ENTRY, "at": "2026-10-22T10:15:00Z"}]}
    assert reads == [1]
    client.get("/ops/failed-tasks", headers=bearer(token, [ADMINS]))
    assert reads == [1, 100]
    assert client.get("/ops/failed-tasks?limit=0", headers=bearer(token, [ADMINS])).status_code == 422
    assert client.get("/ops/failed-tasks?limit=501", headers=bearer(token, [ADMINS])).status_code == 422


@pytest.mark.parametrize("entries", [[{"task_id": "broken"}, ENTRY]])
def test_skips_malformed_entries(client, token):
    items = client.get("/ops/failed-tasks", headers=bearer(token, [ADMINS])).json()["items"]
    assert [i["task_id"] for i in items] == ["4f1c"]


@pytest.mark.parametrize("entries", [redis.ConnectionError("refused")])
def test_redis_down_is_503(client, token):
    response = client.get("/ops/failed-tasks", headers=bearer(token, [ADMINS]))
    assert response.status_code == 503
    assert response.json() == {"detail": "the failed-task list is unavailable"}


def test_importing_the_router_does_not_build_the_celery_app():
    code = "import sys, backend.api.ops; print('backend.celery_redis.app' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


# ---------------------------------------------------------------- summary


@pytest.fixture
def summary_client(auth_config, key_resolver, monkeypatch):
    from backend.postgres.session import get_session

    class FakeSession:
        rollbacks = 0

        def rollback(self):
            FakeSession.rollbacks += 1

    monkeypatch.setattr(ops, "_documents_by_status", lambda s: {"ACTIVE": 7, "HALTED": 22})
    monkeypatch.setattr(ops, "_open_flags", lambda s: {"HARD": 176, "SOFT": 84})
    monkeypatch.setattr(ops, "_last_runs", lambda s: [])

    def no_ledger(s):
        raise LookupError("llm_calls is not available yet (S1 migration 0012)")

    monkeypatch.setattr(ops, "_llm_today", no_ledger)
    app = FastAPI()
    app.include_router(ops.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    app.dependency_overrides[get_session] = lambda: FakeSession()
    app.dependency_overrides[ops.get_queue_reader] = lambda: lambda: {"io_light": 3, "cpu_parse": 0}
    return app, TestClient(app)


def test_summary_is_for_any_signed_in_user_and_reports_each_part(summary_client, token):
    _, client = summary_client
    assert client.get("/ops/summary").status_code == 401
    body = client.get("/ops/summary", headers=bearer(token)).json()
    assert body["queues"] == [{"queue": "io_light", "waiting": 3}, {"queue": "cpu_parse", "waiting": 0}]
    assert body["documents_by_status"] == {"ACTIVE": 7, "HALTED": 22}
    assert body["open_flags"] == {"HARD": 176, "SOFT": 84}
    assert body["llm_today"] is None
    assert body["notes"] == {"llm_today": "llm_calls is not available yet (S1 migration 0012)"}


def test_an_unreadable_part_is_a_note_not_a_failed_page(summary_client, token):
    app, client = summary_client

    def down():
        raise redis.ConnectionError("refused")

    app.dependency_overrides[ops.get_queue_reader] = lambda: down
    body = client.get("/ops/summary", headers=bearer(token)).json()
    assert body["queues"] is None and body["notes"]["queues"] == "unavailable (ConnectionError)"
    assert body["open_flags"] == {"HARD": 176, "SOFT": 84}
