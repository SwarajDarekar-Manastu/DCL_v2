"""Configuration and operations tables (file 05 §4.6)."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier


class PipelineConfig(Base):
    """Append-only, versioned non-secret configuration; ``v_config_current`` is the latest version per key.

    Rollback inserts the old value as a new version. Secrets and endpoints never go here.
    """

    __tablename__ = "pipeline_config"
    __table_args__ = ({"info": tier(Tier.AUTHORED)},)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    description: Mapped[str | None] = mapped_column(Text)
