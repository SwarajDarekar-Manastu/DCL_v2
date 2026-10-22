"""The ``llm_calls`` writer: pass ``db_ledger(engine)`` as ``GeminiClient(ledger=...)``. Owner: S1.

Each call is one row in its own short transaction, so a caller's rollback never loses the cost of calls
that were made. A doc id that is not a UUID is kept out of ``doc_id`` (the anchor still says where).
"""

import uuid
from collections.abc import Callable

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from backend.llm_engine.gemini_types import LlmCallRecord
from backend.postgres.models import LlmCall


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def row(record: LlmCallRecord) -> LlmCall:
    return LlmCall(
        at=record.at,
        model=record.model,
        purpose=record.purpose,
        prompt_version=record.prompt_version,
        doc_id=_uuid(record.doc_id),
        node_anchor=record.node_anchor,
        trace_id=record.trace_id,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cached_tokens=record.cached_tokens,
        latency_ms=record.latency_ms,
        cost_estimate=record.cost_estimate,
        status=record.status,
        error=record.error,
        request_id=record.request_id,
    )


def db_ledger(engine: Engine) -> Callable[[LlmCallRecord], None]:
    def write(record: LlmCallRecord) -> None:
        with Session(engine) as session:
            session.add(row(record))
            session.commit()

    return write
