import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import audit, auth
from backend.api.audit import AuditFilters, AuditPage
from backend.postgres.session import get_session

REVIEWERS = "group-reviewers"


@pytest.fixture
def seen(monkeypatch):
    calls: list[AuditFilters] = []

    def fake_query(session, filters):
        calls.append(filters)
        return AuditPage(items=[], next_cursor=None)

    monkeypatch.setattr(audit, "query_audit", fake_query)
    return calls


@pytest.fixture
def client(auth_config, key_resolver, seen):
    app = FastAPI()
    app.include_router(audit.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    app.dependency_overrides[get_session] = lambda: object()
    return TestClient(app)


def test_reviewers_only(client, token):
    assert client.get("/audit").status_code == 401
    assert client.get("/audit", headers={"Authorization": f"Bearer {token()}"}).status_code == 403


def test_query_parameters_reach_the_query(client, token, seen):
    response = client.get(
        "/audit",
        params=[("entity_type", "case"), ("entity_id", "doc:1"), ("entity_id", "flag-1"), ("limit", "20")],
        headers={"Authorization": f"Bearer {token(groups=[REVIEWERS])}"},
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}
    assert (seen[0].entity_type, seen[0].entity_id, seen[0].limit) == ("case", ["doc:1", "flag-1"], 20)


def test_bad_parameters_are_422(client, token, seen):
    headers = {"Authorization": f"Bearer {token(groups=[REVIEWERS])}"}
    assert client.get("/audit", params={"entity_type": "nope"}, headers=headers).status_code == 422
    assert client.get("/audit", params={"cursor": "abc"}, headers=headers).status_code == 422
    assert seen == []
