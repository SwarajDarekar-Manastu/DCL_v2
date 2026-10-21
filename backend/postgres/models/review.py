"""Review tables (file 05 §4.5): `audit_events` now; `review_flags` and `rules` with the review backend."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import AuditEntityType, enum_check


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
