"""Acceptance checks run against the live stack database, read-only, and only when asked:
DCL_ACCEPTANCE=1 and DCL_DATABASE_URL set. A plain `uv run pytest` skips them."""

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
