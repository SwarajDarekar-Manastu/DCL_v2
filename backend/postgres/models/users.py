"""Console users for local password RBAC (DECISIONS 2026-10-22; Entra ID is future scope).

S1 owns the table and the first-admin bootstrap (``backend/postgres/bootstrap.py``); S3 owns
``backend/api/auth.py`` (login, JWT, user management) on top of it. ``password_hash`` is an argon2id
encoded string, never a plain password. ``email`` is stored lower-case (CHECK), so uniqueness is
case-insensitive.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, CheckConstraint, DateTime, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import UserRole, roles_check


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        roles_check("roles", UserRole),
        CheckConstraint("email = lower(email)", name="email_lower"),
        {"info": tier(Tier.AUTHORED)},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{viewer}'::text[]"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
