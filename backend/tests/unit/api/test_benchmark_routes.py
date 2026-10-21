import json
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.api import auth, benchmark, engine
from backend.benchmark.catalog import CaseSpec, Problem
from backend.postgres.session import get_session

REVIEWERS = "group-reviewers"
TRACE = "0b6d9f0e-1111-4222-8333-444455556666"


class FakeSession:
    def __init__(self):
        self.commits = self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def db():
    return FakeSession()


@pytest.fixture
def client(auth_config, key_resolver, db, monkeypatch):
    settings = SimpleNamespace(pipe_shared_secret=SecretStr("s3cret"))
    settings.require = lambda *groups: settings
    monkeypatch.setattr(engine, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(benchmark.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def bearer(token, groups=()):
    return {"Authorization": f"Bearer {token(groups=list(groups))}"}


CASE = {
    "case_id": "tp07-t04-peak",
    "suite": "telemetry",
    "category": "TELEMETRY_MATH",
    "question": "Peak pressure of TP07 T04?",
    "spec": {
        "retrieval_gold_anchors": [{"doc_id": "6f1c2a3e-0000-4000-8000-000000000001", "anchor": "page:8:"}]
    },
}


def test_reading_needs_sign_in_and_writing_needs_reviewer(client, token, monkeypatch):
    monkeypatch.setattr(benchmark, "list_suites", lambda session: [])
    assert client.get("/benchmark/suites").status_code == 401
    assert client.get("/benchmark/suites", headers=bearer(token)).status_code == 200
    assert client.post("/benchmark/cases", json=CASE, headers=bearer(token)).status_code == 403
    assert (
        client.post("/benchmark/runs", json={"suite": "telemetry"}, headers=bearer(token)).status_code == 403
    )


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"case_id": "bad id/with slash"}, "case_id"),
        ({"category": "GUESSING"}, "category"),
        (
            {
                "spec": {
                    "retrieval_gold_anchors": [
                        {"doc_id": "6f1c2a3e-0000-4000-8000-000000000001", "anchor": "node:5f0c9e2a:"}
                    ]
                }
            },
            "unknown anchor kind",
        ),
        ({"spec": {"expected_citations": [{"page": 3}]}}, "file_name, doc_id or standard_id"),
        ({"spec": {"unknown_field": 1}}, "unknown_field"),
    ],
)
def test_malformed_cases_are_422(client, token, patch, message):
    response = client.post("/benchmark/cases", json=CASE | patch, headers=bearer(token, [REVIEWERS]))
    assert response.status_code == 422
    assert message in json.dumps(response.json())


def test_create_commits_and_problems_roll_back(client, token, db, monkeypatch):
    created = {}

    def create(session, body, actor):
        created["actor"] = actor
        raise Problem(409, "case tp07-t04-peak exists; add a version instead")

    monkeypatch.setattr(benchmark, "create_case", create)
    response = client.post("/benchmark/cases", json=CASE, headers=bearer(token, [REVIEWERS]))
    assert response.status_code == 409 and response.json()["detail"].startswith("case tp07-t04-peak exists")
    assert (db.commits, db.rollbacks, created["actor"]) == (0, 1, "engineer@manastuspace.com")


def signed(body: bytes) -> dict:
    ts = str(int(time.time()))
    user, email = "owui-1", "asha@manastuspace.com"
    return {
        "X-DCL-User-Id": user,
        "X-DCL-User-Email": email,
        "X-DCL-User-Groups": "",
        "X-DCL-Timestamp": ts,
        "X-DCL-Signature": engine.sign_identity("s3cret", ts, user, email, "", body),
        "Content-Type": "application/json",
    }


def test_drafts_come_only_from_the_signed_pipe(client, token, db, monkeypatch):
    seen = {}

    def draft(session, body, actor):
        seen.update(actor=actor, trace=str(body.source_trace_id), suite=body.suite)
        return {
            "case_id": "chat-1",
            "version": 1,
            "suite": body.suite,
            "status": "draft",
            "category": body.category,
            "question": body.question,
            "spec": CaseSpec().model_dump(),
            "difficulty": None,
            "notes": None,
            "source_trace_id": body.source_trace_id,
            "created_by": actor,
            "created_at": "2026-10-22T09:00:00Z",
        }

    monkeypatch.setattr(benchmark, "draft_from_chat", draft)
    body = json.dumps(
        {"category": "FACT_LOOKUP", "question": "Preheat power?", "source_trace_id": TRACE}
    ).encode()
    assert (
        client.post("/benchmark/drafts", content=body, headers=bearer(token, [REVIEWERS])).status_code == 422
    )
    response = client.post("/benchmark/drafts", content=body, headers=signed(body))
    assert response.status_code == 201 and response.json()["status"] == "draft"
    assert seen == {"actor": "asha@manastuspace.com", "trace": TRACE, "suite": "from-chat"}
    assert db.commits == 1


def test_run_detail_404(client, token, monkeypatch):
    def missing(session, run_id):
        raise Problem(404, f"no run {run_id}")

    monkeypatch.setattr(benchmark, "run_results", missing)
    run_id = uuid.uuid4()
    response = client.get(f"/benchmark/runs/{run_id}", headers=bearer(token))
    assert response.status_code == 404 and response.json()["detail"] == f"no run {run_id}"
