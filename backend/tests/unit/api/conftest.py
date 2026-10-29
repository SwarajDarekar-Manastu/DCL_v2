import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.api.auth import AuthConfig
from backend.tests.unit.sync.conftest import engine, session  # noqa: F401 (DB tests: disposable PostgreSQL)

TENANT = "11111111-1111-1111-1111-111111111111"
AUDIENCE = "api://dcl-console-api"
REVIEWERS = "group-reviewers"
ADMINS = "group-admins"
CONFIG = AuthConfig(tenant_id=TENANT, audience=AUDIENCE, group_reviewers=REVIEWERS, group_admins=ADMINS)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def resolve_key(token: str):
    return _KEY.public_key()


def make_token(*, groups=(), lifetime_s=3600, signed_by=None, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": AUDIENCE,
        "tid": TENANT,
        "oid": str(uuid.uuid4()),
        "name": "Test Engineer",
        "preferred_username": "engineer@manastuspace.com",
        "iat": now,
        "exp": now + lifetime_s,
        "groups": list(groups),
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, signed_by or _KEY, algorithm="RS256", headers={"kid": "test"})


@pytest.fixture
def other_key():
    return _OTHER_KEY


@pytest.fixture
def auth_config() -> AuthConfig:
    return CONFIG


@pytest.fixture
def token():
    return make_token


@pytest.fixture
def key_resolver():
    return resolve_key
