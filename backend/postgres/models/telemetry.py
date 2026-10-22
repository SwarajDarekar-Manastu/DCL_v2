"""Telemetry catalog (file 05 §4.4): one ``telemetry_runs`` row per run, one ``telemetry_channels`` row per
canonical channel. Parquet files live in ``dcl-telemetry/{run_uuid}/``; DuckDB reads ``normalized.parquet``
with column names taken from ``telemetry_channels`` only.

A HALTED document has no rows here (file 06 §2): the commit path writes them once the gate passes.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import (
    AmbientCondition,
    GaugeOrAbs,
    Quantity,
    RunStatus,
    TelemetrySourceFormat,
    enum_check,
)

EMPTY_OBJECT = text("'{}'::jsonb")
EMPTY_ARRAY = text("'[]'::jsonb")


class TelemetryRun(Base):
    """One run. Test ids are read from the document (``doc_id``), not duplicated here."""

    __tablename__ = "telemetry_runs"
    __table_args__ = (
        enum_check("source_format", TelemetrySourceFormat),
        enum_check("run_status", RunStatus),
        enum_check("ambient_condition", AmbientCondition),
        {"info": tier(Tier.REGISTRY)},
    )

    run_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_label: Mapped[str] = mapped_column(Text, unique=True)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE"), index=True
    )
    blob_sha256: Mapped[str] = mapped_column(CHAR(64), ForeignKey("blobs.sha256"), index=True)
    source_format: Mapped[str] = mapped_column(Text)
    run_status: Mapped[str] = mapped_column(Text, server_default=RunStatus.UNKNOWN.value)
    ambient_condition: Mapped[str] = mapped_column(Text, server_default=AmbientCondition.UNKNOWN.value)
    ambient_pressure_bar_abs: Mapped[float | None] = mapped_column(Float)
    sampling_rate_hz_nominal: Mapped[float | None] = mapped_column(Float)
    sampling_rate_hz_actual: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    n_rows: Mapped[int | None] = mapped_column(BigInteger)
    n_gaps: Mapped[int | None] = mapped_column(Integer)
    n_duplicate_ts: Mapped[int | None] = mapped_column(Integer)
    t0_ignition_ms: Mapped[int | None] = mapped_column(BigInteger)
    t0_method: Mapped[str | None] = mapped_column(Text)
    t0_confidence: Mapped[float | None] = mapped_column(Float)
    sub_runs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=EMPTY_ARRAY)
    raw_parquet_uri: Mapped[str | None] = mapped_column(Text)
    normalized_parquet_uri: Mapped[str | None] = mapped_column(Text)
    schema_uri: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel_map_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.rule_id"), index=True
    )
    clock_offsets: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class TelemetryChannel(Base):
    """One canonical channel of a run, with the three-tier metrics (file 03 §C.1)."""

    __tablename__ = "telemetry_channels"
    __table_args__ = (
        enum_check("quantity", Quantity),
        enum_check("gauge_or_abs", GaugeOrAbs),
        {"info": tier(Tier.DERIVED)},
    )

    run_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telemetry_runs.run_uuid", ondelete="CASCADE"), primary_key=True
    )
    canonical_name: Mapped[str] = mapped_column(Text, primary_key=True)
    raw_name: Mapped[str] = mapped_column(Text)
    raw_unit: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[str | None] = mapped_column(Text)
    unit_si: Mapped[str | None] = mapped_column(Text)
    gauge_or_abs: Mapped[str] = mapped_column(Text, server_default=GaugeOrAbs.NOT_APPLICABLE.value)
    conversion: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    sensor_tag: Mapped[str | None] = mapped_column(Text)
    range_min: Mapped[float | None] = mapped_column(Float)
    range_max: Mapped[float | None] = mapped_column(Float)
    stat_min: Mapped[float | None] = mapped_column(Float)
    stat_max: Mapped[float | None] = mapped_column(Float)
    stat_mean: Mapped[float | None] = mapped_column(Float)
    stat_p50: Mapped[float | None] = mapped_column(Float)
    stat_p99: Mapped[float | None] = mapped_column(Float)
    stat_std: Mapped[float | None] = mapped_column(Float)
    peak_raw: Mapped[float | None] = mapped_column(Float)
    peak_50ms: Mapped[float | None] = mapped_column(Float)
    steady_mean: Mapped[float | None] = mapped_column(Float)
    steady_window_ms: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    saturated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    null_fraction: Mapped[float | None] = mapped_column(Float)
    sparkline_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.asset_id", ondelete="SET NULL"), index=True
    )
