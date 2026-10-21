"""drive_items.previous_blob_sha256: in-place content replacement handed to the dispatcher (Lead 2026-10-22).

No FK (an old blob may be purged); partial index where not null.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drive_items", sa.Column("previous_blob_sha256", sa.CHAR(64), nullable=True))
    op.create_index(
        "ix_drive_items_previous_blob_sha256",
        "drive_items",
        ["previous_blob_sha256"],
        postgresql_where=sa.text("previous_blob_sha256 IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_drive_items_previous_blob_sha256", table_name="drive_items")
    op.drop_column("drive_items", "previous_blob_sha256")
