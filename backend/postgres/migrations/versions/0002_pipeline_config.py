"""pipeline_config (append-only, versioned) and v_config_current; read by the gate and the scopes in M1.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_config",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("description", sa.Text()),
        sa.PrimaryKeyConstraint("key", "version"),
    )
    op.execute(
        """
        CREATE VIEW v_config_current AS
        SELECT DISTINCT ON (key) key, version, value, updated_by, updated_at, description
        FROM pipeline_config
        ORDER BY key, version DESC
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW v_config_current")
    op.drop_table("pipeline_config")
