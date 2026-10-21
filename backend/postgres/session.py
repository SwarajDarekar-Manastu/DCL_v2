"""Engine and sessions. The URL comes from the env contract (``Settings.stack_database_url``)."""

from collections.abc import Iterator
from functools import lru_cache

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


@lru_cache(maxsize=1)
def default_session_factory() -> sessionmaker[Session]:
    from backend.config import get_settings

    return session_factory(engine_from_settings(get_settings()))


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards; routers commit explicitly.

    Use ``session: Annotated[Session, Depends(get_session)]``; tests override ``get_session``.
    """
    with default_session_factory()() as session:
        yield session
