"""backend/api/ops.py summary queries on the real schema. Needs DCL_TEST_DATABASE_URL (an empty ParadeDB)."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.api import ops
from backend.postgres.models import BenchmarkRun, LlmCall
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"


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


def test_summary_queries_run_on_the_real_schema(session):
    def run(suite, day, pass_rate):
        return BenchmarkRun(
            suite=suite,
            status="completed",
            case_versions={"a": 1},
            aggregate={"pass_rate": pass_rate, "cases_done": 1, "cases_total": 1},
            started_at=datetime(2026, 10, day, tzinfo=UTC),
        )

    session.add_all([run("telemetry", 20, 0.5), run("telemetry", 22, 0.75), run("code", 21, 0.0)])
    session.flush()
    assert ops._documents_by_status(session) == {}
    assert ops._open_flags(session) == {"HARD": 0, "SOFT": 0}
    assert [(r.suite, r.pass_rate) for r in ops._last_runs(session)] == [("code", 0.0), ("telemetry", 0.75)]


def test_model_calls_today_sum_only_today(session):
    now = datetime.now(UTC)

    def call(at, tokens_in, tokens_out, cached, cost):
        return LlmCall(
            at=at,
            model="gemini-3.8-flash",
            purpose="synthesis",
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cached_tokens=cached,
            cost_estimate=cost,
            status="ok",
        )

    session.add_all(
        [
            call(now, 1000, 200, 50, 0.01),
            call(now, 500, 100, 0, None),
            call(now - timedelta(days=2), 9, 9, 9, 9.0),
        ]
    )
    session.flush()
    today = ops._llm_today(session)
    assert (today.calls, today.input_tokens, today.output_tokens, today.cached_tokens) == (2, 1500, 300, 50)
    assert today.cost_estimate == 0.01


def test_usage_sums_recorded_costs_counts_billed_failures_and_names_unpriced_calls(session):
    now = datetime.now(UTC)

    def call(model, status, tokens_in=0, tokens_out=0, cost=None, purpose="vision.triage_page", at=now):
        return LlmCall(
            at=at, model=model, purpose=purpose, input_tokens=tokens_in, output_tokens=tokens_out,
            cost_estimate=cost, status=status,
        )  # fmt: skip

    session.add_all(
        [
            call("gemini-3.1-flash-lite", "ok", 1000, 100, cost=0.10),
            call("gemini-3.1-flash-lite", "error", 500, 65_520, cost=0.02),  # reply failed the schema: billed
            call("gemini-3.1-flash-lite", "cache_hit"),
            call("gemini-3.1-flash-lite", "error"),  # gateway unreachable: no tokens, not billed
            call("gemini-3.8-flash", "ok", 10_000, 2_000, purpose="engine.synthesis"),  # no price yet
            call("gemini-3.1-flash-lite", "ok", 9, 9, cost=5.0, at=now - timedelta(days=30)),  # outside
        ]
    )
    session.flush()
    usage = ops.llm_usage(session, days=7)
    totals = {t.model: t for t in usage.by_model}
    lite = totals["gemini-3.1-flash-lite"]
    assert (lite.calls, lite.billed_calls, lite.cache_hits, lite.errors, lite.cost_usd) == (4, 2, 1, 2, 0.12)
    assert lite.output_tokens == 65_620
    flash = totals["gemini-3.8-flash"]
    assert (flash.cost_usd, flash.unpriced_calls) == (None, 1)
    assert usage.total_cost_usd == 0.12
