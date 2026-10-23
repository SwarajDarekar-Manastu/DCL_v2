"""Answer traces (file 05 ``answer_traces``): one row per Answer Engine answer. Derived tier; 365-day
retention unless ``pinned`` (referenced by benchmark cases). Written by S2's ``EngineDeps.save_trace``."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier


class AnswerTrace(Base):
    __tablename__ = "answer_traces"
    __table_args__ = (Index(None, "created_at"), Index(None, "user_id"), {"info": tier(Tier.DERIVED)})

    trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    chat_id: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    conversation_summary: Mapped[str | None] = mapped_column(Text)
    user_language: Mapped[str | None] = mapped_column(Text)
    query_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tool_calls: Mapped[list[Any] | None] = mapped_column(JSONB)
    retrieved: Mapped[list[Any] | None] = mapped_column(JSONB)
    external_queries: Mapped[list[Any] | None] = mapped_column(JSONB)
    claims: Mapped[list[Any] | None] = mapped_column(JSONB)
    citations: Mapped[list[Any] | None] = mapped_column(JSONB)
    verifier_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_config_: Mapped[dict[str, Any] | None] = mapped_column("model_config", JSONB)
    answer_markdown: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pinned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
