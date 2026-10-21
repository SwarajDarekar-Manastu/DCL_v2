"""Console API authentication: Entra ID access tokens and role mapping (file 08 §2.3).

Roles: any authenticated user of the tenant is `viewer`; members of `dcl-reviewers` are
`reviewer`; members of `dcl-admins` are `admin` (admin implies reviewer). Other routers
protect themselves with `Depends(require_role(Role.REVIEWER))`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

ENTRA_AUTHORITY = "https://login.microsoftonline.com"
CLOCK_LEEWAY_S = 60


class Role(StrEnum):
    VIEWER = "viewer"
    REVIEWER = "reviewer"
    ADMIN = "admin"


ROLE_RANK = {Role.VIEWER: 0, Role.REVIEWER: 1, Role.ADMIN: 2}


@dataclass(frozen=True)
class AuthConfig:
    tenant_id: str
    audience: str
    group_reviewers: str
    group_admins: str

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
    roles: list[Role]

    def has(self, role: Role) -> bool:
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
    return AuthConfig(
        tenant_id=s.tenant_id,
        audience=s.console_api_audience,
        group_reviewers=s.console_group_reviewers,
        group_admins=s.console_group_admins,
    )


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def get_key_resolver(config: AuthConfig = Depends(get_auth_config)) -> KeyResolver:
    client = _jwks_client(config.jwks_url)
    return lambda token: client.get_signing_key_from_jwt(token).key


def roles_for_groups(groups: list[str], config: AuthConfig) -> list[Role]:
    roles = [Role.VIEWER]
    if config.group_reviewers in groups or config.group_admins in groups:
        roles.append(Role.REVIEWER)
    if config.group_admins in groups:
        roles.append(Role.ADMIN)
    return roles


def verify_token(token: str, config: AuthConfig, resolve_key: KeyResolver) -> tuple[ConsoleUser, int]:
    """Return the user and the token's expiry (epoch seconds), or raise AuthError."""
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


_bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    config: AuthConfig = Depends(get_auth_config),
    resolve_key: KeyResolver = Depends(get_key_resolver),
) -> ConsoleUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token", {"WWW-Authenticate": "Bearer"})
    try:
        user, _ = verify_token(credentials.credentials, config, resolve_key)
    except AuthError as exc:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        raise HTTPException(exc.status_code, exc.detail, headers) from exc
    return user


def require_role(role: Role) -> Callable[..., ConsoleUser]:
    def dependency(user: ConsoleUser = Depends(current_user)) -> ConsoleUser:
        if not user.has(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role {role}")
        return user

    return dependency


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(user: ConsoleUser = Depends(current_user)) -> ConsoleUser:
    return user
