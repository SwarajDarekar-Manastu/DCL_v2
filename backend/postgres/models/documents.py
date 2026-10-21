"""Logical documents and their links to blobs and to each other (file 05 §4.2).

``documents.status`` is the document's state, shared by every location holding the content;
locations are derived: ``document_sources ⋈ drive_items ON blob_sha256``.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import (
    DocKind,
    DocumentRelationType,
    DocumentSourceRole,
    DocumentStatus,
    Route,
    SourceOrigin,
    enum_check,
)

TIMESTAMPTZ = DateTime(timezone=True)
EMPTY_OBJECT = text("'{}'::jsonb")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        enum_check("route", Route),
        enum_check("doc_kind", DocKind),
        enum_check("status", DocumentStatus),
        enum_check("source_origin", SourceOrigin),
        CheckConstraint("trust_tier BETWEEN 1 AND 6", name="trust_tier"),
        CheckConstraint("(status = 'HALTED') = (staged_payload_uri IS NOT NULL)", name="staged_when_halted"),
        Index(None, "status"),
        Index(None, "doc_kind", "status"),
        Index(None, "test_plan_id"),
        Index(None, "test_run_id"),
        Index(None, "standard_id"),
        Index(None, "source_origin", "trust_tier"),
        Index(None, "entity_ids", postgresql_using="gin"),
        Index(None, "enrichment", postgresql_using="gin", postgresql_ops={"enrichment": "jsonb_path_ops"}),
        {"info": tier(Tier.REGISTRY)},
    )

    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    route: Mapped[str | None] = mapped_column(Text)  # NULL: no adapter (UNSUPPORTED_FORMAT)
    title: Mapped[str | None] = mapped_column(Text)
    doc_kind: Mapped[str] = mapped_column(Text, server_default=DocKind.UNKNOWN.value)
    status: Mapped[str] = mapped_column(Text)
    source_origin: Mapped[str] = mapped_column(Text, server_default=SourceOrigin.INTERNAL.value)
    trust_tier: Mapped[int | None] = mapped_column(SmallInteger)
    publisher: Mapped[str | None] = mapped_column(Text)
    external_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    test_plan_id: Mapped[str | None] = mapped_column(Text)
    test_run_id: Mapped[str | None] = mapped_column(Text)
    hardware_item: Mapped[str | None] = mapped_column(Text)
    doc_date: Mapped[date | None] = mapped_column(Date)
    date_source: Mapped[str | None] = mapped_column(Text)
    standard_id: Mapped[str | None] = mapped_column(Text)
    standard_revision: Mapped[str | None] = mapped_column(Text)
    revision_marker: Mapped[str | None] = mapped_column(Text)
    classification_marking: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    languages_detected: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    number_locale: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    unit_count: Mapped[int | None] = mapped_column(Integer)
    folder_context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    metadata_sources: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    enrichment: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    catalog: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'::uuid[]")
    )
    search_text: Mapped[str | None] = mapped_column(Text)
    cir_uri: Mapped[str | None] = mapped_column(Text)
    staged_payload_uri: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[int | None] = mapped_column(Integer)
    pipeline_version: Mapped[int | None] = mapped_column(Integer)
    cloud_processed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))
    indexed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class DocumentSource(Base):
    """The only link between documents and blobs: one primary per document, one document per primary blob."""

    __tablename__ = "document_sources"
    __table_args__ = (
        enum_check("role", DocumentSourceRole),
        Index(
            "uq_document_sources_primary_per_doc",
            "doc_id",
            unique=True,
            postgresql_where=text("role = 'primary'"),
        ),
        Index(
            "uq_document_sources_primary_blob",
            "blob_sha256",
            unique=True,
            postgresql_where=text("role = 'primary'"),
        ),
        Index(None, "blob_sha256"),
        {"info": tier(Tier.REGISTRY)},
    )

    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE"), primary_key=True
    )
    blob_sha256: Mapped[str] = mapped_column(CHAR(64), ForeignKey("blobs.sha256"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)


class DocumentRelation(Base):
    """SUPERSEDES (a supersedes b), NEAR_DUPLICATE and REFERENCES; symmetric relations keep a < b."""

    __tablename__ = "document_relations"
    __table_args__ = (
        enum_check("relation", DocumentRelationType),
        CheckConstraint("relation = 'SUPERSEDES' OR doc_id_a < doc_id_b", name="symmetric_order"),
        Index(None, "doc_id_b"),
        {"info": tier(Tier.REGISTRY)},
    )

    doc_id_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE"), primary_key=True
    )
    doc_id_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[float | None] = mapped_column(Float)
    created_by: Mapped[str] = mapped_column(Text, server_default="system")
