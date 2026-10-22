import time
import uuid
from dataclasses import replace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import auth
from backend.api.auth import ConsoleRole, DuplicateEmail, LocalAuth, LocalUser, LoginLimiter

SECRET = "s" * 40
PASSWORD = "correct horse battery"
ALL_ROLES = [ConsoleRole.VIEWER, ConsoleRole.REVIEWER, ConsoleRole.ADMIN]


class MemoryStore:
    def __init__(self):
        self.users: dict[uuid.UUID, LocalUser] = {}
        self.audit: list[tuple[str, str, str, dict | None, dict]] = []

    def count(self):
        return len(self.users)

    def get(self, user_id):
        return self.users.get(user_id)

    def by_email(self, email):
        return next((u for u in self.users.values() if u.email == email), None)

    def list(self):
        return sorted(self.users.values(), key=lambda u: u.email)

    def create(self, user, actor="test"):
        if self.by_email(user.email):
            raise DuplicateEmail(user.email)
        self.users[user.user_id] = user
        self.audit.append((actor, user.email, "create", None, user.audit_view()))
        return user

    def save(self, user, actor="test", action="update", before=None, after=None):
        self.users[user.user_id] = user
        self.audit.append((actor, user.email, action, before, after))
        return user

    def record_login(self, user_id, at, password_hash=None):
        user = self.users[user_id]
        self.users[user_id] = replace(
            user, last_login_at=at, password_hash=password_hash or user.password_hash
        )


def account(email, roles, password=PASSWORD, active=True):
    return LocalUser(
        user_id=uuid.uuid4(),
        email=email,
        display_name=email.split("@")[0],
        password_hash=auth.hash_password(password),
        roles=roles,
        is_active=active,
    )


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def local(store):
    return LocalAuth(secret=SECRET, ttl_s=12 * 3600, store=store, limiter=LoginLimiter())


@pytest.fixture
def client(local, auth_config, key_resolver):
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[auth.get_local_auth] = lambda: local
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    return TestClient(app)


