"""Schema tests run Alembic against a disposable database.

They upgrade and downgrade the whole schema, so they never use DCL_DATABASE_URL. Point
DCL_TEST_DATABASE_URL at an empty database on the pinned ParadeDB image; without it the
tests are skipped.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "postgres" / "alembic.ini"


def _test_url() -> str:
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    return normalize_url(url)


@pytest.fixture(scope="session")
def database_url(monkeypatch_session) -> str:
    url = _test_url()
    monkeypatch_session.setenv("DCL_DATABASE_URL", url)
    return url


@pytest.fixture(scope="session")
def monkeypatch_session():
    with pytest.MonkeyPatch.context() as mp:
        yield mp


@pytest.fixture(scope="session")
def alembic_config(database_url) -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture(scope="session")
def engine(database_url):
    eng = create_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture()
def migrated(alembic_config, engine):
    """Schema at head for one test, torn down to an empty database afterwards."""
    command.upgrade(alembic_config, "head")
    yield engine
    command.downgrade(alembic_config, "base")
