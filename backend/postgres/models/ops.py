"""Configuration and operations tables (file 05 §4.6)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, Identity, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import LlmCallStatus, enum_check


class PipelineConfig(Base):
    """Append-only, versioned non-secret configuration; ``v_config_current`` is the latest version per key.

    Rollback inserts the old value as a new version. Secrets and endpoints never go here.
    """

    __tablename__ = "pipeline_config"
    __table_args__ = ({"info": tier(Tier.AUTHORED)},)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    description: Mapped[str | None] = mapped_column(Text)


class LlmCall(Base):
    """One Gemini call (file 05 ``llm_calls``): the cost and budget ledger. No FKs: it outlives documents.
    Written by ``backend.postgres.ledger.db_ledger`` (the gateway client's ``ledger`` hook)."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        enum_check("status", LlmCallStatus),
        Index(None, "at"),
        Index(None, "doc_id"),
        {"info": tier(Tier.DERIVED)},
    )

    call_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    model: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    doc_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    node_anchor: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cached_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
