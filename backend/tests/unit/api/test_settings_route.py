"""Settings router: admin only, request validation before any database work."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import auth, settings
from backend.postgres.session import get_session

REVIEWERS, ADMINS = "group-reviewers", "group-admins"


@pytest.fixture
def client(auth_config, key_resolver):
    app = FastAPI()
    app.include_router(settings.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    app.dependency_overrides[get_session] = lambda: object()
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/settings", None),
        ("get", "/settings/flags.strict_mode/history", None),
        ("post", "/settings/preview", {"changes": [{"key": "flags.strict_mode", "value": True}]}),
        ("put", "/settings", {"changes": [{"key": "flags.strict_mode", "value": True}]}),
        ("post", "/settings/rollback", {"versions": {"flags.strict_mode": 1}}),
    ],
)
def test_admins_only(client, token, method, path, body):
    kwargs = {"json": body} if body else {}
    assert client.request(method, path, **kwargs).status_code == 401
    reviewer = {"Authorization": f"Bearer {token(groups=[REVIEWERS])}"}
    assert client.request(method, path, headers=reviewer, **kwargs).status_code == 403


def test_empty_batches_are_422(client, token):
    admin = {"Authorization": f"Bearer {token(groups=[ADMINS])}"}
    assert client.put("/settings", json={"changes": []}, headers=admin).status_code == 422
    assert client.post("/settings/rollback", json={"versions": {}}, headers=admin).status_code == 422
    assert client.post("/settings/rollback", json={"versions": {"a.b": 0}}, headers=admin).status_code == 422
