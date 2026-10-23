# ruff: noqa: E501  (literal CHECK value lists stay on one line each)
"""Rules propose, people approve: rule type ``channel_proposal`` and ``review_flags.proposed_by_rule_id``.

A ``channel_proposal`` rule pre-fills the units of the files it matches; Route C never reads it as an answer
(only ``channel_map``, a person's approval of one file, is). ``proposed_by_rule_id`` keeps which rule a
suggestion came from, so a rule can show how many files it proposed to and how many a person approved.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "rule_type IN ('channel_map', 'unit_mapping', 'schema_mapping', 'supersession', 'ignore_pattern', 'origin_override')"
NEW = "rule_type IN ('channel_map', 'channel_proposal', 'unit_mapping', 'schema_mapping', 'supersession', 'ignore_pattern', 'origin_override')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_rules_rule_type"), "rules", type_="check")
    op.create_check_constraint(op.f("ck_rules_rule_type"), "rules", NEW)
    op.add_column("review_flags", sa.Column("proposed_by_rule_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_review_flags_proposed_by_rule_id_rules"),
        "review_flags",
        "rules",
        ["proposed_by_rule_id"],
        ["rule_id"],
    )
    op.create_index(op.f("ix_review_flags_proposed_by_rule_id"), "review_flags", ["proposed_by_rule_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_review_flags_proposed_by_rule_id"), table_name="review_flags")
    op.drop_constraint(op.f("fk_review_flags_proposed_by_rule_id_rules"), "review_flags", type_="foreignkey")
    op.drop_column("review_flags", "proposed_by_rule_id")
    op.execute("DELETE FROM rules WHERE rule_type = 'channel_proposal'")
    op.drop_constraint(op.f("ck_rules_rule_type"), "rules", type_="check")
    op.create_check_constraint(op.f("ck_rules_rule_type"), "rules", OLD)
