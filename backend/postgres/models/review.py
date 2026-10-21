"""Review tables (file 05 §4.5): audit_events, rules, review_flags."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import (
    AuditEntityType,
    FlagSeverity,
    FlagStatus,
    FlagType,
    RuleOrigin,
    RuleType,
    enum_check,
)


class AuditEvent(Base):
    """Append-only log of human actions; machine activity is in ``jobs`` and ``llm_calls``."""

    __tablename__ = "audit_events"
    __table_args__ = (
        enum_check("entity_type", AuditEntityType),
        Index(None, "entity_type", "entity_id", "at"),
        {"info": tier(Tier.AUTHORED)},
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    actor: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Rule(Base):
    """Operator rules and derived maps in one table; one precedence resolver (backend/review/rules.py).

    Operator rules are immutable: a change inserts a row with ``supersedes_rule_id``. Derived rules are
    replaced when ``source_blob_sha256`` changes (no FK: the blob purge must not be blocked).
    """

    __tablename__ = "rules"
    __table_args__ = (
        enum_check("rule_type", RuleType),
        enum_check("origin", RuleOrigin),
        Index("ix_rules_active_type_folder", "rule_type", "scope_folder_id", postgresql_where=text("active")),
        Index(None, "source_blob_sha256"),
        {"info": tier(Tier.AUTHORED)},
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    rule_type: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    scope_root: Mapped[str | None] = mapped_column(Text)
    scope_folder_id: Mapped[str | None] = mapped_column(Text)
    scope_filename_glob: Mapped[str | None] = mapped_column(Text)
    scope_extension: Mapped[str | None] = mapped_column(Text)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    precedence: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    source_blob_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    supersedes_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.rule_id"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class ReviewFlag(Base):
    """A structured question to a human (file 06 §5). Upserted by fingerprint: per document, or per
    location for flags raised before a document exists (HELD_LARGE_FILE, Tier-4 SENSITIVE_CONTENT)."""

    __tablename__ = "review_flags"
    __table_args__ = (
        UniqueConstraint("doc_id", "fingerprint"),
        Index(
            "uq_review_flags_location_fingerprint",
            "location_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("doc_id IS NULL"),
        ),
        CheckConstraint("doc_id IS NOT NULL OR location_id IS NOT NULL", name="doc_or_location"),
        enum_check("flag_type", FlagType),
        enum_check("severity", FlagSeverity),
        enum_check("status", FlagStatus),
        Index(None, "case_key"),
        Index(None, "location_id"),
        {"info": tier(Tier.AUTHORED)},
    )

    flag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    case_key: Mapped[str] = mapped_column(Text)
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE")
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drive_items.location_id")
    )
    page_or_sheet: Mapped[str] = mapped_column(Text, server_default="")
    fingerprint: Mapped[str] = mapped_column(Text)
    flag_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=FlagStatus.OPEN.value)
    route: Mapped[str | None] = mapped_column(Text)
    anchor: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    suggested_resolution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resolution_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.rule_id"), index=True
    )
    assigned_to: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
