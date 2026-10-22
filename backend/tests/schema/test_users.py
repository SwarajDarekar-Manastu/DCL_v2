"""users (migration 0010): role CHECK per array element, lower-case unique email."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
