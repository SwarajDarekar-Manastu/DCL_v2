"""answer_traces on real rows: the writer, Show trace by id and by chat message, Report issue with the
wrong-unit CONFLICT flag. Needs DCL_TEST_DATABASE_URL."""

import json
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend import config
from backend.api import engine as engine_api
from backend.postgres.enums import DocumentStatus
from backend.postgres.models import AnswerTrace, Document, ReviewFlag
from backend.postgres.session import normalize_url
from backend.tests.unit.llm_engine.engine.test_engine_api import SECRET, signed_headers

ALEMBIC_INI = Path(__file__).resolve().parents[4] / "postgres" / "alembic.ini"


@pytest.fixture(scope="module")
def db():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    url = normalize_url(url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        alembic = Config(str(ALEMBIC_INI))
        command.upgrade(alembic, "head")
        eng = create_engine(url)
        yield eng
        eng.dispose()
        command.downgrade(alembic, "base")


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", None)
    monkeypatch.setenv("DCL_PIPE_SHARED_SECRET", SECRET)
    config.get_settings.cache_clear()
    app = FastAPI()
    app.include_router(engine_api.router)

    def session():
        with Session(db) as s:
            yield s

    app.dependency_overrides[engine_api.db_session] = session
    yield TestClient(app)
    config.get_settings.cache_clear()


def trace(doc_id, *, user="u-17", chat="c1", message="m1") -> dict:
    return {
        "trace_id": str(uuid.uuid4()),
        "question": "Peak chamber pressure in TP7 T04?",
        "chat_id": chat,
        "message_id": message,
        "user_id": user,
        "conversation_summary": None,
        "user_language": "en",
        "model_config": {"gemini_model": "gemini-test"},
        "mode": "answered",
        "query_analysis": {"raw": {"intents": ["telemetry_metric"]}},
        "tool_calls": [{"tool": "query_telemetry", "call_id": "a", "warnings": [], "display": "12.4 barg"}],
        "retrieved": [],
        "external_queries": [],
        "claims": [{"text": "peak 12.4 barg", "kind": "numeric", "evidence_ids": ["E1"]}],
        "citations": [
            {"doc_id": str(doc_id), "anchor": "page:8:" + "a" * 64, "label": "Test Report 37, p. 8"}
        ],
        "verifier_result": {"summary": {"claims": 1, "entailed": 1}},
        "answer_markdown": "The peak was 12.4 barg [1].",
        "latency_ms": 4200,
    }


def test_the_writer_routes_and_feedback(db, client):
    with Session(db) as s:
        doc = Document(route="A1", status=DocumentStatus.ACTIVE, title="Test Report 37")
        s.add(doc)
        s.commit()
        doc_id = doc.doc_id
    mine, theirs = trace(doc_id), trace(doc_id, user="u-99", message="m9")
    with Session(db) as s:
        for t in (mine, mine, theirs):  # a DBOS replay writes the same row again
            engine_api.save_trace(s, t)
        s.commit()
        row = s.get(AnswerTrace, uuid.UUID(mine["trace_id"]))
        assert row.model_config_ == {"gemini_model": "gemini-test", "mode": "answered"}
        assert s.scalar(select(AnswerTrace).where(AnswerTrace.chat_id == "c1").limit(1)) is not None

    with Session(db) as s:
        for purpose, ms in (("engine.query_analysis", 1000), ("engine.synthesis", 3000)):
            s.execute(
                text(
                    "INSERT INTO llm_calls (model, purpose, prompt_version, trace_id, input_tokens, "
                    "output_tokens, latency_ms, status) "
                    "VALUES ('gemini-test', :p, 'x.v1', :t, 100, 20, :ms, 'ok')"
                ),
                {"p": purpose, "t": mine["trace_id"], "ms": ms},
            )
        s.commit()
    shown = client.get(f"/v1/traces/{mine['trace_id']}", headers=signed_headers(b"")).json()
    gemini = shown["gemini"]
    assert (gemini["total_ms"], gemini["share"], gemini["tokens_in"]) == (4000, round(4000 / 4200, 3), 200)
    assert [c["purpose"] for c in gemini["calls"]] == ["engine.query_analysis", "engine.synthesis"]
    assert shown["question"] == mine["question"] and shown["tool_calls"][0]["tool"] == "query_telemetry"
    by_message = client.get("/v1/traces?chat_id=c1&message_id=m1", headers=signed_headers(b"")).json()
    assert by_message["trace_id"] == mine["trace_id"]
    assert client.get(f"/v1/traces/{theirs['trace_id']}", headers=signed_headers(b"")).status_code == 404

    for report in (
        {"kind": "wrong_unit", "comment": "bar(g) not bar(a)", "citation_id": "1"},
        {"kind": "wrong_number", "comment": "should be 12.5"},
    ):
        body = json.dumps(report).encode()
        path = f"/v1/traces/{mine['trace_id']}/feedback"
        assert client.post(path, content=body, headers=signed_headers(body)).status_code == 202
    with Session(db) as s:
        feedback = s.get(AnswerTrace, uuid.UUID(mine["trace_id"])).feedback
        assert [f["kind"] for f in feedback] == ["wrong_unit", "wrong_number"]
        assert feedback[0]["user_id"] == "u-17"
        [flag] = s.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == doc_id)).all()
        assert (flag.flag_type, flag.severity, flag.anchor["page"]) == ("CONFLICT", "SOFT", 8)
        assert flag.evidence["a"]["value"] == "bar(g) not bar(a)"
