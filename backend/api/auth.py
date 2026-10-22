"""Console API authentication: Entra ID access tokens and role mapping (file 08 §2.3).

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
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

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


def authenticate(
    token: str, config: AuthConfig, resolve_key: KeyResolver, dev: DevAuth | None
) -> tuple[ConsoleUser, int]:
    """The dev identity for the dev token (when enabled), otherwise an Entra ID token."""
    if dev is not None and hmac.compare_digest(token.encode(), dev.token.encode()):
        log.warning("DEV SIGN-IN: Console request accepted as the dev identity (DCL_CONSOLE_DEV_AUTH=true)")
        user = ConsoleUser(oid="dev-sign-in", name="Dev sign-in", email="dev@localhost", roles=dev.roles)
        return user, int(time.time()) + DEV_SESSION_S
    return verify_token(token, config, resolve_key)


_bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    config: Annotated[AuthConfig, Depends(get_auth_config)],
    resolve_key: Annotated[KeyResolver, Depends(get_key_resolver)],
    dev: Annotated[DevAuth | None, Depends(get_dev_auth)],
) -> ConsoleUser:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token", {"WWW-Authenticate": "Bearer"}
        )
    try:
        user, _ = authenticate(credentials.credentials, config, resolve_key, dev)
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
