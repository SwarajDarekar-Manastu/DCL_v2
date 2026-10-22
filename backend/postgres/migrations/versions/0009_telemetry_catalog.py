# ruff: noqa: E501  (literal CHECK value lists stay on one line each)
"""telemetry_runs and telemetry_channels (file 05 §4.4), approved by the Lead 2026-10-22.

One row per run (registry tier; run_label unique, test ids read from the document) and one row per
canonical channel with the three-tier metrics (derived tier; rebuilt with the run). A HALTED document
has no rows here. CHECK value lists are literal.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telemetry_runs",
        sa.Column("run_uuid", sa.UUID(), nullable=False),
        sa.Column("run_label", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.UUID(), nullable=False),
        sa.Column("blob_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("source_format", sa.Text(), nullable=False),
        sa.Column("run_status", sa.Text(), server_default="UNKNOWN", nullable=False),
        sa.Column("ambient_condition", sa.Text(), server_default="UNKNOWN", nullable=False),
        sa.Column("ambient_pressure_bar_abs", sa.Float(), nullable=True),
        sa.Column("sampling_rate_hz_nominal", sa.Float(), nullable=True),
        sa.Column("sampling_rate_hz_actual", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("n_rows", sa.BigInteger(), nullable=True),
        sa.Column("n_gaps", sa.Integer(), nullable=True),
        sa.Column("n_duplicate_ts", sa.Integer(), nullable=True),
        sa.Column("t0_ignition_ms", sa.BigInteger(), nullable=True),
        sa.Column("t0_method", sa.Text(), nullable=True),
        sa.Column("t0_confidence", sa.Float(), nullable=True),
        sa.Column(
            "sub_runs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("raw_parquet_uri", sa.Text(), nullable=True),
        sa.Column("normalized_parquet_uri", sa.Text(), nullable=True),
        sa.Column("schema_uri", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channel_map_rule_id", sa.UUID(), nullable=True),
        sa.Column(
            "clock_offsets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "ambient_condition IN ('VACUUM_CHAMBER', 'SEA_LEVEL', 'AMBIENT_RECORDED', 'UNKNOWN')",
            name=op.f("ck_telemetry_runs_ambient_condition"),
        ),
        sa.CheckConstraint(
            "run_status IN ('NOMINAL', 'FAILED_RUN', 'COLD_FLOW', 'PRE_HEAT', 'ABORTED', 'UNKNOWN')",
            name=op.f("ck_telemetry_runs_run_status"),
        ),
        sa.CheckConstraint(
            "source_format IN ('labjack_dat', 'tdms', 'csv', 'xlsx_sheet', 'npy_mapped')",
            name=op.f("ck_telemetry_runs_source_format"),
        ),
        sa.ForeignKeyConstraint(
            ["blob_sha256"], ["blobs.sha256"], name=op.f("fk_telemetry_runs_blob_sha256_blobs")
        ),
        sa.ForeignKeyConstraint(
            ["channel_map_rule_id"],
            ["rules.rule_id"],
            name=op.f("fk_telemetry_runs_channel_map_rule_id_rules"),
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_telemetry_runs_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_uuid", name=op.f("pk_telemetry_runs")),
        sa.UniqueConstraint("run_label", name=op.f("uq_telemetry_runs_run_label")),
    )
    op.create_index(op.f("ix_telemetry_runs_blob_sha256"), "telemetry_runs", ["blob_sha256"], unique=False)
    op.create_index(
        op.f("ix_telemetry_runs_channel_map_rule_id"), "telemetry_runs", ["channel_map_rule_id"], unique=False
    )
    op.create_index(op.f("ix_telemetry_runs_doc_id"), "telemetry_runs", ["doc_id"], unique=False)
    op.create_table(
        "telemetry_channels",
        sa.Column("run_uuid", sa.UUID(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("raw_name", sa.Text(), nullable=False),
        sa.Column("raw_unit", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Text(), nullable=True),
        sa.Column("unit_si", sa.Text(), nullable=True),
        sa.Column("gauge_or_abs", sa.Text(), server_default="n/a", nullable=False),
        sa.Column(
            "conversion",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sensor_tag", sa.Text(), nullable=True),
        sa.Column("range_min", sa.Float(), nullable=True),
        sa.Column("range_max", sa.Float(), nullable=True),
        sa.Column("stat_min", sa.Float(), nullable=True),
        sa.Column("stat_max", sa.Float(), nullable=True),
        sa.Column("stat_mean", sa.Float(), nullable=True),
        sa.Column("stat_p50", sa.Float(), nullable=True),
        sa.Column("stat_p99", sa.Float(), nullable=True),
        sa.Column("stat_std", sa.Float(), nullable=True),
        sa.Column("peak_raw", sa.Float(), nullable=True),
        sa.Column("peak_50ms", sa.Float(), nullable=True),
        sa.Column("steady_mean", sa.Float(), nullable=True),
        sa.Column("steady_window_ms", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("saturated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("null_fraction", sa.Float(), nullable=True),
        sa.Column("sparkline_asset_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "gauge_or_abs IN ('gauge', 'absolute', 'unknown', 'n/a')",
            name=op.f("ck_telemetry_channels_gauge_or_abs"),
        ),
        sa.CheckConstraint(
            "quantity IN ('pressure', 'force', 'temperature', 'mass_flow_rate', 'volume_flow_rate', 'power', 'energy', 'voltage', 'current', 'resistance', 'length', 'area', 'volume', 'mass', 'density', 'time', 'frequency', 'velocity', 'acceleration', 'specific_impulse', 'angle', 'ratio', 'valve_state', 'other')",
            name=op.f("ck_telemetry_channels_quantity"),
        ),
        sa.ForeignKeyConstraint(
            ["run_uuid"],
            ["telemetry_runs.run_uuid"],
            name=op.f("fk_telemetry_channels_run_uuid_telemetry_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sparkline_asset_id"],
            ["assets.asset_id"],
            name=op.f("fk_telemetry_channels_sparkline_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("run_uuid", "canonical_name", name=op.f("pk_telemetry_channels")),
    )
    op.create_index(
        op.f("ix_telemetry_channels_sparkline_asset_id"),
        "telemetry_channels",
        ["sparkline_asset_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_telemetry_channels_sparkline_asset_id"), table_name="telemetry_channels")
    op.drop_table("telemetry_channels")
    op.drop_index(op.f("ix_telemetry_runs_doc_id"), table_name="telemetry_runs")
    op.drop_index(op.f("ix_telemetry_runs_channel_map_rule_id"), table_name="telemetry_runs")
    op.drop_index(op.f("ix_telemetry_runs_blob_sha256"), table_name="telemetry_runs")
    op.drop_table("telemetry_runs")
