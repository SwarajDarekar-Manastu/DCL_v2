"""Benchmark tables (file 05 §4.7). Cases are authored and versioned; runs and results are derived.

``source_trace_id`` and ``trace_id`` point at ``answer_traces`` (M8); their foreign keys are added
with that table (``source_trace_id`` ON DELETE SET NULL).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import (
    BenchmarkCaseStatus,
    BenchmarkCategory,
    BenchmarkRunStatus,
    FailureClass,
    enum_check,
)

EMPTY_OBJECT = text("'{}'::jsonb")


class BenchmarkCase(Base):
    __tablename__ = "benchmark_cases"
    __table_args__ = (
        enum_check("status", BenchmarkCaseStatus),
        enum_check("category", BenchmarkCategory),
        Index(None, "suite", "status"),
        {"info": tier(Tier.AUTHORED)},
    )

    case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    suite: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=BenchmarkCaseStatus.DRAFT.value)
    category: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    difficulty: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    source_trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        enum_check("status", BenchmarkRunStatus),
        Index(None, "suite", "started_at"),
        {"info": tier(Tier.DERIVED)},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    suite: Mapped[str] = mapped_column(Text)
    case_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    git_commit: Mapped[str | None] = mapped_column(Text)
    model_config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    pipeline_version: Mapped[int | None] = mapped_column(Integer)
    active_doc_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default=BenchmarkRunStatus.QUEUED.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aggregate: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "case_version"], ["benchmark_cases.case_id", "benchmark_cases.version"]
        ),
        enum_check("failure_class", FailureClass),
        Index(None, "case_id", "case_version"),
        {"info": tier(Tier.DERIVED)},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("benchmark_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_version: Mapped[int] = mapped_column(Integer)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    failure_class: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Numeric(12, 6))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
