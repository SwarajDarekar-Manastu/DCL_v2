"""Benchmark runner on real rows (S3's catalog creates cases and the queued run), with a fake engine.
Needs DCL_TEST_DATABASE_URL (an empty ParadeDB 0.26.2 database)."""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.benchmark import catalog
from backend.benchmark.runner import RunnerDeps, run_benchmark
from backend.postgres.models import BenchmarkCase, BenchmarkResult, BenchmarkRun
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
DOC = "00000000-0000-4000-8000-000000000041"
TRACE = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    url = normalize_url(url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        config = Config(str(ALEMBIC_INI))
        command.upgrade(config, "head")
        eng = create_engine(url)
        yield eng
        eng.dispose()
        command.downgrade(config, "base")


CASES = [
    {
        "case_id": "tp07-mean",
        "category": "TELEMETRY_MATH",
        "question": "Mean chamber pressure in TP07 T01?",
        "spec": {
            "expected_numeric": [{"metric": "pc_mean", "value": 12.4, "unit": "barg", "tolerance_pct": 1}],
            "expected_tools": {"tools": ["query_telemetry"]},
        },
    },
    {
        "case_id": "fact-misroute",
        "category": "FACT_LOOKUP",
        "question": "Which code computes the expansion ratio?",
        "spec": {"expected_tools": {"tools": ["inspect_code_and_diagrams"]}},
    },
    {"case_id": "crash", "category": "FACT_LOOKUP", "question": "BOOM", "spec": {}},
    {
        "case_id": "not-indexed",
        "category": "FACT_LOOKUP",
        "question": "What does the TP12 report say about the load cell?",
        "spec": {"expected_citations": [{"file_name": "TP12 Test Report.pdf"}]},
    },
    {
        "case_id": "clarify-then-answer",
        "category": "TELEMETRY_MATH",
        "question": "What was the peak pressure?",
        "spec": {
            "clarification_answer": "TP07 T01, chamber",
            "expected_numeric": [{"metric": "pc_peak", "value": 49.6, "unit": "barg", "tolerance_pct": 1}],
        },
    },
    {
        "case_id": "conflict",
        "category": "CONFLICT_BEHAVIOR",
        "question": "What test plan does the sheet belong to?",
        "spec": {"expected_behavior": ["must_present_both_conflicting_values"]},
    },
]


def reply(question: str, history: str) -> tuple[dict, dict]:
    if question == "BOOM":
        raise RuntimeError("engine down")
    if question == "What was the peak pressure?":
        return {"mode": "clarification", "answer_markdown": "Which run?", "trace_id": TRACE}, None
    if question.startswith("TP07 T01, chamber"):
        assert "assistant: Which run?" in history
        text, tools = "peak 49.6 barg", ["query_telemetry"]
    elif "chamber" in question:
        text, tools = "mean 12.41 barg", ["catalog_lookup", "query_telemetry"]
    else:
        text, tools = "Sheet says TP6, folder says TP7.", ["search_documents"]
    done = {"mode": "answered", "answer_markdown": text, "trace_id": TRACE, "latency_ms": 1000}
    trace = {
        "tool_calls": [{"tool": t, "warnings": []} for t in tools],
        "citations": [
            {"doc_id": DOC, "title": "TP07_T01.dat", "anchor": "page:1:" + "a" * 64, "provenance": "measured"}
        ],
        "claims": [{"text": text, "kind": "numeric"}],
        "verifier_result": {"verdicts": [{"claim_index": 0, "verdict": "entailed"}]},
    }
    return done, trace


@pytest.fixture
def setup(engine):
    with Session(engine) as s:
        s.execute(delete(BenchmarkResult))
        s.execute(delete(BenchmarkRun))
        s.execute(delete(BenchmarkCase))
        s.commit()
        for case in CASES:
            catalog.create_case(s, catalog.CaseCreate(suite="s2", **case), "s5@test")
        run = catalog.start_run(s, catalog.RunRequest(suite="s2"), "lead@test")
        s.commit()
    events, asked, judged = [], [], []

    async def answer(question, history, external_mode):
        asked.append((question, external_mode))
        return reply(question, history)

    async def judge(expectation, question, answer_text, sources):
        judged.append(expectation)
        return {"passed": "TP6" in answer_text and "TP7" in answer_text, "rationale": "both plans stated"}

    deps = RunnerDeps(
        session_factory=sessionmaker(engine, expire_on_commit=False),
        answer=answer,
        publish=lambda run_id, event, data: events.append((run_id, event, data)),
        judge=judge,
        model_config={"gemini_model": "gemini-test"},
        concurrency=2,
    )
    return run.run_id, deps, events, asked, judged


def results(engine, run_id):
    with Session(engine) as s:
        return {
            r.case_id: r for r in s.scalars(select(BenchmarkResult).where(BenchmarkResult.run_id == run_id))
        }


def test_a_queued_run_completes_with_results_aggregate_and_events(engine, setup):
    run_id, deps, events, asked, judged = setup
    assert asyncio.run(run_benchmark(run_id, deps)) == "completed"
    rows = results(engine, run_id)
    assert set(rows) == {c["case_id"] for c in CASES}
    assert rows["tp07-mean"].passed and rows["tp07-mean"].failure_class is None
    assert rows["tp07-mean"].trace_id == uuid.UUID(TRACE) and rows["tp07-mean"].latency_ms == 1000
    assert rows["fact-misroute"].failure_class == "TOOL_MISROUTE"
    assert rows["crash"].passed is False and "engine down" in rows["crash"].metrics["error"]
    assert rows["crash"].failure_class == "TOOL_ERROR"
    assert rows["not-indexed"].failure_class == "MISSING_DOCUMENT"
    assert rows["not-indexed"].metrics["missing_documents"] == ["TP12 Test Report.pdf"]
    assert rows["clarify-then-answer"].passed  # the clarification was answered from the case
    assert rows["conflict"].passed and judged == ["must_present_both_conflicting_values"]
    assert {mode for _, mode in asked} == {"mock"}
    with Session(engine) as s:
        run = s.get(BenchmarkRun, run_id)
        assert run.status == "completed" and run.started_at and run.finished_at
        assert run.model_config == {"requested_by": "lead@test", "gemini_model": "gemini-test"}
        assert run.active_doc_count == 0
        assert run.aggregate["cases_done"] == 6 and run.aggregate["pass_rate"] == 0.5
        assert run.aggregate["failure_classes"] == {
            "TOOL_MISROUTE": 1,
            "TOOL_ERROR": 1,
            "MISSING_DOCUMENT": 1,
        }
    progress = [d for _, e, d in events if e == "progress" and "case_id" in d]
    assert len(progress) == 6 and progress[-1]["cases_done"] == 6
    assert [e for _, e, _ in events][-1] == "finished" and events[-1][2]["status"] == "completed"
    with Session(engine) as s:  # S3's view reads what the runner wrote
        assert catalog.run_results(s, run_id).results


def test_a_redelivered_run_resumes_and_a_final_run_is_left_alone(engine, setup):
    run_id, deps, events, asked, _ = setup
    with Session(engine) as s:
        s.add(BenchmarkResult(run_id=run_id, case_id="tp07-mean", case_version=1, passed=True, metrics={}))
        s.commit()
    asyncio.run(run_benchmark(run_id, deps))
    assert "Mean chamber pressure in TP07 T01?" not in [q for q, _ in asked]
    asked.clear()
    assert asyncio.run(run_benchmark(run_id, deps)) == "completed"
    assert asked == []


def test_cancel_stops_between_cases_and_drops_the_case_in_flight(engine, setup):
    run_id, deps, events, asked, _ = setup
    deps.concurrency = 1
    inner = deps.answer

    async def cancelling(question, history, mode):
        if not asked:
            with Session(engine) as s:
                catalog.cancel_run(s, run_id)
                s.commit()
        return await inner(question, history, mode)

    deps.answer = cancelling
    assert asyncio.run(run_benchmark(run_id, deps)) == "cancelled"
    assert results(engine, run_id) == {}
    assert len(asked) == 2  # the clarification and its answer of the first case, nothing after


class FakeRedis:
    def __init__(self):
        self.keys = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True

    def exists(self, key):
        return key in self.keys


def test_the_sweep_starts_a_queued_run_once_and_resumes_a_stalled_one(engine, setup, monkeypatch):
    from backend.benchmark import runner, tasks

    run_id, deps, events, asked, _ = setup
    fake, sent = FakeRedis(), []
    monkeypatch.setattr(tasks, "broker", lambda: fake)
    monkeypatch.setattr(tasks, "_deps", lambda: deps)
    monkeypatch.setattr(tasks.start, "delay", lambda rid: sent.append(("start", rid)))
    monkeypatch.setattr(tasks.case, "delay", lambda rid, cid: sent.append(("case", cid)))
    assert tasks.sweep() == {"started": 1, "resumed": 0}
    assert tasks.sweep() == {"started": 0, "resumed": 0}  # the start lock holds while the task is queued
    assert sent == [("start", str(run_id))]
    sent.clear()
    assert tasks.start.run(str(run_id)) == 6  # claim and one task per case
    assert [c for kind, c in sent if kind == "case"] == sorted(c["case_id"] for c in CASES)
    sent.clear()
    assert tasks.sweep() == {"started": 0, "resumed": 0}  # heartbeat alive
    fake.keys.pop(tasks.HEARTBEAT.format(run_id))  # the worker died
    assert tasks.sweep() == {"started": 0, "resumed": 1}
    assert len(sent) == 6
    assert tasks.case.run(str(run_id), "tp07-mean") is True
    assert tasks.case.run(str(run_id), "tp07-mean") is None  # already recorded: a duplicate does nothing
    assert runner.complete_if_done(run_id, deps) is False
