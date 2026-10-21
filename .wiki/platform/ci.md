# CI pipeline and gates

| Field | Value |
|-------|-------|
| Feature id | `platform/ci` |
| Status | in-progress |
| Owner session | S4 |
| Spec | docs/architecture/10_development_plan.md §7; 05 §3; 01 §7.1 |
| Last updated | 2026-10-22 |

## Purpose

Lint, unit tests, alembic upgrade/check on the pinned ParadeDB image, FK-index query, image secret scan, benchmark gate. Every workflow step is a script that runs the same way on the dev host.

## Location

Code:
- `.github/workflows/ci.yml` (jobs `lint`, `test`, `images`)
- `backend/devops/ci/test_services.sh` (disposable ParadeDB 0.26.2-pg17 + MinIO, random credentials, `DCL_TEST_*` exports)
- `backend/devops/ci/schema_gate.sh` (upgrade head, `alembic check`, `backend/tests/schema/fk_without_index.sql`)
- `backend/devops/ci/scan_image_secrets.py` (every layer of an image; optional exact-value check against `.env`)
- `backend/devops/ci/README.md`

Tests and fixtures:
- `backend/tests/unit/devops/test_scan_image_secrets.py`

## Interfaces

Provides:
- green/red on every PR and push to main
- `DCL_TEST_DATABASE_URL`, `DCL_TEST_MINIO_ENDPOINT`, `DCL_TEST_MINIO_ACCESS_KEY`, `DCL_TEST_MINIO_SECRET_KEY` for S1's schema, storage and sync tests

Consumes:
- schema and `fk_without_index.sql` (S1)
- benchmark runner (S2/S5, M10)

## Workspace (files to touch when modifying this feature)

- `.github/workflows/`
- `backend/devops/ci/`
- `backend/tests/unit/devops/`

## Rubric (what "done" means for this feature)

- [ ] A merge that drops telemetry exactness is blocked (M10 benchmark gate)
- [x] Secret scan passes on every image (2026-10-22: backend, models, MinIO, LibreOffice clean against the 16 secret values of the real `.env`)
- [x] Schema gate green on pg17 (migrations at head, no drift, every FK indexed)
- [x] Workflow passes actionlint 1.7.7; every script verified on the dev host
- [ ] First green run on GitHub (after the merge to main)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S4 | Pipeline v1: lint, disposable ParadeDB + MinIO, schema gate, tests, image build + layer secret scan |

## Related

- `platform/compose-stack`, `backend/schema-and-migrations`, `quality/benchmark-suites`
- `.wiki/index.md`
