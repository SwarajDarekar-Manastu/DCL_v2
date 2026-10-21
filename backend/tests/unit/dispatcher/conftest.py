"""The dispatcher's DB tests reuse the sync tests' disposable PostgreSQL and MinIO fixtures."""

from backend.tests.unit.sync.conftest import engine, minio, session  # noqa: F401
