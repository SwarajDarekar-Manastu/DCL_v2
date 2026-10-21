"""Shared fixtures for the sync tests that need a migrated, disposable PostgreSQL (DCL_TEST_DATABASE_URL)."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from alembic import command
from alembic.config import Config
from minio import Minio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.postgres import pipeline_config
from backend.postgres.models import SyncRoot
from backend.postgres.session import normalize_url
from backend.storage.minio import ensure_buckets

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        config = Config(str(ALEMBIC_INI))
        command.upgrade(config, "head")
        eng = create_engine(normalize_url(url))
        yield eng
        eng.dispose()
        command.downgrade(config, "base")


@pytest.fixture()
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        pipeline_config.seed_gate(s, pipeline_config.load_gate_yaml())
        s.add(SyncRoot(root_name="APU Injector", remote_drive_id="D", remote_item_id="ROOT"))
        s.commit()
        yield s
        s.rollback()
        tables = ("review_flags", "drive_items", "drive_folders", "blobs", "sync_roots", "pipeline_config")
        for table in tables:
            s.execute(text(f"DELETE FROM {table}"))
        s.commit()


@pytest.fixture(scope="module")
def minio() -> Minio:
    endpoint = os.environ.get("DCL_TEST_MINIO_ENDPOINT")
    if not endpoint:
        pytest.skip("DCL_TEST_MINIO_ENDPOINT is not set")
    parts = urlsplit(endpoint)
    client = Minio(
        parts.netloc,
        access_key=os.environ.get("DCL_TEST_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("DCL_TEST_MINIO_SECRET_KEY", "minioadmin"),
        secure=parts.scheme == "https",
    )
    ensure_buckets(client)
    return client
