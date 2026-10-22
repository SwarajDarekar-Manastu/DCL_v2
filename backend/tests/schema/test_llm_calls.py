"""llm_calls (migration 0011) and the ledger hook the gateway client calls once per Gemini call."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.llm_engine.gemini_types import LlmCallRecord
from backend.postgres.ledger import db_ledger, row
from backend.postgres.models import LlmCall

AT = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


def _record(**kw) -> LlmCallRecord:
    values = dict(
        at=AT,
        model="gemini-3.8-flash",
        purpose="triage_page",
        prompt_version="triage_page.v1",
        doc_id="1539b6b4-79f0-40c5-8e24-b340610ca3c6",
        node_anchor="page:3:abc",
        trace_id=None,
        input_tokens=1200,
        output_tokens=80,
        cached_tokens=0,
        latency_ms=850,
        cost_estimate=None,
        status="ok",
        error=None,
        request_id="r-1",
    )
    values.update(kw)
    return LlmCallRecord(**values)


def test_the_ledger_writes_one_row_per_call_in_its_own_transaction(migrated):
    ledger = db_ledger(migrated)
    ledger(_record())
    ledger(_record(doc_id="not-a-uuid", status="error", error="SAFETY", output_tokens=0))
    with Session(migrated) as s:
        rows = s.scalars(select(LlmCall).order_by(LlmCall.call_id)).all()
        assert [(str(r.doc_id), r.status, r.input_tokens, r.node_anchor) for r in rows] == [
            ("1539b6b4-79f0-40c5-8e24-b340610ca3c6", "ok", 1200, "page:3:abc"),
            ("None", "error", 1200, "page:3:abc"),
        ]
        assert rows[0].at == AT


def test_unknown_status_is_refused(migrated):
    with Session(migrated) as s:
        bad = row(_record())
        bad.status = "maybe"
        s.add(bad)
        with pytest.raises(IntegrityError, match="ck_llm_calls_status"):
            s.commit()
