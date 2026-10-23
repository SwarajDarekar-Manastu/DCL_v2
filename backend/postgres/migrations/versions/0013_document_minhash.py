"""documents.minhash: the 128-value MinHash signature of a document's body text (file 02 §5.3,
DECISIONS 2026-10-23). Nullable: documents with too little text, and documents not yet re-indexed, have none.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("minhash", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "minhash")
