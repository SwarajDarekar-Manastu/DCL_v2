# ruff: noqa: E501  (the pg_search DDL stays verbatim)
"""Metadata in search (docs/sessions/PLAN_metadata_search.md, user 2026-10-26).

- ``bm25_document_nodes`` also indexes ``embed_text``: the contextual header (title, kind, date, test labels,
  piece type, path, About line, entities) becomes searchable by keyword, not only by the dense vector.
- Every file has one card (``indexing/card.py``): ``documents.search_text`` holds its text, ``card_codes``
  its normalized identifiers, ``card_embedding`` its vector. Halted files get one too. ``bm25_documents``
  indexes the card with the test labels, kind, status and route as exact fields; HNSW indexes the vector.
  The catalog step of the answer engine (``engine/catalog.py``) searches them.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-26
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC


def _revision_0004():
    """The pinned BM25 DDL of 0004 (one source for that text; migrations are files, not a package)."""
    spec = importlib.util.spec_from_file_location("rev0004", Path(__file__).with_name("0004_bm25_indexes.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


old = _revision_0004()

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BM25_DOCUMENT_NODES = old.BM25_DOCUMENT_NODES.replace(
    "    (breadcrumb::pdb.simple('stemmer=english')),\n",
    "    (breadcrumb::pdb.simple('stemmer=english')),\n    (embed_text::pdb.simple('stemmer=english')),\n",
)

BM25_DOCUMENTS = """
CREATE INDEX bm25_documents ON documents USING bm25 (
    doc_id,
    (search_text::pdb.simple('stemmer=english')),
    (title::pdb.simple('stemmer=english')),
    (card_codes::pdb.whitespace),
    (status::pdb.literal), (route::pdb.literal), (doc_kind::pdb.literal),
    (test_plan_id::pdb.literal), (test_run_id::pdb.literal), (hardware_item::pdb.literal)
)
"""


def upgrade() -> None:
    op.add_column("documents", sa.Column("card_codes", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("card_embedding", HALFVEC(768), nullable=True))
    op.execute(
        "CREATE INDEX hnsw_documents_card_embedding ON documents USING hnsw (card_embedding halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    )
    op.execute("DROP INDEX IF EXISTS bm25_document_nodes")
    op.execute(BM25_DOCUMENT_NODES)
    op.execute("DROP INDEX IF EXISTS bm25_documents")
    op.execute(BM25_DOCUMENTS)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS bm25_documents")
    op.execute(old.BM25_DOCUMENTS)
    op.execute("DROP INDEX IF EXISTS bm25_document_nodes")
    op.execute(old.BM25_DOCUMENT_NODES)
    op.execute("DROP INDEX IF EXISTS hnsw_documents_card_embedding")
    op.drop_column("documents", "card_embedding")
    op.drop_column("documents", "card_codes")
