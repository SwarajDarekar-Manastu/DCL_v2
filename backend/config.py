"""Environment contract of docs/architecture/01 §7.1: secrets and endpoints come from the environment only.

Every process calls get_settings() at startup. Load-time refusals apply to every process; values a component
needs are checked by Settings.require() when that component starts, so a container never dies for a value
it does not use. Messages name variables, never values.
"""

import os
import re
from collections.abc import Mapping
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from dotenv import dotenv_values
from pydantic import AnyHttpUrl, Field, PositiveInt, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
FORBIDDEN_NAMES = ("GOOGLE_API_KEY",)
PLACEHOLDER = re.compile(
    r"^\s*(<.*>|\$\{.*\}|\.\.\.|x{3,}|changeme|change[-_]me|replace[-_]?me|todo|tbd|placeholder"
    r"|your[-_ ].*|fill[-_ ]?me|fill[-_ ]?in|none|null)\s*$",
    re.IGNORECASE,
)


class ConfigError(RuntimeError):
    pass


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


class Group(StrEnum):
    GRAPH = "graph"
    GEMINI = "gemini"
    ALERTS = "alerts"


CommaList = Annotated[list[str], NoDecode]


def _env(name: str, **kwargs):
    return Field(validation_alias=name, **kwargs)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore", frozen=True, env_ignore_empty=True, populate_by_name=False
    )

    role: Role | None = _env("ROLE", default=None)

    tenant_id: str | None = _env("DCL_TENANT_ID", default=None)
    client_id: str | None = _env("DCL_CLIENT_ID", default=None)
    auth_mode: Literal["delegated"] | None = _env("DCL_AUTH_MODE", default=None)
    delegated_username: str | None = _env("DCL_DELEGATED_USERNAME", default=None)
    permission_option: PermissionOption | None = _env("DCL_PERMISSION_OPTION", default=None)
    token_cache_path: Path | None = _env("DCL_TOKEN_CACHE_PATH", default=None)
    token_dir: Path | None = _env("DCL_TOKEN_DIR", default=None)

    drive_id: str | None = _env("DCL_DRIVE_ID", default=None)
    folder_ids: CommaList = _env("DCL_FOLDER_IDS", default_factory=list)
    folder_paths: CommaList = _env("DCL_FOLDER_PATHS", default_factory=list)
    test_outside_item_id: str | None = _env("DCL_TEST_OUTSIDE_ITEM_ID", default=None)

    secret_store: str | None = _env("DCL_SECRET_STORE", default=None)
    certificate_path: Path | None = _env("DCL_CERTIFICATE_PATH", default=None)
    certificate_thumbprint: SecretStr | None = _env("DCL_CERTIFICATE_THUMBPRINT", default=None)

    gemini_backend: Literal["gateway"] | None = _env("GEMINI_BACKEND", default=None)
    gemini_gateway_url: AnyHttpUrl | None = _env("GEMINI_GATEWAY_URL", default=None)
    gemini_gateway_key: SecretStr | None = _env("GEMINI_GATEWAY_KEY", default=None)
    gemini_thinking_level: ThinkingLevel | None = _env("GEMINI_THINKING_LEVEL", default=None)
    gemini_include_thoughts: bool = _env("GEMINI_INCLUDE_THOUGHTS", default=False)
    gemini_context_cache: bool = _env("GEMINI_CONTEXT_CACHE", default=False)
    gemini_cache_ttl_s: PositiveInt | None = _env("GEMINI_CACHE_TTL_S", default=None)
    google_cloud_project: str | None = _env("GOOGLE_CLOUD_PROJECT", default=None)
    google_cloud_location: str | None = _env("GOOGLE_CLOUD_LOCATION", default=None)

    alert_webhook_url: SecretStr | None = _env("DCL_ALERT_WEBHOOK_URL", default=None)

    db_user: str | None = _env("DCL_DB_USER", default=None)
    db_password: SecretStr | None = _env("DCL_DB_PASSWORD", default=None)
    db_port: Annotated[int, Field(gt=0, lt=65536)] | None = _env("DCL_DB_PORT", default=None)
    database_url: SecretStr | None = _env("DCL_DATABASE_URL", default=None)
    bind_host: str = _env("DCL_BIND_HOST", default="127.0.0.1")
    portainer_user: str | None = _env("DCL_PORTAINER_USER", default=None)
    portainer_password: SecretStr | None = _env("DCL_PORTAINER_PASSWORD", default=None)

    @model_validator(mode="before")
    @classmethod
    def _split_comma_lists(cls, data: dict) -> dict:
        for name in ("DCL_FOLDER_IDS", "DCL_FOLDER_PATHS"):
            value = data.get(name)
            if isinstance(value, str):
                data[name] = [item.strip() for item in value.split(",") if item.strip()]
        return data

    @model_validator(mode="after")
    def _roots_pair_up(self) -> "Settings":
        if self.folder_ids and self.folder_paths and len(self.folder_ids) != len(self.folder_paths):
            raise ValueError("DCL_FOLDER_IDS and DCL_FOLDER_PATHS must list the same number of folders")
        return self

    def require(self, *groups: Group) -> "Settings":
        missing = [
            name
            for group in groups
            for name in REQUIRED_BY_GROUP[group]
            if getattr(self, FIELD_BY_ENV_NAME[name]) in (None, [])
        ]
        if missing:
            needed = ", ".join(groups)
            raise ConfigError(f"missing environment variables needed by {needed}: {', '.join(missing)}")
        return self


FIELD_BY_ENV_NAME: dict[str, str] = {
    field.validation_alias: name for name, field in Settings.model_fields.items()
}
CONTRACT_NAMES = frozenset(FIELD_BY_ENV_NAME)
REQUIRED_BY_GROUP: dict[Group, tuple[str, ...]] = {
    Group.GRAPH: (
        "DCL_TENANT_ID",
        "DCL_CLIENT_ID",
        "DCL_AUTH_MODE",
        "DCL_DELEGATED_USERNAME",
        "DCL_PERMISSION_OPTION",
        "DCL_TOKEN_CACHE_PATH",
        "DCL_TOKEN_DIR",
        "DCL_DRIVE_ID",
        "DCL_FOLDER_IDS",
        "DCL_FOLDER_PATHS",
    ),
    Group.GEMINI: ("GEMINI_BACKEND", "GEMINI_GATEWAY_URL", "GEMINI_GATEWAY_KEY"),
    Group.ALERTS: ("DCL_ALERT_WEBHOOK_URL",),
}


def _refuse_forbidden_and_placeholders(sources: list[Mapping[str, str | None]]) -> None:
    for name in FORBIDDEN_NAMES:
        if any(name in source for source in sources):
            raise ConfigError(
                f"{name} is set; Gemini is reached only through the Manastu gateway "
                "(docs/architecture/09 §H.1). Remove it from the environment and from .env."
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
    _refuse_forbidden_and_placeholders([os.environ, file_values])
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
