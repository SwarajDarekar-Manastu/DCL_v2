"""query_audit over real audit_events rows. Needs DCL_TEST_DATABASE_URL (an empty ParadeDB database)."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.api.audit import AuditFilters, query_audit
from backend.postgres.models import AuditEvent
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
CASE = "0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90:1"


@pytest.fixture(scope="module")
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
            events = [
                ("asha@x", "case", CASE, "assign", T0),
                ("asha@x", "flag", "flag-1", "resolve", T0 + timedelta(minutes=5)),
                ("asha@x", "rule", "rule-1", "create", T0 + timedelta(minutes=5)),
                ("ravi@x", "case", CASE, "undo", T0 + timedelta(hours=1)),
                ("ravi@x", "config", "translation.mode", "update", T0 + timedelta(days=1)),
            ]
            s.add_all(
                AuditEvent(
                    actor=a, entity_type=t, entity_id=i, action=act, at=at, before=None, after={"n": n}
                )
                for n, (a, t, i, act, at) in enumerate(events)
            )
            s.commit()
            yield s
        engine.dispose()
        command.downgrade(config, "base")


def actions(page):
    return [item.action for item in page.items]


def test_newest_first_and_filters(session):
    assert actions(query_audit(session, AuditFilters())) == ["update", "undo", "create", "resolve", "assign"]
    assert actions(query_audit(session, AuditFilters(actor="ravi@x"))) == ["update", "undo"]
    assert actions(query_audit(session, AuditFilters(entity_type="rule"))) == ["create"]
    window = AuditFilters(since=T0 + timedelta(minutes=1), until=T0 + timedelta(days=1))
    assert actions(query_audit(session, window)) == ["undo", "create", "resolve"]


def test_case_history_includes_its_flags(session):
    history = query_audit(session, AuditFilters(entity_id=[CASE, "flag-1"]))
    assert actions(history) == ["undo", "resolve", "assign"]
    assert history.items[0].after == {"n": 3}


def test_cursor_pages_without_gaps_or_repeats(session):
    first = query_audit(session, AuditFilters(limit=2))
    second = query_audit(session, AuditFilters(limit=2, cursor=first.next_cursor))
    third = query_audit(session, AuditFilters(limit=2, cursor=second.next_cursor))
    assert actions(first) + actions(second) + actions(third) == [
        "update",
        "undo",
        "create",
        "resolve",
        "assign",
    ]
    assert third.next_cursor is None
