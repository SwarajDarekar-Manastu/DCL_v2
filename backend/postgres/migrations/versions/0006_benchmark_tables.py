# ruff: noqa: E501  (literal CHECK value lists stay on one line each)
"""Benchmark tables (file 05 §4.7): benchmark_cases (authored, keyed (case_id, version)),
benchmark_runs, benchmark_results. FKs to answer_traces come with that table (M8).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22 01:32:43.986569
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmark_cases",
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("suite", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "spec",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("difficulty", sa.SmallInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_trace_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "category IN ('TELEMETRY_MATH', 'FACT_LOOKUP', 'CODE', 'FAILURE_ANALYSIS', 'STANDARDS', 'DESIGN_SYNTHESIS', 'NAVIGATIONAL', 'VISUAL', 'OUT_OF_SCOPE', 'HALTED_DATA_BEHAVIOR', 'CONFLICT_BEHAVIOR', 'MULTILINGUAL', 'LIBRARY_VS_INTERNAL')",
            name=op.f("ck_benchmark_cases_category"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')", name=op.f("ck_benchmark_cases_status")
        ),
        sa.PrimaryKeyConstraint("case_id", "version", name=op.f("pk_benchmark_cases")),
    )
    op.create_index(
        op.f("ix_benchmark_cases_suite_status"), "benchmark_cases", ["suite", "status"], unique=False
    )
    op.create_table(
        "benchmark_runs",
        sa.Column("run_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("suite", sa.Text(), nullable=False),
        sa.Column(
            "case_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("git_commit", sa.Text(), nullable=True),
        sa.Column(
            "model_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("pipeline_version", sa.Integer(), nullable=True),
        sa.Column("active_doc_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "aggregate",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_benchmark_runs_status"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_benchmark_runs")),
    )
    op.create_index(
        op.f("ix_benchmark_runs_suite_started_at"), "benchmark_runs", ["suite", "started_at"], unique=False
    )
    op.create_table(
        "benchmark_results",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.UUID(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("failure_class", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "failure_class IN ('RETRIEVAL_MISS', 'RERANK_MISS', 'TOOL_MISROUTE', 'TOOL_ERROR', 'SYNTHESIS_ERROR', 'VERIFIER_FALSE_NEGATIVE', 'UNIT_ERROR', 'BEHAVIOR_FAIL')",
            name=op.f("ck_benchmark_results_failure_class"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "case_version"],
            ["benchmark_cases.case_id", "benchmark_cases.version"],
            name=op.f("fk_benchmark_results_case_id_case_version_benchmark_cases"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["benchmark_runs.run_id"],
            name=op.f("fk_benchmark_results_run_id_benchmark_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "case_id", name=op.f("pk_benchmark_results")),
    )
    op.create_index(
        op.f("ix_benchmark_results_case_id_case_version"),
        "benchmark_results",
        ["case_id", "case_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_benchmark_results_case_id_case_version"), table_name="benchmark_results")
    op.drop_table("benchmark_results")
    op.drop_index(op.f("ix_benchmark_runs_suite_started_at"), table_name="benchmark_runs")
    op.drop_table("benchmark_runs")
    op.drop_index(op.f("ix_benchmark_cases_suite_status"), table_name="benchmark_cases")
    op.drop_table("benchmark_cases")
