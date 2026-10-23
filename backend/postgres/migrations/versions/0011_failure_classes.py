# ruff: noqa: E501  (literal CHECK value lists stay on one line each)
"""benchmark_results.failure_class gains MISSING_DOCUMENT, INSUFFICIENT_EVIDENCE, TIMEOUT, HALTED_DATA
(DECISIONS 2026-10-22, S2 runner fixes).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "failure_class IN ('RETRIEVAL_MISS', 'RERANK_MISS', 'TOOL_MISROUTE', 'TOOL_ERROR', 'SYNTHESIS_ERROR', 'VERIFIER_FALSE_NEGATIVE', 'UNIT_ERROR', 'BEHAVIOR_FAIL')"
NEW = "failure_class IN ('RETRIEVAL_MISS', 'RERANK_MISS', 'TOOL_MISROUTE', 'TOOL_ERROR', 'SYNTHESIS_ERROR', 'VERIFIER_FALSE_NEGATIVE', 'UNIT_ERROR', 'BEHAVIOR_FAIL', 'MISSING_DOCUMENT', 'INSUFFICIENT_EVIDENCE', 'TIMEOUT', 'HALTED_DATA')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_benchmark_results_failure_class"), "benchmark_results", type_="check")
    op.create_check_constraint(op.f("ck_benchmark_results_failure_class"), "benchmark_results", NEW)


def downgrade() -> None:
    op.execute(
        "UPDATE benchmark_results SET failure_class = NULL "
        "WHERE failure_class IN ('MISSING_DOCUMENT', 'INSUFFICIENT_EVIDENCE', 'TIMEOUT', 'HALTED_DATA')"
    )
    op.drop_constraint(op.f("ck_benchmark_results_failure_class"), "benchmark_results", type_="check")
    op.create_check_constraint(op.f("ck_benchmark_results_failure_class"), "benchmark_results", OLD)
