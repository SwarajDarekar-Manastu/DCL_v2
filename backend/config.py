"""Environment contract (docs/architecture/01 §7.1). Skeleton: ROLE only; the full contract follows."""

from enum import StrEnum
from functools import lru_cache

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Role(StrEnum):
    API = "api"
    MODELS = "models"
    ALL = "all"


class ConfigError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    role: Role


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        names = sorted({str(err["loc"][0]).upper() for err in exc.errors()})
        raise ConfigError(f"invalid or missing environment variables: {', '.join(names)}") from None
