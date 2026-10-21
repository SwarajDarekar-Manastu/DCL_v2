# PostgreSQL schema, enums as CHECK, Alembic

| Field | Value |
|-------|-------|
| Feature id | `backend/schema-and-migrations` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/05_storage_schema.md (all) |
| Last updated | 2026-10-21 |

## Purpose

Own the 26-table schema in three tiers, the StrEnum→CHECK generation, naming conventions, every FK index, and hand-written migrations for HNSW/BM25/CHECK.

## Location

Code:
- `backend/postgres/base.py` (naming convention, `Base`, `Tier`, `tier()`)
- `backend/postgres/enums.py` (one `StrEnum` per ✓ column, `enum_check()`)
- `backend/postgres/models/__init__.py`, `backend/postgres/models/registry.py` (M1: `sync_roots`, `drive_folders`, `drive_items`, `blobs`, `blob_derivations`, `jobs`)
- `backend/postgres/alembic.ini`, `backend/postgres/migrations/env.py`, `backend/postgres/migrations/script.py.mako`
- `backend/postgres/migrations/versions/0001_m1_registry.py`
- `backend/postgres/session.py` (planned)
- `backend/postgres/views.sql` (planned, M2–M3)

Tests and fixtures:
- `backend/tests/schema/conftest.py`, `backend/tests/schema/test_m1_schema.py`
- `backend/tests/schema/fk_without_index.sql` (the CI query: any row fails the build)

## Interfaces

Provides:
- SQLAlchemy models (`from backend.postgres.models import DriveItem, …`) and status enums (`backend.postgres.enums`)
- migration files; run from the repository root: `alembic -c backend/postgres/alembic.ini upgrade head` with `DCL_DATABASE_URL`
- `fk_without_index.sql` for CI
- v_* views (planned)

Consumes:
- ParadeDB image (platform/compose-stack)
- `DCL_DATABASE_URL` (platform/env-contract); the migration env reads it directly until `backend/config.py` exists
- `DCL_TEST_DATABASE_URL`: a disposable database for `backend/tests/schema` (upgrades and downgrades the whole schema; tests skip without it). Run: `DCL_TEST_DATABASE_URL=… uv run pytest backend/tests/schema`

Conventions fixed here:
- Constraint names: `pk_<t>`, `uq_<t>_<cols>`, `ix_<t>_<cols>`, `fk_<t>_<cols>_<referred>`, `ck_<t>_<column>`.
- CHECK value lists are literal in migrations; the tests compare them with the enums, so an enum change without a migration fails.
- Hand-written HNSW/BM25 indexes must be named `hnsw_*` / `bm25_*` (autogenerate skips them).
- Alembic compares only tables of the current schema that no extension owns (the ParadeDB image ships PostGIS tables).
- `jobs.blob_sha256` and `jobs.doc_id` are indexed without FKs (the ledger must not block the blob purge); `blob_derivations.parent_blob_sha256` has an FK (covered by the PK); `child_blob_sha256` is NULL for gate-skipped members.

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/postgres/base.py`
- `backend/postgres/enums.py`
- `backend/postgres/models/`
- `backend/postgres/alembic.ini`
- `backend/postgres/migrations/`
- `backend/tests/schema/`

## Rubric (what "done" means for this feature)

- [x] alembic upgrade head and alembic check pass (M1 tables; ParadeDB `latest-pg17` = PG 17.11, pg_search 0.26.2, also PG 18 and postgres:16; CI wiring pending S4)
- [x] FK-without-index query returns no rows (and is proven to detect a missing index)
- [x] Every status column has a CHECK generated from a Python enum (M1 tables)
- [x] Tables are created in the milestone whose code writes them (only the six M1 tables exist)
- [ ] Remaining 20 tables, extensions, views, HNSW/BM25 migrations (M2–M10)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | Base, naming convention, enums→CHECK, M1 registry models, migration 0001, schema tests, FK-without-index query |

## Related

- `.wiki/index.md`
- `backend/sync-engine`, `backend/gate-and-scope`, `backend/registry-and-blobs` (write the M1 tables)
