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


def test_partial_configuration_is_a_clear_503(token, key_resolver):
    partial = auth.auth_config_from(tenant_id="t", audience=None, group_reviewers="r", group_admins="")
    assert partial.missing == ("audience", "group_admins")
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: partial
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    app.dependency_overrides[auth.get_dev_auth] = lambda: None
    response = TestClient(app).get("/auth/me", headers={"Authorization": f"Bearer {token()}"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Console sign-in is not configured: missing audience, group_admins"


# ---------------------------------------------------------------- dev-only sign-in

DEV_TOKEN = "d" * 40


def dev_settings(monkeypatch, *, env="dev", flag=True, token=DEV_TOKEN, roles=("viewer", "reviewer")):
    from types import SimpleNamespace

    from pydantic import SecretStr

    from backend.config import Environment

    settings = SimpleNamespace(
        env=Environment(env),
        console_dev_auth=flag,
        console_dev_token=SecretStr(token) if token is not None else None,
        console_dev_roles=list(roles),
    )
    monkeypatch.setattr("backend.config.get_settings", lambda: settings)


@pytest.fixture
def unconfigured_client(key_resolver):
    """Entra not registered yet: only the dev sign-in can work."""
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/reviewer-only")
    def reviewer_only(user: Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]):
        return {"oid": user.oid}

    app.dependency_overrides[auth.get_auth_config] = lambda: auth.auth_config_from(
        tenant_id=None, audience=None, group_reviewers=None, group_admins=None
    )
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    return TestClient(app)


def test_dev_token_signs_in_with_configured_roles_and_logs(unconfigured_client, monkeypatch, caplog):
    dev_settings(monkeypatch)
    with caplog.at_level("WARNING", logger="backend.api.auth"):
        response = unconfigured_client.get("/auth/me", headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    assert response.status_code == 200
    assert response.json() == {
        "oid": "dev-sign-in",
        "name": "Dev sign-in",
        "email": "dev@localhost",
        "roles": ["viewer", "reviewer"],
    }
    assert "DEV SIGN-IN" in caplog.text
    ok = unconfigured_client.get("/reviewer-only", headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    assert ok.status_code == 200


def test_other_tokens_still_need_entra(unconfigured_client, monkeypatch):
    dev_settings(monkeypatch)
    wrong = unconfigured_client.get("/auth/me", headers={"Authorization": "Bearer " + "x" * 40})
    assert wrong.status_code == 503 and wrong.json()["detail"].startswith("Console sign-in is not configured")
    assert unconfigured_client.get("/auth/me").status_code == 401


def test_flag_off_means_no_dev_path(unconfigured_client, monkeypatch):
    dev_settings(monkeypatch, flag=False)
    response = unconfigured_client.get("/auth/me", headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    assert response.status_code == 503  # falls through to Entra, which is not configured


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        ({"env": "staging"}, "dev sign-in is only allowed with DCL_ENV=dev"),
        ({"env": "prod"}, "dev sign-in is only allowed with DCL_ENV=dev"),
        ({"token": "short"}, "DCL_CONSOLE_DEV_TOKEN must be at least 32 characters"),
        ({"token": None}, "DCL_CONSOLE_DEV_TOKEN must be at least 32 characters"),
        ({"roles": ("viewer", "superuser")}, "DCL_CONSOLE_DEV_ROLES: 'superuser' is not a valid ConsoleRole"),
    ],
)
def test_dev_misconfiguration_is_refused(unconfigured_client, monkeypatch, caplog, kwargs, detail):
    dev_settings(monkeypatch, **kwargs)
    with caplog.at_level("CRITICAL", logger="backend.api.auth"):
        response = unconfigured_client.get("/auth/me", headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    assert response.status_code == 503 and response.json()["detail"] == detail
    if "env" in kwargs:
        assert "dev sign-in refused" in caplog.text
