"""Console API authentication (file 08 §2.3).

Local accounts (user decision 2026-10-22, this cycle): users sign in with email and password
(argon2id) at POST /auth/login and get a short-lived HS256 JWT signed with DCL_AUTH_SECRET (TTL
DCL_AUTH_TOKEN_TTL_HOURS). Every request re-reads the account, so deactivation and role changes apply
at once. Five failed logins per minute per email answer 429. While the `users` table is empty, the
first login creates the admin from DCL_BOOTSTRAP_ADMIN_EMAIL / DCL_BOOTSTRAP_ADMIN_PASSWORD. Admins
manage accounts at /auth/users. Entra ID verification (RS256, group → role mapping) stays below for
the future and is used only for non-HS256 tokens.

Dev-only sign-in (user-approved exception, DECISIONS 2026-10-22): with DCL_ENV=dev and
DCL_CONSOLE_DEV_AUTH=true, a request whose bearer token equals DCL_CONSOLE_DEV_TOKEN signs in as a
fixed dev identity with the roles in DCL_CONSOLE_DEV_ROLES. Every use is logged as a warning; the
flag outside dev is refused (503 here, and at start-up by the settings loader).

Roles: any authenticated user of the tenant is `viewer`; members of `dcl-reviewers` are
`reviewer`; members of `dcl-admins` are `admin` (admin implies reviewer). Other routers
protect themselves with `user: Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]`
or, for any signed-in user, `user: CurrentUser`.
"""

import hmac
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from functools import cache, lru_cache
from typing import Annotated, Any, Protocol

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

ENTRA_AUTHORITY = "https://login.microsoftonline.com"
DEV_SESSION_S = 8 * 3600  # websocket lifetime of a dev sign-in
DEV_TOKEN_MIN_LENGTH = 32
CLOCK_LEEWAY_S = 60


class ConsoleRole(StrEnum):
    VIEWER = "viewer"
    REVIEWER = "reviewer"
    ADMIN = "admin"


ROLE_RANK = {ConsoleRole.VIEWER: 0, ConsoleRole.REVIEWER: 1, ConsoleRole.ADMIN: 2}


@dataclass(frozen=True)
class AuthConfig:
    tenant_id: str
    audience: str
    group_reviewers: str
    group_admins: str
    missing: tuple[str, ...] = ()  # settings not provided; verification answers 503 naming them

    @property
    def issuers(self) -> list[str]:
        # v2 tokens (accessTokenAcceptedVersion = 2, recommended) and v1 tokens.
        return [f"{ENTRA_AUTHORITY}/{self.tenant_id}/v2.0", f"https://sts.windows.net/{self.tenant_id}/"]

    @property
    def jwks_url(self) -> str:
        return f"{ENTRA_AUTHORITY}/{self.tenant_id}/discovery/v2.0/keys"


class ConsoleUser(BaseModel):
    oid: str
    name: str
    email: str
    roles: list[ConsoleRole]

    def has(self, role: ConsoleRole) -> bool:
        return any(ROLE_RANK[r] >= ROLE_RANK[role] for r in self.roles)


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


KeyResolver = Callable[[str], Any]


def get_auth_config() -> AuthConfig:
    from backend.config import get_settings

    s = get_settings()
    return auth_config_from(
        tenant_id=s.tenant_id,
        audience=s.console_api_audience,
        group_reviewers=s.console_group_reviewers,
        group_admins=s.console_group_admins,
    )


def auth_config_from(**values: str | None) -> AuthConfig:
    """A partial configuration is kept, not raised: the dev sign-in must work before Entra exists."""
    missing = tuple(name for name, value in values.items() if not value)
    return AuthConfig(**{name: value or "" for name, value in values.items()}, missing=missing)  # type: ignore[arg-type]


@dataclass(frozen=True)
class DevAuth:
    token: str
    roles: list[ConsoleRole]


