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
