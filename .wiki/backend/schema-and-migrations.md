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
- `backend/postgres/models/__init__.py`, `backend/postgres/models/registry.py` (M1: `sync_roots`, `drive_folders`, `drive_items`, `blobs`, `blob_derivations`, `jobs`), `backend/postgres/models/ops.py` (`pipeline_config`), `documents.py` (documents, document_sources, document_relations), `nodes.py` (document_nodes with `halfvec(768)` and `bbox` = JSON list of PageBox, assets), `entities.py` (entities, entity_aliases, entity_mentions, numeric_facts), `review.py` (audit_events, rules, review_flags), `benchmark.py` (benchmark_cases, benchmark_runs, benchmark_results)
- `backend/postgres/pipeline_config.py` (get / get_prefix / set_value, `seed_gate` from `config/gate.yaml`, `seed_sanity_ranges` from `config/sanity_ranges.yaml`, `gate_config()`, `sanity_ranges()`, `download_scope()`, `processing_scope()`; CLI `seed-config | seed-gate [--reseed]`)
- `backend/postgres/alembic.ini`, `backend/postgres/migrations/env.py`, `backend/postgres/migrations/script.py.mako`
- `backend/postgres/migrations/versions/0001_m1_registry.py`, `0002_pipeline_config.py` (table + `v_config_current`), `0003_documents_entities_audit.py` (vector extension, 10 tables, `hnsw_document_nodes_embedding` / `_image_embedding`), `0004_bm25_indexes.py` (pg_search `bm25_document_nodes` + `bm25_documents`, S2's verified DDL verbatim), `0005_review_flags_rules.py`, `0006_benchmark_tables.py`
- `backend/postgres/session.py` (`engine_from_settings`, `session_factory`, `normalize_url`, FastAPI dependency `get_session`)
- `backend/postgres/views.sql` (planned, M2–M3)

Tests and fixtures:
- `backend/tests/schema/conftest.py`, `backend/tests/schema/test_m1_schema.py`, `backend/tests/schema/test_pipeline_config.py`
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
- `backend/postgres/pipeline_config.py`
- `backend/postgres/models/`
- `backend/postgres/alembic.ini`
- `backend/postgres/migrations/`
- `backend/tests/schema/`

## Rubric (what "done" means for this feature)

- [x] alembic upgrade head and alembic check pass (M1 tables; ParadeDB `latest-pg17` = PG 17.11, pg_search 0.26.2, also PG 18 and postgres:16; CI wiring pending S4)
- [x] FK-without-index query returns no rows (and is proven to detect a missing index)
- [x] Every status column has a CHECK generated from a Python enum (M1 tables)
- [x] Tables are created in the milestone whose code writes them (only the six M1 tables exist)
- [x] Document, node, asset, entity, fact and audit tables with HNSW indexes (0003)
- [x] BM25 indexes (0004)
- [x] review_flags, rules (0005); benchmark tables (0006)
- [ ] telemetry_*, llm_calls, answer_traces, views (M2–M8)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | Base, naming convention, enums→CHECK, M1 registry models, migration 0001, schema tests, FK-without-index query |
| 2026-10-21 | S1 | session.py; `Job.key_for()` |
| 2026-10-22 | S1 | Migration 0002 `pipeline_config` + `v_config_current` (M1, Lead decision); typed access and gate seeding |
| 2026-10-22 | S1 | Migrations 0005 (rules, review_flags with location-level fingerprint uniqueness) and 0006 (benchmark tables; run statuses chosen by S1) |
| 2026-10-22 | S1 | Migration 0004: BM25 indexes from S2's verified pg_search 0.26.2 DDL |
| 2026-10-22 | S1 | `get_session` dependency; `sanity_ranges` key seeded from config/sanity_ranges.yaml |
| 2026-10-22 | S1 | Migration 0003: M2 document tables, M4 entity/fact tables, audit_events (Lead decision); HNSW indexes; pgvector dep |

## Related

- `.wiki/index.md`
- `backend/sync-engine`, `backend/gate-and-scope`, `backend/registry-and-blobs` (write the M1 tables)
