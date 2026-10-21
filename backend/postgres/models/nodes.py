"""Retrieval nodes and renderable assets (file 05 §4.2). Both are derived: rebuilt, never hand-edited.

``node_id`` changes on every re-index; nothing durable stores it (file 04 §4.4). ``bbox`` is a JSON
list of ``{page_no, x0, y0, x1, y1}`` in 0..1 with a top-left origin. The HNSW (and later BM25)
indexes live in hand-written migrations and are named ``hnsw_*`` / ``bm25_*``.
"""

import uuid
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import CHAR, BigInteger, Boolean, Float, ForeignKey, Index, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import (
    AssetKind,
    DocKind,
    DocumentStatus,
    NodeSource,
    NodeType,
    SourceOrigin,
    enum_check,
)

EMBEDDING_DIM = 768
EMPTY_OBJECT = text("'{}'::jsonb")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (enum_check("kind", AssetKind), {"info": tier(Tier.DERIVED)})

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    minio_uri: Mapped[str] = mapped_column(Text, unique=True)
    blob_sha256: Mapped[str] = mapped_column(CHAR(64), ForeignKey("blobs.sha256"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    t_ms: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    phash: Mapped[str | None] = mapped_column(Text)
    photo_cluster_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_cluster_representative: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    exif: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)


class DocumentNode(Base):
    __tablename__ = "document_nodes"
    __table_args__ = (
        enum_check("node_type", NodeType),
        enum_check("source", NodeSource),
        enum_check("doc_kind", DocKind),
        enum_check("source_origin", SourceOrigin),
        enum_check("doc_status", DocumentStatus),
        Index(None, "doc_id", "ordinal"),
        Index(None, "node_type"),
        Index(None, "parent_node_id"),
        Index(None, "test_plan_id"),
        Index(None, "doc_kind"),
        Index(None, "source_origin", "trust_tier"),
        Index("ix_document_nodes_needs_review_doc_id", "doc_id", postgresql_where=text("needs_review")),
        {"info": tier(Tier.DERIVED)},
    )

    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE")
    )
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    node_type: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    ordinal: Mapped[int] = mapped_column(Integer)
    breadcrumb: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_en: Mapped[str | None] = mapped_column(Text)
    content_codes: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    embed_text: Mapped[str | None] = mapped_column(Text)
    embed_text_hash: Mapped[str | None] = mapped_column(CHAR(64))
    embedding: Mapped[Any | None] = mapped_column(HALFVEC(EMBEDDING_DIM))
    image_embedding: Mapped[Any | None] = mapped_column(HALFVEC(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    page_no: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    t_start_ms: Mapped[int | None] = mapped_column(BigInteger)
    t_end_ms: Mapped[int | None] = mapped_column(BigInteger)
    sheet_name: Mapped[str | None] = mapped_column(Text)
    cell_range: Mapped[str | None] = mapped_column(Text)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.asset_id"), index=True
    )
    source: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    doc_kind: Mapped[str | None] = mapped_column(Text)
    test_plan_id: Mapped[str | None] = mapped_column(Text)
    source_origin: Mapped[str | None] = mapped_column(Text)
    trust_tier: Mapped[int | None] = mapped_column(SmallInteger)
    doc_status: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=EMPTY_OBJECT)
    pipeline_version: Mapped[int | None] = mapped_column(Integer)
