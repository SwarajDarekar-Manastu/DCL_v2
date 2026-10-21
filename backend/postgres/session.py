"""Engine and sessions. The URL comes from the env contract (``Settings.stack_database_url``)."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings


def normalize_url(url: str) -> str:
    """``postgresql://`` → ``postgresql+psycopg://`` (the one driver the backend uses)."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def engine_from_settings(settings: Settings) -> Engine:
    return create_engine(normalize_url(settings.stack_database_url().get_secret_value()), pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
