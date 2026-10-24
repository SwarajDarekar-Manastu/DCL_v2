# ruff: noqa: E501  (literal CHECK value lists stay on one line each)
"""Rules act outside telemetry units (user, 2026-10-24, option A): rule types ``column_unit`` (the unit of a
table or prose number by column or label name) and ``source_choice`` (which side of a disagreement wins in a
scope). Telemetry channel units keep ``channel_proposal`` / ``channel_map``: a rule proposes, a person approves.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "rule_type IN ('channel_map', 'channel_proposal', 'unit_mapping', 'schema_mapping', 'supersession', 'ignore_pattern', 'origin_override')"
NEW = "rule_type IN ('channel_map', 'channel_proposal', 'unit_mapping', 'schema_mapping', 'supersession', 'ignore_pattern', 'origin_override', 'column_unit', 'source_choice')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_rules_rule_type"), "rules", type_="check")
    op.create_check_constraint(op.f("ck_rules_rule_type"), "rules", NEW)


def downgrade() -> None:
    # the rules about to go are referenced by flags, runs and newer rules: clear those references first
    for table, column in (
        ("review_flags", "resolution_rule_id"),
        ("review_flags", "proposed_by_rule_id"),
        ("telemetry_runs", "channel_map_rule_id"),
        ("rules", "supersedes_rule_id"),
    ):
        op.execute(
            sa.text(
                f"UPDATE {table} SET {column} = NULL WHERE {column} IN "  # noqa: S608  (fixed table and column names)
                "(SELECT rule_id FROM rules WHERE rule_type IN ('column_unit', 'source_choice'))"
            )
        )
    op.execute("DELETE FROM rules WHERE rule_type IN ('column_unit', 'source_choice')")
    op.drop_constraint(op.f("ck_rules_rule_type"), "rules", type_="check")
    op.create_check_constraint(op.f("ck_rules_rule_type"), "rules", OLD)