def get_dev_auth() -> DevAuth | None:
    """The dev sign-in, when enabled and allowed; None otherwise. Misconfiguration answers 503."""
    from backend.config import Environment, get_settings

    s = get_settings()
    if not getattr(s, "console_dev_auth", False):
        return None
    if s.env != Environment.DEV:
        log.critical("DCL_CONSOLE_DEV_AUTH is set with DCL_ENV=%s; dev sign-in refused", s.env)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "dev sign-in is only allowed with DCL_ENV=dev"
        )
    secret = getattr(s, "console_dev_token", None)
    token = secret.get_secret_value() if secret is not None else ""
    if len(token) < DEV_TOKEN_MIN_LENGTH:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"DCL_CONSOLE_DEV_TOKEN must be at least {DEV_TOKEN_MIN_LENGTH} characters",
        )
    try:
        roles = [ConsoleRole(r.strip()) for r in getattr(s, "console_dev_roles", None) or ["viewer"]]
    except ValueError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"DCL_CONSOLE_DEV_ROLES: {exc}") from exc
    return DevAuth(token=token, roles=roles)


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def get_key_resolver(config: Annotated[AuthConfig, Depends(get_auth_config)]) -> KeyResolver:
    client = _jwks_client(config.jwks_url)
    return lambda token: client.get_signing_key_from_jwt(token).key


def roles_for_groups(groups: list[str], config: AuthConfig) -> list[ConsoleRole]:
    roles = [ConsoleRole.VIEWER]
    if config.group_reviewers in groups or config.group_admins in groups:
        roles.append(ConsoleRole.REVIEWER)
    if config.group_admins in groups:
        roles.append(ConsoleRole.ADMIN)
    return roles


def verify_token(token: str, config: AuthConfig, resolve_key: KeyResolver) -> tuple[ConsoleUser, int]:
    """Return the user and the token's expiry (epoch seconds), or raise AuthError."""
    if config.missing:
        raise AuthError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Console sign-in is not configured: missing {', '.join(config.missing)}",
        )
    try:
        key = resolve_key(token)
    except jwt.PyJWKClientConnectionError as exc:
        raise AuthError(status.HTTP_503_SERVICE_UNAVAILABLE, "identity provider keys unreachable") from exc
    except jwt.PyJWTError as exc:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "unknown signing key") from exc
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=config.audience,
            issuer=config.issuers,
            leeway=CLOCK_LEEWAY_S,
            options={"require": ["exp", "iat", "iss", "aud", "oid", "tid"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, f"invalid token: {type(exc).__name__}") from exc
    if claims["tid"] != config.tenant_id:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "token from another tenant")
    if claims.get("hasgroups") or "groups" in claims.get("_claim_names", {}):
        raise AuthError(
            status.HTTP_403_FORBIDDEN,
            "group overage: configure the Console API app to emit only groups assigned to the application",
        )
    user = ConsoleUser(
        oid=claims["oid"],
        name=claims.get("name", ""),
        email=claims.get("preferred_username") or claims.get("upn") or claims.get("email", ""),
        roles=roles_for_groups(claims.get("groups", []), config),
    )
    return user, int(claims["exp"])


# ---------------------------------------------------------------- local accounts

LOCAL_ISSUER = "dcl-console"
AUTH_SECRET_MIN_LENGTH = 32
PASSWORD_MIN_LENGTH = 12
LOGIN_FAILURES_PER_WINDOW = 5
LOGIN_WINDOW_S = 60
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@cache
def _dummy_hash() -> str:
    return _hasher.hash("not-a-real-password-used-for-timing")


