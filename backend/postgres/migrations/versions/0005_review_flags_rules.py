# ruff: noqa: E501  (literal CHECK value lists stay on one line each)
"""rules and review_flags (file 05 §4.5): the review backend starts with the Tier-4 flags.

review_flags is unique on (doc_id, fingerprint) and, for flags raised before a document exists
(HELD_LARGE_FILE, Tier-4 SENSITIVE_CONTENT), on (location_id, fingerprint) where doc_id is null.
CHECK value lists are literal.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22 01:21:57.358477
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("rule_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("scope_root", sa.Text(), nullable=True),
        sa.Column("scope_folder_id", sa.Text(), nullable=True),
        sa.Column("scope_filename_glob", sa.Text(), nullable=True),
        sa.Column("scope_extension", sa.Text(), nullable=True),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("precedence", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_blob_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("supersedes_rule_id", sa.UUID(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "origin IN ('operator', 'cfg', 'header', 'config_json', 'tdms_props')",
            name=op.f("ck_rules_origin"),
        ),
        sa.CheckConstraint(
            "rule_type IN ('channel_map', 'unit_mapping', 'schema_mapping', 'supersession', 'ignore_pattern', 'origin_override')",
            name=op.f("ck_rules_rule_type"),
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_rule_id"], ["rules.rule_id"], name=op.f("fk_rules_supersedes_rule_id_rules")
        ),
        sa.PrimaryKeyConstraint("rule_id", name=op.f("pk_rules")),
    )
    op.create_index(
        "ix_rules_active_type_folder",
        "rules",
        ["rule_type", "scope_folder_id"],
        unique=False,
        postgresql_where=sa.text("active"),
    )
    op.create_index(op.f("ix_rules_source_blob_sha256"), "rules", ["source_blob_sha256"], unique=False)
    op.create_index(op.f("ix_rules_supersedes_rule_id"), "rules", ["supersedes_rule_id"], unique=False)
    op.create_table(
        "review_flags",
        sa.Column("flag_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_key", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.UUID(), nullable=True),
        sa.Column("location_id", sa.UUID(), nullable=True),
        sa.Column("page_or_sheet", sa.Text(), server_default="", nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("flag_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="OPEN", nullable=False),
        sa.Column("route", sa.Text(), nullable=True),
        sa.Column(
            "anchor",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("suggested_resolution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolution_rule_id", sa.UUID(), nullable=True),
        sa.Column("assigned_to", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "flag_type IN ('UNIT_AMBIGUITY', 'SCHEMA_UNKNOWN', 'LOW_CONFIDENCE_EXTRACTION', 'PARSE_FAILURE', 'UNSUPPORTED_FORMAT', 'CONFLICT', 'SENSITIVE_CONTENT', 'HELD_LARGE_FILE', 'CLOUD_RESTRICTED')",
            name=op.f("ck_review_flags_flag_type"),
        ),
        sa.CheckConstraint("severity IN ('HARD', 'SOFT')", name=op.f("ck_review_flags_severity")),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'REJECTED_FILE', 'AUTO_RESOLVED', 'REOPENED')",
            name=op.f("ck_review_flags_status"),
        ),
        sa.CheckConstraint(
            "doc_id IS NOT NULL OR location_id IS NOT NULL", name=op.f("ck_review_flags_doc_or_location")
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_review_flags_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["drive_items.location_id"], name=op.f("fk_review_flags_location_id_drive_items")
        ),
        sa.ForeignKeyConstraint(
            ["resolution_rule_id"], ["rules.rule_id"], name=op.f("fk_review_flags_resolution_rule_id_rules")
        ),
        sa.PrimaryKeyConstraint("flag_id", name=op.f("pk_review_flags")),
        sa.UniqueConstraint("doc_id", "fingerprint", name=op.f("uq_review_flags_doc_id_fingerprint")),
    )
    op.create_index(op.f("ix_review_flags_case_key"), "review_flags", ["case_key"], unique=False)
    op.create_index(op.f("ix_review_flags_location_id"), "review_flags", ["location_id"], unique=False)
    op.create_index(
        op.f("ix_review_flags_resolution_rule_id"), "review_flags", ["resolution_rule_id"], unique=False
    )
    op.create_index(
        "uq_review_flags_location_fingerprint",
        "review_flags",
        ["location_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("doc_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_review_flags_location_fingerprint",
        table_name="review_flags",
        postgresql_where=sa.text("doc_id IS NULL"),
    )
    op.drop_index(op.f("ix_review_flags_resolution_rule_id"), table_name="review_flags")
    op.drop_index(op.f("ix_review_flags_location_id"), table_name="review_flags")
    op.drop_index(op.f("ix_review_flags_case_key"), table_name="review_flags")
    op.drop_table("review_flags")
    op.drop_index(op.f("ix_rules_supersedes_rule_id"), table_name="rules")
    op.drop_index(op.f("ix_rules_source_blob_sha256"), table_name="rules")
    op.drop_index("ix_rules_active_type_folder", table_name="rules", postgresql_where=sa.text("active"))
    op.drop_table("rules")
