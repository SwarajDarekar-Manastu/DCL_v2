"""Taking a document's content out of the index (file 06 §7; file 02 §5.1).

A document leaves search by its status (``document_nodes.doc_status`` follows it, migration 0018), but until
2026-10-27 its rows stayed: a halted file's old chunks, numbers, names and summary could still be read by
id, in the viewer and in the catalog. ``withdraw`` deletes what a commit wrote for a document and keeps the
documents row. It runs when an indexed file halts (a blocking question reopened or newly raised), when a
review decision takes the file out (skip, junk, exclude), and when a newer version replaces it
(dispatcher/routing.py ``purge_replaced``). A later commit writes everything again from the new run.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.postgres.models import Document, DocumentNode, EntityMention, NumericFact, TelemetryRun


def withdraw(session: Session, document: Document) -> bool:
    """Delete the document's nodes, numbers, mentions and runs (channels go with their run) and clear its
    derived fields; returns whether it had content in the index."""
    doc_id = document.doc_id
    had = (
        session.scalar(select(DocumentNode.node_id).where(DocumentNode.doc_id == doc_id).limit(1)) is not None
    )
    for model in (EntityMention, NumericFact, DocumentNode, TelemetryRun):
        session.execute(delete(model).where(model.doc_id == doc_id))
    document.enrichment, document.entity_ids = {}, []
    document.search_text = document.card_codes = document.card_embedding = None
    session.flush()
    return had