def _password_matches(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _ordered(roles: list[ConsoleRole]) -> list[ConsoleRole]:
    return sorted(set(roles), key=ROLE_RANK.__getitem__)


@dataclass
class LocalUser:
    """A row of S1's `users` table (migration 0010)."""

    user_id: uuid.UUID
    email: str
    display_name: str
    password_hash: str
    roles: list[ConsoleRole]
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_login_at: datetime | None = None

    def console_user(self) -> ConsoleUser:
        return ConsoleUser(oid=str(self.user_id), name=self.display_name, email=self.email, roles=self.roles)


class DuplicateEmail(Exception):
    pass


class UserStore(Protocol):
    def count(self) -> int: ...
    def get(self, user_id: uuid.UUID) -> LocalUser | None: ...
    def by_email(self, email: str) -> LocalUser | None: ...
    def list(self) -> list[LocalUser]: ...
    def create(self, user: LocalUser) -> LocalUser: ...
    def save(self, user: LocalUser) -> LocalUser: ...


class SqlUserStore:
    """The only code that queries `users`; S1 owns the model (backend.postgres.models.User)."""

    def __init__(self, session_factory: Callable[[], Any]):
        self._sessions = session_factory

    @staticmethod
    def _model():
        from backend.postgres.models import User  # published with migration 0010

        return User

    @staticmethod
    def _user(row: Any) -> LocalUser:
        return LocalUser(
            user_id=row.user_id,
            email=row.email,
            display_name=row.display_name,
            password_hash=row.password_hash,
            roles=_ordered([ConsoleRole(r) for r in row.roles]),
            is_active=row.is_active,
            created_at=row.created_at,
            last_login_at=row.last_login_at,
        )

    def count(self) -> int:
        from sqlalchemy import func, select

        with self._sessions() as session:
            return session.scalar(select(func.count()).select_from(self._model())) or 0

    def get(self, user_id: uuid.UUID) -> LocalUser | None:
        with self._sessions() as session:
            row = session.get(self._model(), user_id)
            return self._user(row) if row else None

    def by_email(self, email: str) -> LocalUser | None:
        from sqlalchemy import select

        model = self._model()
        with self._sessions() as session:
            row = session.scalar(select(model).where(model.email == email))
            return self._user(row) if row else None

    def list(self) -> list[LocalUser]:
        from sqlalchemy import select

        model = self._model()
        with self._sessions() as session:
            return [self._user(r) for r in session.scalars(select(model).order_by(model.email))]

    def create(self, user: LocalUser) -> LocalUser:
        from sqlalchemy.exc import IntegrityError

        model = self._model()
        with self._sessions() as session:
            row = model(
                user_id=user.user_id,
                email=user.email,
                display_name=user.display_name,
                password_hash=user.password_hash,
                roles=[str(r) for r in user.roles],
                is_active=user.is_active,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                raise DuplicateEmail(user.email) from exc
            session.refresh(row)
            return self._user(row)

    def save(self, user: LocalUser) -> LocalUser:
        with self._sessions() as session:
            row = session.get(self._model(), user.user_id)
            row.display_name = user.display_name
            row.password_hash = user.password_hash
            row.roles = [str(r) for r in user.roles]
            row.is_active = user.is_active
            row.last_login_at = user.last_login_at
            session.commit()
            return self._user(row)


class LoginLimiter:
    """Failed logins per email in a sliding window; in memory, per API process."""

    def __init__(self, limit: int = LOGIN_FAILURES_PER_WINDOW, window_s: int = LOGIN_WINDOW_S):
        self.limit, self.window_s = limit, window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def retry_after(self, email: str, now: float) -> int | None:
        with self._lock:
            failures = self._failures[email]
            while failures and failures[0] <= now - self.window_s:
                failures.popleft()
            if len(failures) < self.limit:
                return None
            return max(1, int(failures[0] + self.window_s - now + 1))

    def failed(self, email: str, now: float) -> None:
        with self._lock:
            self._failures[email].append(now)

    def succeeded(self, email: str) -> None:
        with self._lock:
            self._failures.pop(email, None)


@dataclass
class LocalAuth:
    secret: str
    ttl_s: int
    store: UserStore
    limiter: LoginLimiter
    bootstrap: tuple[str, str] | None = None  # (email, password) for the first admin


@cache
def _sql_store() -> SqlUserStore:
    from backend.postgres.session import default_session_factory

    return SqlUserStore(default_session_factory())


_limiter = LoginLimiter()


def get_local_auth() -> LocalAuth | None:
    """Local sign-in when DCL_AUTH_SECRET is set; None otherwise (login then answers 503)."""
    from backend.config import get_settings

    s = get_settings()
    configured = getattr(s, "auth_secret", None)
    secret = configured.get_secret_value() if configured else ""
    if not secret:
        return None
    if len(secret) < AUTH_SECRET_MIN_LENGTH:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"DCL_AUTH_SECRET must be at least {AUTH_SECRET_MIN_LENGTH} characters",
        )
    bootstrap = None
    email, password = getattr(s, "bootstrap_admin_email", None), getattr(s, "bootstrap_admin_password", None)
    if email and password:
        bootstrap = (email, password.get_secret_value())
    return LocalAuth(
        secret=secret,
        ttl_s=getattr(s, "auth_token_ttl_hours", 12) * 3600,
        store=_sql_store(),
        limiter=_limiter,
        bootstrap=bootstrap,
    )


def issue_token(user: LocalUser, local: LocalAuth, now: int | None = None) -> tuple[str, int]:
    now = int(time.time()) if now is None else now
    expires_at = now + local.ttl_s
    claims = {
        "iss": LOCAL_ISSUER,
        "aud": LOCAL_ISSUER,
        "sub": str(user.user_id),
        "email": user.email,
        "name": user.display_name,
        "roles": [str(r) for r in user.roles],
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(claims, local.secret, algorithm="HS256"), expires_at


def _is_local_token(token: str) -> bool:
    try:
        return jwt.get_unverified_header(token).get("alg") == "HS256"
    except jwt.PyJWTError:
        return False


def verify_local_token(token: str, local: LocalAuth) -> tuple[ConsoleUser, int]:
    """The account behind a local token, re-read from the store: roles and is_active are current."""
    try:
        claims = jwt.decode(
            token,
            local.secret,
            algorithms=["HS256"],
            audience=LOCAL_ISSUER,
            issuer=LOCAL_ISSUER,
            leeway=CLOCK_LEEWAY_S,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        user_id = uuid.UUID(claims["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "token expired") from exc
    except (jwt.PyJWTError, ValueError) as exc:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, f"invalid token: {type(exc).__name__}") from exc
    user = local.store.get(user_id)
    if user is None or not user.is_active:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "account disabled")
    return user.console_user(), int(claims["exp"])


def ensure_bootstrap_admin(local: LocalAuth) -> None:
    """Create the first admin from the bootstrap settings, only while there are no accounts."""
    if local.bootstrap is None or local.store.count() > 0:
        return
    email, password = local.bootstrap
    if len(password) < PASSWORD_MIN_LENGTH:
        log.error(
            "DCL_BOOTSTRAP_ADMIN_PASSWORD is shorter than %d characters; no admin created",
            PASSWORD_MIN_LENGTH,
        )
        return
    try:
        local.store.create(
            LocalUser(
                user_id=uuid.uuid4(),
                email=email.strip().lower(),
                display_name="Administrator",
                password_hash=hash_password(password),
                roles=list(ConsoleRole),
            )
        )
    except DuplicateEmail:
        return  # another request created it first
    log.warning("bootstrap admin %s created (users table was empty)", email)


def authenticate(
    token: str,
    config: AuthConfig,
    resolve_key: KeyResolver,
    dev: DevAuth | None,
    local: LocalAuth | None = None,
) -> tuple[ConsoleUser, int]:
    """The dev identity for the dev token (when enabled), a local account for HS256, else Entra ID."""
    if dev is not None and hmac.compare_digest(token.encode(), dev.token.encode()):
        log.warning("DEV SIGN-IN: Console request accepted as the dev identity (DCL_CONSOLE_DEV_AUTH=true)")
        user = ConsoleUser(oid="dev-sign-in", name="Dev sign-in", email="dev@localhost", roles=dev.roles)
        return user, int(time.time()) + DEV_SESSION_S
    if _is_local_token(token):
        if local is None:
            raise AuthError(
                status.HTTP_503_SERVICE_UNAVAILABLE, "local sign-in is not configured: DCL_AUTH_SECRET"
            )
        return verify_local_token(token, local)
    return verify_token(token, config, resolve_key)


_bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    config: Annotated[AuthConfig, Depends(get_auth_config)],
    resolve_key: Annotated[KeyResolver, Depends(get_key_resolver)],
    dev: Annotated[DevAuth | None, Depends(get_dev_auth)],
    local: Annotated[LocalAuth | None, Depends(get_local_auth)],
) -> ConsoleUser:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token", {"WWW-Authenticate": "Bearer"}
        )
    try:
        user, _ = authenticate(credentials.credentials, config, resolve_key, dev, local)
    except AuthError as exc:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        raise HTTPException(exc.status_code, exc.detail, headers) from exc
    return user


CurrentUser = Annotated[ConsoleUser, Depends(current_user)]


def require_role(role: ConsoleRole) -> Callable[..., ConsoleUser]:
    def dependency(user: CurrentUser) -> ConsoleUser:
        if not user.has(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role {role}")
        return user

    return dependency


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(user: CurrentUser) -> ConsoleUser:
    return user


# ---------------------------------------------------------------- local sign-in and accounts

LocalAuthDep = Annotated[LocalAuth | None, Depends(get_local_auth)]
Admin = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.ADMIN))]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (OAuth token type, not a secret)
    expires_at: datetime
    user: ConsoleUser


