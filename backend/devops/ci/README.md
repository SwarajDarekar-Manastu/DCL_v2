# CI scripts

`.github/workflows/ci.yml` calls only these scripts, so every gate runs the same way on the dev host. Run them from the repository root.

| Gate | Command |
|------|---------|
| Lint | `uv run ruff check backend && uv run ruff format --check backend` |
| Disposable ParadeDB 0.26.2-pg17 + MinIO | `eval "$(backend/devops/ci/test_services.sh up)"` … `backend/devops/ci/test_services.sh down` |
| Schema gate: `alembic upgrade head`, `alembic check`, FK-without-index query | `backend/devops/ci/schema_gate.sh` (needs `DCL_TEST_DATABASE_URL`) |
| Tests, including the DB and MinIO suites | `uv run pytest -q` with the `DCL_TEST_*` exports from `test_services.sh` |
| Image secret scan | `uv run python backend/devops/ci/scan_image_secrets.py <image> [--forbid-values-from .env]` |

On the dev host, add `--forbid-values-from .env` to the scan. It then also fails when any file in the image contains one of the real secret values, and it reports the variable name only. CI has no `.env`, so it scans by pattern.

The benchmark gate (a merge that drops telemetry exactness is blocked) joins in M10.
