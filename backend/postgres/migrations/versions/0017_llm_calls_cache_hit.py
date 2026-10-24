"""``llm_calls.status`` gains ``cache_hit``: a call answered from the result cache (plan task 7), no request,
no tokens, no cost, so the ledger shows what a re-run did not pay for.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_llm_calls_status"), "llm_calls", type_="check")
    op.create_check_constraint(
        op.f("ck_llm_calls_status"), "llm_calls", "status IN ('ok', 'error', 'cache_hit')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM llm_calls WHERE status = 'cache_hit'")
    op.drop_constraint(op.f("ck_llm_calls_status"), "llm_calls", type_="check")
    op.create_check_constraint(op.f("ck_llm_calls_status"), "llm_calls", "status IN ('ok', 'error')")