class UserView(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    roles: list[ConsoleRole]
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    roles: list[ConsoleRole] = Field(min_length=1)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=1024)


class UserUpdate(BaseModel):
    """Only the fields present change; `password` is an admin reset."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    roles: list[ConsoleRole] | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=PASSWORD_MIN_LENGTH, max_length=1024)


def _view(user: LocalUser) -> UserView:
    return UserView(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        roles=user.roles,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _require_local(local: LocalAuth | None) -> LocalAuth:
    if local is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "local sign-in is not configured: DCL_AUTH_SECRET"
        )
    return local


@router.post("/login")
def login(body: LoginRequest, local: LocalAuthDep, response: Response) -> LoginResponse:
    local = _require_local(local)
    email = body.email.strip().lower()
    now = time.time()
    retry_after = local.limiter.retry_after(email, now)
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed sign-ins; try again shortly",
            {"Retry-After": str(retry_after)},
        )
    ensure_bootstrap_admin(local)
    user = local.store.by_email(email)
    if user is None or not user.is_active:
        _password_matches(_dummy_hash(), body.password)  # same work whether or not the account exists
        ok = False
    else:
        ok = _password_matches(user.password_hash, body.password)
    if not ok or user is None:
        local.limiter.failed(email, now)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong email or password")
    local.limiter.succeeded(email)
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user = local.store.save(replace(user, last_login_at=datetime.now(UTC)))
    token, expires_at = issue_token(user, local)
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(
        access_token=token, expires_at=datetime.fromtimestamp(expires_at, UTC), user=user.console_user()
    )


@router.get("/users")
def list_users(_: Admin, local: LocalAuthDep) -> list[UserView]:
    return [_view(u) for u in _require_local(local).store.list()]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, admin: Admin, local: LocalAuthDep) -> UserView:
    local = _require_local(local)
    user = LocalUser(
        user_id=uuid.uuid4(),
        email=body.email.strip().lower(),
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
        roles=_ordered(body.roles),
    )
    try:
        created = local.store.create(user)
    except DuplicateEmail as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"an account for {user.email} exists") from exc
    log.info("user %s created with roles %s by %s", created.email, created.roles, admin.email)
    return _view(created)


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserUpdate, admin: Admin, local: LocalAuthDep) -> UserView:
    local = _require_local(local)
    user = local.store.get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no user {user_id}")
    changed = replace(
        user,
        display_name=body.display_name.strip() if body.display_name is not None else user.display_name,
        roles=_ordered(body.roles) if body.roles is not None else user.roles,
        is_active=body.is_active if body.is_active is not None else user.is_active,
        password_hash=hash_password(body.password) if body.password is not None else user.password_hash,
    )
    was_admin = user.is_active and ConsoleRole.ADMIN in user.roles
    stays_admin = changed.is_active and ConsoleRole.ADMIN in changed.roles
    if was_admin and not stays_admin:
        other_admins = [
            u
            for u in local.store.list()
            if u.user_id != user_id and u.is_active and ConsoleRole.ADMIN in u.roles
        ]
        if not other_admins:
            raise HTTPException(status.HTTP_409_CONFLICT, "keep at least one active admin")
    saved = local.store.save(changed)
    fields = sorted(body.model_dump(exclude_none=True).keys() - {"password"}) + (
        ["password"] if body.password else []
    )
    log.info("user %s updated (%s) by %s", saved.email, ", ".join(fields), admin.email)
    return _view(saved)
