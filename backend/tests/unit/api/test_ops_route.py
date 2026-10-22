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
