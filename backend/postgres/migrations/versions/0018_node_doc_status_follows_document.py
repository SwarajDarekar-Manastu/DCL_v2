"""``document_nodes.doc_status`` follows ``documents.status`` (file 05: "refreshed by the (rare) status
changes"). Only the commit wrote it, so a document that was later quarantined, failed, deleted or superseded
kept nodes marked ACTIVE and stayed searchable. A trigger copies every status change to the nodes, whatever
code path makes it, except PROCESSING: during a re-run the last committed version stays searchable until the
new commit replaces it. The upgrade also corrects the nodes that are already stale.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION document_status_to_nodes() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status <> 'PROCESSING' THEN
                UPDATE document_nodes SET doc_status = NEW.status
                WHERE doc_id = NEW.doc_id AND doc_status IS DISTINCT FROM NEW.status;
            END IF;
            RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_status_to_nodes AFTER UPDATE OF status ON documents
        FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
        EXECUTE FUNCTION document_status_to_nodes()
        """
    )
    op.execute(
        """
        UPDATE document_nodes n SET doc_status = d.status FROM documents d
        WHERE n.doc_id = d.doc_id AND d.status <> 'PROCESSING' AND n.doc_status IS DISTINCT FROM d.status
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER document_status_to_nodes ON documents")
    op.execute("DROP FUNCTION document_status_to_nodes()")
