"""Entities, aliases, mentions and numeric facts (file 05 §4.3).

Entities and aliases are authored (merges are human decisions, audited); mentions and facts are
derived and go with their node: deleting a document's nodes deletes them (ON DELETE CASCADE).
"""

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import (
    AliasCreatedBy,
    EntityCreatedBy,
    EntityType,
    GaugeOrAbs,
    MentionSource,
    NumericFactSource,
    Quantity,
    enum_check,
)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("type", "canonical_key"),
        enum_check("type", EntityType),
        enum_check("created_by", EntityCreatedBy),
        {"info": tier(Tier.AUTHORED)},
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    type: Mapped[str] = mapped_column(Text)
    canonical_name: Mapped[str] = mapped_column(Text)
    canonical_key: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    first_seen_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="SET NULL"), index=True
    )


class EntityAlias(Base):
    """Surface form → entity. A merge re-points aliases and mentions (no ``merged_into`` column)."""

    __tablename__ = "entity_aliases"
    __table_args__ = (
        enum_check("type", EntityType),
        enum_check("created_by", AliasCreatedBy),
        {"info": tier(Tier.AUTHORED)},
    )

    type: Mapped[str] = mapped_column(Text, primary_key=True)
    alias_key: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.entity_id"), index=True
    )
    alias: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    fuzzy_score: Mapped[float | None] = mapped_column(Float)


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    __table_args__ = (enum_check("source", MentionSource), {"info": tier(Tier.DERIVED)})

    mention_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_nodes.node_id", ondelete="CASCADE"), index=True
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.entity_id"), index=True
    )
    surface: Mapped[str] = mapped_column(Text)
    span_start: Mapped[int | None] = mapped_column(Integer)
    span_end: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(Text)


class NumericFact(Base):
    __tablename__ = "numeric_facts"
    __table_args__ = (
        enum_check("quantity", Quantity),
        enum_check("gauge_or_abs", GaugeOrAbs),
        enum_check("source", NumericFactSource),
        Index(None, "quantity", "value_si"),
        {"info": tier(Tier.DERIVED)},
    )

    fact_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_nodes.node_id", ondelete="CASCADE"), index=True
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[str] = mapped_column(Text)
    value_raw: Mapped[str | None] = mapped_column(Text)
    unit_raw: Mapped[str | None] = mapped_column(Text)
    value_si: Mapped[float | None] = mapped_column(Float)
    unit_si: Mapped[str | None] = mapped_column(Text)
    gauge_or_abs: Mapped[str] = mapped_column(Text, server_default=GaugeOrAbs.NOT_APPLICABLE.value)
    context: Mapped[str | None] = mapped_column(Text)
    span_start: Mapped[int | None] = mapped_column(Integer)
    span_end: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    suspect: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    needs_unit: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
