"""users (migration 0010): role CHECK per array element, lower-case unique email, admin bootstrap."""

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.postgres.bootstrap import bootstrap_admin
from backend.postgres.models import User


@pytest.fixture()
def session(migrated):
    with Session(migrated) as s:
        yield s


def _user(email="asha@manastu.space", roles=("viewer",)):
    return User(email=email, display_name="Asha", password_hash="$argon2id$x", roles=list(roles))


def test_defaults_and_every_role_accepted(session):
    session.add(_user(roles=["viewer", "reviewer", "admin"]))
    session.commit()
    user = session.scalars(select(User)).one()
    assert (user.is_active, user.last_login_at is None, user.created_at is not None) == (True, True, True)


@pytest.mark.parametrize("roles", [["owner"], ["viewer", "superuser"], ["Admin"]])
def test_unknown_role_is_refused(session, roles):
    session.add(_user(roles=roles))
    with pytest.raises(IntegrityError, match="ck_users_roles"):
        session.commit()


def test_email_is_lower_case_and_unique(session):
    session.add(_user(email="Asha@manastu.space"))
    with pytest.raises(IntegrityError, match="ck_users_email_lower"):
        session.commit()
    session.rollback()
    session.add(_user())
    session.commit()
    session.add(_user())
    with pytest.raises(IntegrityError, match="uq_users_email"):
        session.commit()


def test_bootstrap_creates_one_admin_once(session):
    admin = bootstrap_admin(session, " Admin@Manastu.Space ", "correct horse battery")
    session.commit()
    assert (admin.email, admin.roles, admin.is_active) == (
        "admin@manastu.space",
        ["viewer", "reviewer", "admin"],
        True,
    )
    assert admin.password_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(admin.password_hash, "correct horse battery")
    assert bootstrap_admin(session, "other@manastu.space", "another long password") is None
    assert session.scalars(select(User.email)).all() == ["admin@manastu.space"]


def test_bootstrap_without_settings_or_with_a_short_password(session):
    assert bootstrap_admin(session, None, None) is None
    with pytest.raises(ValueError, match="at least 12"):
        bootstrap_admin(session, "a@b.c", "short")
