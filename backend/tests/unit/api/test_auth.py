from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.api import auth
from backend.api.auth import ConsoleRole, ConsoleUser, require_role

REVIEWERS = "group-reviewers"
ADMINS = "group-admins"


@pytest.fixture
def client(auth_config, key_resolver):
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/reviewer-only")
    def reviewer_only(user: Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]):
        return {"oid": user.oid}

    @app.get("/admin-only")
    def admin_only(user: Annotated[ConsoleUser, Depends(require_role(ConsoleRole.ADMIN))]):
        return {"oid": user.oid}

    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    return TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("groups", "roles"),
    [
        ([], ["viewer"]),
        (["unrelated"], ["viewer"]),
        ([REVIEWERS], ["viewer", "reviewer"]),
        ([ADMINS], ["viewer", "reviewer", "admin"]),
        ([REVIEWERS, ADMINS], ["viewer", "reviewer", "admin"]),
    ],
)
def test_me_maps_groups_to_roles(client, token, groups, roles):
    response = client.get("/auth/me", headers=bearer(token(groups=groups)))
    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == roles
    assert body["email"] == "engineer@manastuspace.com"


def test_v1_issuer_is_accepted(client, token):
    token = token(iss=f"https://sts.windows.net/{'11111111-1111-1111-1111-111111111111'}/")
    assert client.get("/auth/me", headers=bearer(token)).status_code == 200


def test_missing_token_is_401_with_challenge(client, token):
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"aud": "api://someone-else"}, "invalid token: InvalidAudienceError"),
        ({"iss": "https://login.microsoftonline.com/other/v2.0"}, "invalid token: InvalidIssuerError"),
        ({"lifetime_s": -3600}, "token expired"),
        ({"oid": None}, "invalid token: MissingRequiredClaimError"),
        ({"tid": "22222222-2222-2222-2222-222222222222"}, "token from another tenant"),
    ],
)
def test_bad_tokens_are_401(client, token, overrides, detail):
    response = client.get("/auth/me", headers=bearer(token(**overrides)))
    assert response.status_code == 401
    assert response.json()["detail"] == detail


def test_wrong_signature_is_401(client, token, other_key):
    response = client.get("/auth/me", headers=bearer(token(signed_by=other_key)))
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid token: InvalidSignatureError"


def test_group_overage_is_refused(client, token):
    token = token(_claim_names={"groups": "src1"}, _claim_sources={"src1": {"endpoint": "x"}})
    response = client.get("/auth/me", headers=bearer(token))
    assert response.status_code == 403
    assert response.json()["detail"].startswith("group overage")


@pytest.mark.parametrize(
    ("path", "groups", "expected"),
    [
        ("/reviewer-only", [], 403),
        ("/reviewer-only", [REVIEWERS], 200),
        ("/reviewer-only", [ADMINS], 200),
        ("/admin-only", [REVIEWERS], 403),
        ("/admin-only", [ADMINS], 200),
    ],
)
def test_require_role(client, token, path, groups, expected):
    assert client.get(path, headers=bearer(token(groups=groups))).status_code == expected


def test_require_role_without_token_is_401(client, token):
    assert client.get("/admin-only").status_code == 401
