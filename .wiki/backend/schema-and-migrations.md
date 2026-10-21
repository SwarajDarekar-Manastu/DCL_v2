# PostgreSQL schema, enums as CHECK, Alembic

| Field | Value |
|-------|-------|
| Feature id | `backend/schema-and-migrations` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/05_storage_schema.md (all) |
| Last updated | 2026-10-21 |

## Purpose

Own the 26-table schema in three tiers, the StrEnum→CHECK generation, naming conventions, every FK index, and hand-written migrations for HNSW/BM25/CHECK.

## Location

Code:
- `backend/postgres/base.py`
- `backend/postgres/enums.py`
- `backend/postgres/models/`
- `backend/postgres/migrations/`

Tests and fixtures:
- `backend/tests/schema/`

## Interfaces

Provides:
- SQLAlchemy models
- migration files
- v_* views

Consumes:
- ParadeDB image (platform/compose-stack)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/postgres/base.py`
- `backend/postgres/enums.py`
- `backend/postgres/models/`
- `backend/postgres/migrations/`
- `backend/tests/schema/`

## Rubric (what "done" means for this feature)

- [ ] alembic upgrade head and alembic check pass in CI
- [ ] FK-without-index query returns no rows
- [ ] Every status column has a CHECK generated from a Python enum
- [ ] Tables are created in the milestone whose code writes them
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
