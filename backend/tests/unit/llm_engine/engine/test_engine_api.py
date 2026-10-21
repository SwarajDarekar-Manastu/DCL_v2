import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from backend import config
from backend.api import engine
from backend.api.engine import AnswerEvent, DoneEvent, EventType, StepEvent, sign_identity, to_sse

SECRET = "pipe-secret-for-tests-0123456789abcdef"
EXAMPLE = Path(__file__).with_name("example_answer_stream.sse")
EVENTS = TypeAdapter(AnswerEvent)


@pytest.fixture(autouse=True)
def pipe_secret(monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", None)
    monkeypatch.setenv("DCL_PIPE_SHARED_SECRET", SECRET)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(engine.router)
    return TestClient(app)


def signed_headers(body: bytes, *, secret=SECRET, timestamp=None, groups="dcl-engineers,dcl-reviewers"):
    ts = str(int(timestamp if timestamp is not None else time.time()))
    return {
        "content-type": "application/json",
        "x-dcl-user-id": "u-17",
        "x-dcl-user-email": "engineer@manastuspace.com",
        "x-dcl-user-groups": groups,
        "x-dcl-timestamp": ts,
        "x-dcl-signature": sign_identity(secret, ts, "u-17", "engineer@manastuspace.com", groups, body),
    }


BODY = json.dumps(
    {"messages": [{"role": "user", "content": "peak Pc in TP07?"}], "chat_id": "c1", "message_id": "m1"}
).encode()


def test_signed_request_passes_identity_and_reaches_the_workflow_stub(client):
    response = client.post("/v1/answer", content=BODY, headers=signed_headers(BODY))
    assert response.status_code == 501


@pytest.mark.parametrize(
    "headers",
    [
        signed_headers(BODY, secret="wrong-secret"),
        signed_headers(b"another body"),
        signed_headers(BODY, timestamp=time.time() - 3600),
        {k: v for k, v in signed_headers(BODY).items() if k != "x-dcl-signature"},
    ],
    ids=["wrong secret", "body swapped", "stale timestamp", "unsigned"],
)
def test_unsigned_or_tampered_identity_is_refused(client, headers):
    assert client.post("/v1/answer", content=BODY, headers=headers).status_code in (401, 422)


def test_traces_and_confirm_require_identity_too(client):
    trace_id = "0b6d9f0e-1111-4222-8333-444455556666"
    assert client.get(f"/v1/traces/{trace_id}").status_code == 422
    assert client.get(f"/v1/traces/{trace_id}", headers=signed_headers(b"")).status_code == 501


def test_sse_frame_is_event_line_plus_one_json_data_line():
    frame = to_sse(StepEvent(step_id="s1", name="tool", description="Running\nDuckDB", done=False, tool="t2"))
    lines = frame.split("\n")
    assert lines[0] == "event: step"
    assert lines[1].startswith("data: ") and lines[2:] == ["", ""]
    assert json.loads(lines[1][6:])["description"] == "Running\nDuckDB"


def parse_stream(text: str):
    for frame in text.strip().split("\n\n"):
        event_line, data_line = frame.split("\n")
        event_type = event_line.removeprefix("event: ")
        yield EVENTS.validate_python({"type": event_type, **json.loads(data_line.removeprefix("data: "))})


def test_example_stream_for_the_pipe_validates_and_ends_with_done():
    events = list(parse_stream(EXAMPLE.read_text()))
    assert {e.type for e in events} >= {EventType.STEP, EventType.TOKEN, EventType.CITATION, EventType.DONE}
    assert isinstance(events[-1], DoneEvent)
    assert all(to_sse(e) in EXAMPLE.read_text() for e in events)


def test_citations_carry_anchors_not_node_ids():
    citation = next(e for e in parse_stream(EXAMPLE.read_text()) if e.type == EventType.CITATION)
    assert citation.anchor.startswith("page:8:")
    assert "node_id" not in citation.model_dump()


def test_confirmation_carries_the_trace_id_the_reply_goes_to():
    events = list(parse_stream(EXAMPLE.read_text()))
    confirmation = next(e for e in events if e.type == EventType.NEEDS_CONFIRMATION)
    done = events[-1]
    assert confirmation.trace_id == done.trace_id
    assert events.index(confirmation) < events.index(done)


def test_trace_lookup_by_chat_and_message_and_feedback_are_signed_routes(client):
    query = "/v1/traces?chat_id=c1&message_id=m1"
    assert client.get(query).status_code == 422
    assert client.get(query, headers=signed_headers(b"")).status_code == 501
    body = json.dumps({"kind": "wrong_unit", "comment": "bar(g) not bar(a)", "citation_id": "1"}).encode()
    path = "/v1/traces/0b6d9f0e-1111-4222-8333-444455556666/feedback"
    assert client.post(path, content=body, headers=signed_headers(body)).status_code == 501
    bad = json.dumps({"kind": "rude"}).encode()
    assert client.post(path, content=bad, headers=signed_headers(bad)).status_code == 422


def test_retrieval_lab_needs_a_console_user_and_returns_the_search_result(monkeypatch):
    from backend.api import auth
    from backend.indexing.retrieval import SearchResult

    app = FastAPI()
    app.include_router(engine.router)
    seen = {}

    def fake_search(session, query, **kw):
        seen.update(query=query, k=kw["k"], rerank=kw["rerank"])
        return SearchResult(hits=[], dense_path="exact", leg_counts={"dense": 0, "lexical": 0, "parents": 0})

    monkeypatch.setattr(engine, "search", fake_search)
    app.dependency_overrides[engine.db_session] = lambda: None
    app.dependency_overrides[engine.models_client] = lambda: None
    client = TestClient(app)
    refused = client.post("/v1/retrieval/search", json={"query": "TP37 Pc"})
    assert refused.status_code in (401, 403, 503)  # 503: Console auth not configured in this environment
    assert seen == {}

    app.dependency_overrides[auth.current_user] = lambda: auth.ConsoleUser(
        oid="o", name="n", email="e@manastuspace.com", roles=[auth.ConsoleRole.VIEWER]
    )
    response = client.post("/v1/retrieval/search", json={"query": "TP37 Pc", "k": 10, "rerank": False})
    assert response.status_code == 200
    assert response.json()["dense_path"] == "exact"
    assert seen == {"query": "TP37 Pc", "k": 10, "rerank": None}
