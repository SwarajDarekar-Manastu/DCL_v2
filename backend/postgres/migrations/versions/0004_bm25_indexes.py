# ruff: noqa: E501  (the pg_search DDL stays verbatim)
"""BM25 indexes (pg_search, ParadeDB 0.26.2-pg17): the one pinned file for this DDL (file 01 §5.5).

The fields and aliases are queried by S2's retrieval SQL exactly as written; DDL verified by S2 on
paradedb/paradedb:0.26.2-pg17 at revision 0003. One BM25 index per table is allowed.
Fallback without pg_search: native tsvector/GIN (file 04 §6), in its own migration if ever needed.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BM25_DOCUMENT_NODES = """
CREATE INDEX bm25_document_nodes ON document_nodes USING bm25 (
    node_id,
    (content::pdb.icu),
    (content::pdb.simple('stemmer=english', 'alias=content_stem_en')),
    (content::pdb.simple('stemmer=german', 'alias=content_stem_de')),
    (content::pdb.simple('stemmer=french', 'alias=content_stem_fr')),
    (content::pdb.simple('stemmer=spanish', 'alias=content_stem_es')),
    (content::pdb.simple('stemmer=italian', 'alias=content_stem_it')),
    (content::pdb.simple('stemmer=russian', 'alias=content_stem_ru')),
    (content::pdb.lindera('japanese', 'alias=content_ja')),
    (content::pdb.lindera('korean', 'alias=content_ko')),
    (content::pdb.jieba('alias=content_zh')),
    (content_codes::pdb.whitespace),
    (content_en::pdb.simple('stemmer=english')),
    (breadcrumb::pdb.simple('stemmer=english')),
    (node_type::pdb.literal), (doc_kind::pdb.literal), (test_plan_id::pdb.literal),
    (source_origin::pdb.literal), (doc_status::pdb.literal), (language::pdb.literal),
    doc_id, trust_tier, needs_review
)
"""

BM25_DOCUMENTS = """
CREATE INDEX bm25_documents ON documents USING bm25 (
    doc_id,
    (search_text::pdb.simple('stemmer=english')),
    (title::pdb.simple('stemmer=english')),
    (status::pdb.literal)
)
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
    op.execute(BM25_DOCUMENT_NODES)
    op.execute(BM25_DOCUMENTS)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS bm25_documents")
    op.execute("DROP INDEX IF EXISTS bm25_document_nodes")