def sign_in(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_returns_a_token_that_signs_in_with_the_stored_roles(client, store):
    store.create(account("asha@manastuspace.com", [ConsoleRole.VIEWER, ConsoleRole.REVIEWER]))
    response = sign_in(client, "  Asha@ManastuSpace.com ")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"], audience="dcl-console")
    assert claims["exp"] - claims["iat"] == 12 * 3600
    assert claims["email"] == "asha@manastuspace.com"
    me = client.get("/auth/me", headers=bearer(response)).json()
    assert me["email"] == "asha@manastuspace.com" and me["roles"] == ["viewer", "reviewer"]
    assert store.by_email("asha@manastuspace.com").last_login_at is not None


def test_wrong_password_unknown_and_inactive_accounts_get_the_same_answer(client, store):
    store.create(account("asha@manastuspace.com", [ConsoleRole.VIEWER]))
    store.create(account("gone@manastuspace.com", [ConsoleRole.VIEWER], active=False))
    answers = [
        sign_in(client, "asha@manastuspace.com", "wrong password!!"),
        sign_in(client, "nobody@manastuspace.com"),
        sign_in(client, "gone@manastuspace.com"),
    ]
    assert [(r.status_code, r.json()) for r in answers] == [(401, {"detail": "wrong email or password"})] * 3


def test_sixth_failure_in_a_minute_is_refused_until_the_window_passes(client, store, local):
    store.create(account("asha@manastuspace.com", [ConsoleRole.VIEWER]))
    codes = [sign_in(client, "asha@manastuspace.com", "bad password 123").status_code for _ in range(5)]
    blocked = sign_in(client, "asha@manastuspace.com")  # even the right password waits
    assert codes == [401] * 5 and blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 61
    assert sign_in(client, "other@manastuspace.com", "x").status_code == 401  # per email
    assert local.limiter.retry_after("asha@manastuspace.com", time.time() + 61) is None


def test_deactivation_and_role_changes_apply_to_existing_tokens(client, store):
    user = store.create(account("asha@manastuspace.com", [ConsoleRole.VIEWER, ConsoleRole.REVIEWER]))
    headers = bearer(sign_in(client, "asha@manastuspace.com"))
    store.save(replace(user, roles=[ConsoleRole.VIEWER]))
    assert client.get("/auth/me", headers=headers).json()["roles"] == ["viewer"]
    store.save(replace(user, is_active=False))
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401 and response.json() == {"detail": "account disabled"}


def test_tampered_and_expired_tokens_are_refused(client, store, local):
    user = store.create(account("asha@manastuspace.com", [ConsoleRole.ADMIN]))
    expired, _ = auth.issue_token(user, local, now=int(time.time()) - 13 * 3600)
    forged = jwt.encode(
        {"iss": "dcl-console", "aud": "dcl-console", "sub": str(user.user_id), "iat": 1, "exp": 4102444800},
        "another secret of sufficient length 123",
        algorithm="HS256",
    )
    for token, detail in [(expired, "token expired"), (forged, "invalid token: InvalidSignatureError")]:
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert (response.status_code, response.json()["detail"]) == (401, detail)


def test_first_login_creates_the_bootstrap_admin_only_while_there_are_no_accounts(client, store, local):
    local.bootstrap = ("Admin@ManastuSpace.com", "bootstrap password 1")
    assert sign_in(client, "admin@manastuspace.com", "bootstrap password 1").json()["user"]["roles"] == [
        "viewer",
        "reviewer",
        "admin",
    ]
    local.bootstrap = ("second@manastuspace.com", "bootstrap password 2")
    assert sign_in(client, "second@manastuspace.com", "bootstrap password 2").status_code == 401
    assert [u.email for u in store.list()] == ["admin@manastuspace.com"]


def test_user_admin_is_admin_only(client, store):
    store.create(account("rev@manastuspace.com", [ConsoleRole.VIEWER, ConsoleRole.REVIEWER]))
    headers = bearer(sign_in(client, "rev@manastuspace.com"))
    assert client.get("/auth/users").status_code == 401
    assert client.get("/auth/users", headers=headers).status_code == 403
    assert client.post("/auth/users", headers=headers, json={}).status_code == 403


def test_admin_creates_changes_deactivates_and_resets(client, store):
    store.create(account("admin@manastuspace.com", ALL_ROLES))
    headers = bearer(sign_in(client, "admin@manastuspace.com"))
    created = client.post(
        "/auth/users",
        headers=headers,
        json={
            "email": "New@ManastuSpace.com",
            "display_name": "New",
            "roles": ["reviewer", "viewer"],
            "password": "first password 1",
        },
    )
    assert created.status_code == 201
    new = created.json()
    assert (new["email"], new["roles"], new["is_active"]) == (
        "new@manastuspace.com",
        ["viewer", "reviewer"],
        True,
    )
    duplicate = client.post(
        "/auth/users",
        headers=headers,
        json={
            "email": "new@manastuspace.com",
            "display_name": "N",
            "roles": ["viewer"],
            "password": "first password 1",
        },
    )
    assert duplicate.status_code == 409
    short = client.post(
        "/auth/users",
        headers=headers,
        json={"email": "x@y.z", "display_name": "X", "roles": ["viewer"], "password": "short"},
    )
    assert short.status_code == 422

    path = f"/auth/users/{new['user_id']}"
    assert client.patch(path, headers=headers, json={"roles": ["viewer"]}).json()["roles"] == ["viewer"]
    assert client.patch(path, headers=headers, json={"password": "second password 2"}).status_code == 200
    assert sign_in(client, "new@manastuspace.com", "first password 1").status_code == 401
    assert sign_in(client, "new@manastuspace.com", "second password 2").status_code == 200
    assert client.patch(path, headers=headers, json={"is_active": False}).json()["is_active"] is False
    assert sign_in(client, "new@manastuspace.com", "second password 2").status_code == 401
    assert client.patch(path, headers=headers, json={"email": "other@x.y"}).status_code == 422
    assert (
        client.patch(f"/auth/users/{uuid.uuid4()}", headers=headers, json={"is_active": False}).status_code
        == 404
    )
    listed = client.get("/auth/users", headers=headers).json()
    assert [(u["email"], u["is_active"]) for u in listed] == [
        ("admin@manastuspace.com", True),
        ("new@manastuspace.com", False),
    ]
    assert all("password_hash" not in u for u in listed)


def test_the_last_active_admin_cannot_be_removed(client, store):
    admin = store.create(account("admin@manastuspace.com", ALL_ROLES))
    headers = bearer(sign_in(client, "admin@manastuspace.com"))
    path = f"/auth/users/{admin.user_id}"
    for change in ({"is_active": False}, {"roles": ["viewer"]}):
        response = client.patch(path, headers=headers, json=change)
        assert (response.status_code, response.json()) == (409, {"detail": "keep at least one active admin"})
    store.create(account("second@manastuspace.com", ALL_ROLES))
    assert client.patch(path, headers=headers, json={"roles": ["viewer"]}).status_code == 200


def test_login_without_a_secret_is_503(local, auth_config, key_resolver):
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[auth.get_local_auth] = lambda: None
    response = TestClient(app).post("/auth/login", json={"email": "a@b.c", "password": "x"})
    assert response.status_code == 503


def test_account_changes_are_audited_with_before_after_and_the_admin(client, store):
    store.create(account("admin@manastuspace.com", ALL_ROLES))
    headers = bearer(sign_in(client, "admin@manastuspace.com"))
    store.audit.clear()
    new = client.post(
        "/auth/users",
        headers=headers,
        json={
            "email": "a@manastuspace.com",
            "display_name": "A",
            "roles": ["viewer"],
            "password": "first password 1",
        },
    ).json()
    path = f"/auth/users/{new['user_id']}"
    client.patch(
        path, headers=headers, json={"roles": ["viewer", "reviewer"], "password": "second password 2"}
    )
    client.patch(path, headers=headers, json={"is_active": False})
    client.patch(path, headers=headers, json={"is_active": True})
    sign_in(client, "a@manastuspace.com", "second password 2")  # sign-ins are not audited
    view = {"email": "a@manastuspace.com", "display_name": "A", "roles": ["viewer"], "is_active": True}
    reviewer = {**view, "roles": ["viewer", "reviewer"]}
    assert store.audit == [
        ("admin@manastuspace.com", "a@manastuspace.com", "create", None, view),
        (
            "admin@manastuspace.com",
            "a@manastuspace.com",
            "update",
            view,
            {**reviewer, "password_reset": True},
        ),
        (
            "admin@manastuspace.com",
            "a@manastuspace.com",
            "deactivate",
            reviewer,
            {**reviewer, "is_active": False},
        ),
        (
            "admin@manastuspace.com",
            "a@manastuspace.com",
            "reactivate",
            {**reviewer, "is_active": False},
            reviewer,
        ),
    ]
    assert all("password_hash" not in str(entry) for entry in store.audit)
