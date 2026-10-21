"""Environment contract of docs/architecture/01 §7.1: secrets and endpoints come from the environment only.

Every process calls get_settings() at startup. Load-time refusals apply to every process; values a component
needs are checked by Settings.require() when that component starts, so a container never dies for a value
it does not use. Dev defaults apply only when DCL_ENV=dev. Messages name variables, never values.
"""

import base64
import binascii
import logging
import os
import re
from collections.abc import Mapping
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from dotenv import dotenv_values
from pydantic import (
    AliasChoices,
    AnyHttpUrl,
    Field,
    PositiveInt,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

log = logging.getLogger(__name__)

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
FORBIDDEN_NAMES = ("GOOGLE_API_KEY",)
GATEWAY_KEY_NAMES = ("GEMINI_GATEWAY_KEY", "DCL_GEMINI_API_KEY")
DEVELOPER_KEY_PREFIX = "AIza"
STACK_DATABASE_HOST = "postgres:5432"
STACK_DATABASE_NAME = "dcl_v2"
PLACEHOLDER = re.compile(
    r"^\s*(<.*>|\$\{.*\}|\.\.\.|x{3,}|changeme|change[-_]me|replace[-_]?me|todo|tbd|placeholder"
    r"|your[-_ ].*|fill[-_ ]?me|fill[-_ ]?in|none|null)\s*$",
    re.IGNORECASE,
)
COMMA_LISTS = ("DCL_FOLDER_IDS", "DCL_FOLDER_PATHS", "DCL_CONSOLE_ALLOWED_ORIGINS")
DEV_DEFAULTS: dict[str, str] = {
    "DCL_REDIS_URL": "redis://redis:6379/0",
    "DCL_MINIO_ENDPOINT": "http://minio:9000",
    "DCL_MODELS_URL": "http://models:8500",
    "DCL_OFFICE_URL": "http://libreoffice:2003",
    "DCL_API_BASE_URL": "http://localhost:8200",
    "DCL_CONSOLE_BASE_URL": "http://localhost:8100",
    "DCL_CONSOLE_ALLOWED_ORIGINS": "http://localhost:8100",
}


class ConfigError(RuntimeError):
    pass


class Environment(StrEnum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class Role(StrEnum):
    API = "api"
    MODELS = "models"
    ALL = "all"


class PermissionOption(StrEnum):
    A = "A"
    B = "B"


class ThinkingLevel(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApiStyle(StrEnum):
    MANASTU = "manastu"
    GEMINI = "gemini"
    OPENAI = "openai"


class Group(StrEnum):
    GRAPH = "graph"
    GEMINI = "gemini"
    ALERTS = "alerts"
    DATABASE = "database"
    REDIS = "redis"
    MINIO = "minio"
    MODELS = "models"
    OFFICE = "office"
    LINKS = "links"
    CONSOLE_AUTH = "console_auth"
    PIPE = "pipe"


CommaList = Annotated[list[str], NoDecode]
Port = Annotated[int, Field(gt=0, lt=65536)]


def _env(*names: str, **kwargs):
    alias = names[0] if len(names) == 1 else AliasChoices(*names)
    return Field(validation_alias=alias, **kwargs)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore", frozen=True, env_ignore_empty=True, populate_by_name=False
    )

    env: Environment = _env("DCL_ENV", default=Environment.DEV)
    role: Role | None = _env("DCL_ROLE", "ROLE", default=None)

    tenant_id: str | None = _env("DCL_TENANT_ID", default=None)
    client_id: str | None = _env("DCL_CLIENT_ID", default=None)
    auth_mode: Literal["delegated"] | None = _env("DCL_AUTH_MODE", default=None)
    delegated_username: str | None = _env("DCL_DELEGATED_USERNAME", default=None)
    permission_option: PermissionOption | None = _env("DCL_PERMISSION_OPTION", default=None)
    token_cache_path: Path | None = _env("DCL_TOKEN_CACHE_PATH", default=None)
    token_dir: Path | None = _env("DCL_TOKEN_DIR", default=None)
    token_cache_key: SecretStr | None = _env("DCL_TOKEN_CACHE_KEY", default=None)

    drive_id: str | None = _env("DCL_DRIVE_ID", default=None)
    folder_ids: CommaList = _env("DCL_FOLDER_IDS", default_factory=list)
    folder_paths: CommaList = _env("DCL_FOLDER_PATHS", default_factory=list)
    test_outside_item_id: str | None = _env("DCL_TEST_OUTSIDE_ITEM_ID", default=None)
    test_outside_drive_id: str | None = _env("DCL_TEST_OUTSIDE_DRIVE_ID", default=None)

    secret_store: str | None = _env("DCL_SECRET_STORE", default=None)
    certificate_path: Path | None = _env("DCL_CERTIFICATE_PATH", default=None)
    certificate_thumbprint: SecretStr | None = _env("DCL_CERTIFICATE_THUMBPRINT", default=None)

    gemini_backend: Literal["gateway"] | None = _env("GEMINI_BACKEND", default=None)
    gemini_gateway_url: AnyHttpUrl | None = _env("GEMINI_GATEWAY_URL", default=None)
    gemini_gateway_key: SecretStr | None = _env(*GATEWAY_KEY_NAMES, default=None)
    gemini_api_style: ApiStyle = _env("GEMINI_API_STYLE", default=ApiStyle.MANASTU)
    gemini_thinking_level: ThinkingLevel | None = _env("GEMINI_THINKING_LEVEL", default=None)
    gemini_include_thoughts: bool = _env("GEMINI_INCLUDE_THOUGHTS", default=False)
    gemini_context_cache: bool = _env("GEMINI_CONTEXT_CACHE", default=False)
    gemini_cache_ttl_s: PositiveInt | None = _env("GEMINI_CACHE_TTL_S", default=None)
    google_cloud_project: str | None = _env("GOOGLE_CLOUD_PROJECT", default=None)
    google_cloud_location: str | None = _env("GOOGLE_CLOUD_LOCATION", default=None)

    alert_webhook_url: SecretStr | None = _env("DCL_ALERT_WEBHOOK_URL", default=None)

    db_user: str | None = _env("DCL_DB_USER", default=None)
    db_password: SecretStr | None = _env("DCL_DB_PASSWORD", default=None)
    db_port: Port | None = _env("DCL_DB_PORT", default=None)
    database_url: SecretStr | None = _env("DCL_DATABASE_URL", default=None)
    bind_host: str = _env("DCL_BIND_HOST", default="127.0.0.1")
    portainer_user: str | None = _env("DCL_PORTAINER_USER", default=None)
    portainer_password: SecretStr | None = _env("DCL_PORTAINER_PASSWORD", default=None)

    redis_url: str | None = _env("DCL_REDIS_URL", default=None)
    minio_endpoint: AnyHttpUrl | None = _env("DCL_MINIO_ENDPOINT", default=None)
    minio_access_key: str | None = _env("DCL_MINIO_ACCESS_KEY", default=None)
    minio_secret_key: SecretStr | None = _env("DCL_MINIO_SECRET_KEY", default=None)
    minio_secure: bool = _env("DCL_MINIO_SECURE", default=False)
    minio_root_user: str | None = _env("DCL_MINIO_ROOT_USER", default=None)
    minio_root_password: SecretStr | None = _env("DCL_MINIO_ROOT_PASSWORD", default=None)
    models_url: AnyHttpUrl | None = _env("DCL_MODELS_URL", default=None)
    office_url: AnyHttpUrl | None = _env("DCL_OFFICE_URL", default=None)
    api_base_url: AnyHttpUrl | None = _env("DCL_API_BASE_URL", default=None)
    console_base_url: AnyHttpUrl | None = _env("DCL_CONSOLE_BASE_URL", default=None)
    pipe_shared_secret: SecretStr | None = _env("DCL_PIPE_SHARED_SECRET", default=None)

    console_api_audience: str | None = _env("DCL_CONSOLE_API_AUDIENCE", default=None)
    console_group_reviewers: str | None = _env("DCL_CONSOLE_GROUP_REVIEWERS", default=None)
    console_group_admins: str | None = _env("DCL_CONSOLE_GROUP_ADMINS", default=None)
    console_group_external_search: str | None = _env("DCL_CONSOLE_GROUP_EXTERNAL_SEARCH", default=None)
    console_allowed_origins: CommaList = _env("DCL_CONSOLE_ALLOWED_ORIGINS", default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _dev_defaults_and_comma_lists(cls, data: dict) -> dict:
        if str(data.get("DCL_ENV") or Environment.DEV).strip().lower() == Environment.DEV:
            for name, value in DEV_DEFAULTS.items():
                data.setdefault(name, value)
        for name in COMMA_LISTS:
            value = data.get(name)
            if isinstance(value, str):
                data[name] = [item.strip() for item in value.split(",") if item.strip()]
        return data

    @field_validator("redis_url")
    @classmethod
    def _redis_scheme(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("redis://", "rediss://", "unix://")):
            raise ValueError("must start with redis://, rediss:// or unix://")
        return value

    @field_validator("token_cache_key")
    @classmethod
    def _fernet_key_shape(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                raw = base64.urlsafe_b64decode(value.get_secret_value().encode())
            except (ValueError, binascii.Error):
                raw = b""
            if len(raw) != 32:
                raise ValueError("must be a Fernet key (32 bytes, url-safe base64)")
        return value

    @model_validator(mode="after")
    def _roots_pair_up(self) -> "Settings":
        if self.folder_ids and self.folder_paths and len(self.folder_ids) != len(self.folder_paths):
            raise ValueError("DCL_FOLDER_IDS and DCL_FOLDER_PATHS must list the same number of folders")
        return self

    def require(self, *groups: Group | str) -> "Settings":
        missing: list[str] = []
        for group in map(Group, groups):
            if group is Group.DATABASE:
                if self.database_url is None:
                    missing += [n for n in ("DCL_DB_USER", "DCL_DB_PASSWORD") if self._unset(n)]
                continue
            missing += [name for name in REQUIRED_BY_GROUP[group] if self._unset(name)]
        if missing:
            needed = ", ".join(map(str, groups))
            raise ConfigError(f"missing environment variables needed by {needed}: {', '.join(missing)}")
        return self

    def _unset(self, name: str) -> bool:
        return getattr(self, FIELD_BY_ENV_NAME[name]) in (None, [])

    def stack_database_url(self) -> SecretStr:
        """DCL_DATABASE_URL when set (host-side tools); otherwise the URL of the stack's postgres service."""
        self.require(Group.DATABASE)
        if self.database_url is not None:
            return self.database_url
        user = quote(self.db_user, safe="")
        password = quote(self.db_password.get_secret_value(), safe="")
        return SecretStr(
            f"postgresql+psycopg://{user}:{password}@{STACK_DATABASE_HOST}/{STACK_DATABASE_NAME}"
        )


def _aliases(field) -> tuple[str, ...]:
    alias = field.validation_alias
    return tuple(alias.choices) if isinstance(alias, AliasChoices) else (alias,)


FIELD_BY_ENV_NAME: dict[str, str] = {
    alias: name for name, field in Settings.model_fields.items() for alias in _aliases(field)
}
CONTRACT_NAMES = frozenset(FIELD_BY_ENV_NAME)
DEPRECATED_NAMES = {"ROLE": "DCL_ROLE"}
REQUIRED_BY_GROUP: dict[Group, tuple[str, ...]] = {
    Group.GRAPH: (
        "DCL_TENANT_ID",
        "DCL_CLIENT_ID",
        "DCL_AUTH_MODE",
        "DCL_DELEGATED_USERNAME",
        "DCL_PERMISSION_OPTION",
        "DCL_TOKEN_CACHE_PATH",
        "DCL_TOKEN_DIR",
        "DCL_TOKEN_CACHE_KEY",
        "DCL_DRIVE_ID",
        "DCL_FOLDER_IDS",
        "DCL_FOLDER_PATHS",
    ),
    Group.GEMINI: ("GEMINI_BACKEND", "GEMINI_GATEWAY_URL", "GEMINI_GATEWAY_KEY"),
    Group.ALERTS: ("DCL_ALERT_WEBHOOK_URL",),
    Group.REDIS: ("DCL_REDIS_URL",),
    Group.MINIO: ("DCL_MINIO_ENDPOINT", "DCL_MINIO_ACCESS_KEY", "DCL_MINIO_SECRET_KEY"),
    Group.MODELS: ("DCL_MODELS_URL",),
    Group.OFFICE: ("DCL_OFFICE_URL",),
    Group.LINKS: ("DCL_API_BASE_URL", "DCL_CONSOLE_BASE_URL"),
    Group.CONSOLE_AUTH: (
        "DCL_TENANT_ID",
        "DCL_CONSOLE_API_AUDIENCE",
        "DCL_CONSOLE_GROUP_REVIEWERS",
        "DCL_CONSOLE_GROUP_ADMINS",
        "DCL_CONSOLE_GROUP_EXTERNAL_SEARCH",
        "DCL_CONSOLE_ALLOWED_ORIGINS",
    ),
    Group.PIPE: ("DCL_PIPE_SHARED_SECRET",),
}


def _refuse_forbidden_and_placeholders(sources: list[Mapping[str, str | None]]) -> None:
    gateway_only = "Gemini is reached only through the Manastu gateway (docs/architecture/09 §H.1)"
    for name in FORBIDDEN_NAMES:
        if any(name in source for source in sources):
            raise ConfigError(f"{name} is set; {gateway_only}. Remove it from the environment and from .env.")
    for name in GATEWAY_KEY_NAMES:
        if any((source.get(name) or "").strip().startswith(DEVELOPER_KEY_PREFIX) for source in sources):
            raise ConfigError(
                f"{name} has the Google Developer API key format; {gateway_only}. "
                "Put the gateway credential there instead."
            )
    placeholders = sorted(
        {
            name
            for source in sources
            for name, value in source.items()
            if name in CONTRACT_NAMES and value and PLACEHOLDER.match(value)
        }
    )
    if placeholders:
        raise ConfigError(f"placeholder values must be replaced in .env: {', '.join(placeholders)}")


def load_settings(env_file: Path | None = None) -> Settings:
    file_values = dotenv_values(env_file) if env_file and env_file.is_file() else {}
    sources = [os.environ, file_values]
    _refuse_forbidden_and_placeholders(sources)
    for old, new in DEPRECATED_NAMES.items():
        if any(source.get(old) for source in sources):
            log.warning("%s is deprecated; set %s instead (docs/architecture/01 §7.1)", old, new)
    try:
        return Settings(_env_file=env_file if file_values else None)
    except ValidationError as exc:
        problems = []
        for err in exc.errors(include_input=False, include_url=False):
            name = str(err["loc"][0]) if err["loc"] else "settings"
            problems.append(f"{name}: {err['msg']}")
        raise ConfigError("invalid environment: " + "; ".join(problems)) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings(DEFAULT_ENV_FILE)
