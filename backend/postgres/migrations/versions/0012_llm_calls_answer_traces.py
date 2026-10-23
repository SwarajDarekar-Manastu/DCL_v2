"""llm_calls (file 05): the Gemini call ledger for cost per document and the daily budget guard.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("call_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("doc_id", sa.UUID(), nullable=True),
        sa.Column("node_anchor", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Float(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('ok', 'error')", name=op.f("ck_llm_calls_status")),
        sa.PrimaryKeyConstraint("call_id", name=op.f("pk_llm_calls")),
    )
    op.create_index(op.f("ix_llm_calls_at"), "llm_calls", ["at"])
    op.create_index(op.f("ix_llm_calls_doc_id"), "llm_calls", ["doc_id"])


def downgrade() -> None:
    op.drop_table("llm_calls")
