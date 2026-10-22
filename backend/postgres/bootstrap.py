"""First-admin bootstrap for local password RBAC (DECISIONS 2026-10-22). Owner: S1.

When ``users`` is empty and ``DCL_BOOTSTRAP_ADMIN_EMAIL`` / ``DCL_BOOTSTRAP_ADMIN_PASSWORD`` are set, one
active admin is created with an argon2id hash. Idempotent: a table with any row is left alone, so a
restart never resets a changed password. Call ``bootstrap_admin`` from the API start-up.
"""

import logging

from argon2 import PasswordHasher
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from backend.postgres.enums import UserRole
from backend.postgres.models import User

log = logging.getLogger(__name__)
MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    """argon2id with argon2-cffi's defaults (RFC 9106 low-memory profile)."""
    return PasswordHasher().hash(password)


def bootstrap_admin(session: Session, email: str | None, password: str | None) -> User | None:
    """The new admin, or None when users exist or the settings are absent. The caller commits."""
    if session.scalar(select(exists().where(User.user_id.is_not(None)))):
        return None
    if not email or not password:
        log.warning("users is empty and DCL_BOOTSTRAP_ADMIN_EMAIL/PASSWORD are not set: nobody can sign in")
        return None
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"DCL_BOOTSTRAP_ADMIN_PASSWORD must have at least {MIN_PASSWORD_LENGTH} characters")
    email = email.strip().lower()
    user = User(
        email=email,
        display_name=email.split("@", 1)[0],
        password_hash=hash_password(password),
        roles=[r.value for r in UserRole],
    )
    session.add(user)
    session.flush()
    log.warning("bootstrapped the first admin %s; change the password after the first sign-in", email)
    return user
