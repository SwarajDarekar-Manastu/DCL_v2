"""Acceptance checks run against the live stack, read-only, and only when asked: DCL_ACCEPTANCE=1 and
DCL_DATABASE_URL set (DCL_MINIO_* for the Parquet checks). A plain `uv run pytest` skips them."""

import importlib.util
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"s5_acceptance_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def m1():
    return _load("m1_state")


@pytest.fixture(scope="session")
def live_session(m1):
    if os.environ.get("DCL_ACCEPTANCE") != "1" or not os.environ.get("DCL_DATABASE_URL"):
        pytest.skip("acceptance checks need DCL_ACCEPTANCE=1 and DCL_DATABASE_URL")
    from backend.postgres.session import normalize_url

    with m1.read_only(normalize_url(os.environ["DCL_DATABASE_URL"])) as session:
        yield session


@pytest.fixture(scope="session")
def m2():
    return _load("m2_state")


@pytest.fixture(scope="session")
def live_minio(m2, live_session):
    if not all(
        os.environ.get(k) for k in ("DCL_MINIO_ENDPOINT", "DCL_MINIO_ACCESS_KEY", "DCL_MINIO_SECRET_KEY")
    ):
        pytest.skip("Parquet checks need DCL_MINIO_ENDPOINT, DCL_MINIO_ACCESS_KEY, DCL_MINIO_SECRET_KEY")
    return m2.minio_getter()
