"""llm_calls and answer_traces (file 05): the Gemini call ledger (cost per document, daily budget guard)
and one trace per Answer Engine answer. Model prices are the ``models.prices`` config key, not a table.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

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
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "answer_traces",
        sa.Column("trace_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=True),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("conversation_summary", sa.Text(), nullable=True),
        sa.Column("user_language", sa.Text(), nullable=True),
        *(
            sa.Column(name, jsonb, nullable=True)
            for name in (
                "query_analysis",
                "tool_calls",
                "retrieved",
                "external_queries",
                "claims",
                "citations",
                "verifier_result",
                "model_config",
            )
        ),
        sa.Column("answer_markdown", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Float(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("feedback", jsonb, nullable=True),
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("trace_id", name=op.f("pk_answer_traces")),
    )
    op.create_index(op.f("ix_answer_traces_created_at"), "answer_traces", ["created_at"])
    op.create_index(op.f("ix_answer_traces_user_id"), "answer_traces", ["user_id"])


def downgrade() -> None:
    op.drop_table("answer_traces")
    op.drop_table("llm_calls")
