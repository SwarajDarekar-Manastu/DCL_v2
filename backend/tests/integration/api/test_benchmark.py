"""backend/benchmark/catalog.py on real benchmark tables. Needs DCL_TEST_DATABASE_URL (an empty ParadeDB)."""

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.benchmark.catalog import (
    CaseContent,
    CaseCreate,
    DraftFromChat,
    Problem,
    RunRequest,
    SuiteImport,
    add_version,
    cancel_run,
    case_history,
    compare_runs,
    create_case,
    draft_from_chat,
    export_suite,
    import_suite,
    list_cases,
    list_suites,
    run_results,
    set_status,
    start_run,
)
from backend.postgres.models import AuditEvent, BenchmarkResult, BenchmarkRun
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
DOC = uuid.UUID("6f1c2a3e-0000-4000-8000-000000000001")


@pytest.fixture
def session():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    url = normalize_url(url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        config = Config(str(ALEMBIC_INI))
        command.upgrade(config, "head")
        engine = create_engine(url)
        with Session(engine) as s:
            yield s
        engine.dispose()
        command.downgrade(config, "base")


def case(case_id, suite="telemetry", category="TELEMETRY_MATH", status="active", question=None):
    return CaseCreate(
        case_id=case_id,
        suite=suite,
        category=category,
        status=status,
        question=question or f"Peak pressure of {case_id}?",
        spec={
            "expected_numeric": [
                {"metric": "peak_pressure", "value": 12.4, "unit": "bar", "tolerance_pct": 1}
            ],
            "expected_tools": {"tools": ["query_telemetry"]},
            "retrieval_gold_anchors": [{"doc_id": str(DOC), "anchor": "page:8:3f2a9c1b7d4e5f60"}],
        },
    )


def audit_actions(session, case_id):
    stmt = select(AuditEvent.action).where(AuditEvent.entity_id == case_id).order_by(AuditEvent.event_id)
    return list(session.scalars(stmt))


def test_versions_are_immutable_and_audited(session):
    create_case(session, case("tp07-t04-peak"), "asha@x")
    edited = CaseContent(
        **case("tp07-t04-peak").model_dump(exclude={"case_id", "status"}) | {"question": "Edited?"}
    )
    v2 = add_version(session, "tp07-t04-peak", edited, "ravi@x")
    history = case_history(session, "tp07-t04-peak")
    assert [(c.version, c.question) for c in history] == [
        (2, "Edited?"),
        (1, "Peak pressure of tp07-t04-peak?"),
    ]
    assert v2.status == "active" and v2.created_by == "ravi@x"
    set_status(session, "tp07-t04-peak", "retired", "asha@x", None)
    assert [c.status for c in case_history(session, "tp07-t04-peak")] == ["retired", "active"]
    assert audit_actions(session, "tp07-t04-peak") == ["create", "new_version", "retired"]
    with pytest.raises(Problem) as exists:
        create_case(session, case("tp07-t04-peak"), "asha@x")
    assert exists.value.status_code == 409


def test_draft_from_chat_needs_approval(session):
    trace = uuid.uuid4()
    body = DraftFromChat(
        category="FACT_LOOKUP", question="Preheat power of the heater?", source_trace_id=trace
    )
    draft = draft_from_chat(session, body, "asha@manastuspace.com")
    assert draft.status == "draft" and draft.suite == "from-chat" and draft.source_trace_id == trace
    assert draft.case_id.startswith("chat-")
    approved = set_status(session, draft.case_id, "active", "ravi@x", "draft")
    assert approved.status == "active"
    with pytest.raises(Problem) as twice:
        set_status(session, draft.case_id, "active", "ravi@x", "draft")
    assert twice.value.status_code == 409
    assert audit_actions(session, draft.case_id) == ["draft_from_chat", "approve"]


def test_run_snapshots_the_active_latest_versions(session):
    create_case(session, case("a"), "x")
    create_case(session, case("b"), "x")
    create_case(session, case("c", status="draft"), "x")
    add_version(session, "b", CaseContent(**case("b").model_dump(exclude={"case_id", "status"})), "x")
    run = start_run(session, RunRequest(suite="telemetry", git_commit="abc123"), "asha@x")
    assert run.status == "queued" and run.case_versions == {"a": 1, "b": 2} and run.git_commit == "abc123"
    subset = start_run(session, RunRequest(suite="telemetry", case_ids=["b"]), "asha@x")
    assert subset.case_versions == {"b": 2}
    with pytest.raises(Problem) as inactive:
        start_run(session, RunRequest(suite="telemetry", case_ids=["c"]), "asha@x")
    assert inactive.value.status_code == 422
    assert cancel_run(session, run.run_id).status == "cancelled"
    with pytest.raises(Problem):
        cancel_run(session, run.run_id)


def test_compare_finds_newly_failing_and_passing(session):
    for cid in ("a", "b", "c"):
        create_case(session, case(cid), "x")
    base = BenchmarkRun(
        suite="telemetry",
        status="completed",
        case_versions={"a": 1, "b": 1, "c": 1},
        model_config={"reranker": "bge-reranker-v2-m3"},
        aggregate={"pass_rate": 1.0, "recall_at_8": 0.9},
        started_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    head = BenchmarkRun(
        suite="telemetry",
        status="completed",
        case_versions={"a": 1, "b": 1, "c": 1},
        model_config={"reranker": None},
        aggregate={"pass_rate": 0.333, "recall_at_8": 0.6},
        started_at=datetime(2026, 10, 21, tzinfo=UTC),
    )
    session.add_all([base, head])
    session.flush()
    rows = [
        (base, "a", True, None),
        (base, "b", True, None),
        (base, "c", False, "SYNTHESIS_ERROR"),
        (head, "a", True, None),
        (head, "b", False, "RERANK_MISS"),
        (head, "c", False, "SYNTHESIS_ERROR"),
    ]
    session.add_all(
        BenchmarkResult(run_id=r.run_id, case_id=c, case_version=1, passed=p, failure_class=f, metrics={})
        for r, c, p, f in rows
    )
    session.flush()

    comparison = compare_runs(session, base.run_id, head.run_id)
    assert [(d.case_id, d.head_failure_class) for d in comparison.newly_failing] == [("b", "RERANK_MISS")]
    assert [d.case_id for d in comparison.still_failing] == ["c"]
    assert comparison.newly_passing == []
    assert comparison.aggregate_delta == {"pass_rate": -0.667, "recall_at_8": -0.3}
    assert comparison.config_diff == {"model_config.reranker": {"base": "bge-reranker-v2-m3", "head": None}}
    assert (comparison.not_scored, comparison.only_in_base, comparison.only_in_head) == ([], [], [])
    assert run_results(session, head.run_id).results[1].failure_class == "RERANK_MISS"
    summary = next(s for s in list_suites(session) if s.suite == "telemetry")
    assert summary.cases_by_status == {"active": 3}
    assert summary.last_run.run_id == head.run_id and summary.last_run.pass_rate == pytest.approx(
        1 / 3, abs=1e-4
    )


def test_export_import_round_trip(session):
    create_case(session, case("a"), "x")
    create_case(session, case("b", status="draft"), "x")
    exported = export_suite(session, "telemetry")
    assert [c.case_id for c in exported.cases] == ["a", "b"]

    changed = [
        c if c.case_id == "a" else c.model_copy(update={"question": "Changed?"}) for c in exported.cases
    ]
    counts = import_suite(session, "telemetry", SuiteImport(cases=[*changed, case("new")]), "asha@x")
    assert (counts.created, counts.versioned, counts.unchanged) == (1, 1, 1)
    assert [c.version for c in list_cases(session, suite="telemetry").items] == [1, 2, 1]
    with pytest.raises(Problem):
        import_suite(session, "other", SuiteImport(cases=[case("a")]), "x")


def test_compare_counts_only_cases_scored_in_both_runs(session):
    for cid in ("a", "b", "c", "d", "e"):
        create_case(session, case(cid), "x")
    base = BenchmarkRun(
        suite="telemetry", status="completed", case_versions={"a": 1, "b": 1, "c": 1, "d": 1}, aggregate={}
    )
    head = BenchmarkRun(
        suite="telemetry", status="completed", case_versions={"a": 1, "b": 1, "c": 1, "e": 1}, aggregate={}
    )
    session.add_all([base, head])
    session.flush()
    error = {"error": "WorkflowTimeoutError: Operation timed out after 300.0 seconds"}
    rows = [
        (base, "a", True, None, {}),
        (base, "b", False, None, error),  # the runner could not score it
        (base, "c", True, None, {}),
        (base, "d", True, None, {}),
        (head, "a", False, "RETRIEVAL_MISS", {}),
        (head, "b", False, "SYNTHESIS_ERROR", {}),
        (head, "c", False, None, error),
        (head, "e", False, "TOOL_MISROUTE", {}),  # new in head: not a regression
    ]
    session.add_all(
        BenchmarkResult(run_id=r.run_id, case_id=c, case_version=1, passed=p, failure_class=f, metrics=m)
        for r, c, p, f, m in rows
    )
    session.flush()

    comparison = compare_runs(session, base.run_id, head.run_id)
    assert [d.case_id for d in comparison.newly_failing] == ["a"]
    assert [d.case_id for d in comparison.not_scored] == ["b", "c"]
    assert comparison.still_failing == [] and comparison.newly_passing == []
    assert (comparison.only_in_base, comparison.only_in_head) == (["d"], ["e"])
