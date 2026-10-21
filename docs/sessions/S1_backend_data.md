# S1 — Backend & Data (sync, dispatcher, telemetry, schema)

**Mission:** everything between OneDrive and a committed document: the Graph sync engine, the junk gate and scopes, the content-addressed registry, the dispatcher and route gating, the deterministic routes (C telemetry, A2 source, B code, E diagrams, G archives), the PostgreSQL schema and migrations, the review backend (flags, rules, staged payloads, resume) and the index commit path.

## Read first

`docs/architecture/02_phase1_ingestion_sync.md`, `03_phase2_processing_routes.md` (§1, §2, §5, §6, §7, §9, §11, §12), `05_storage_schema.md` (all), `06_review_flags_and_halt_policy.md`, `04_metadata_enrichment_chunking_embedding.md` §7 (index commit).

## You own

`backend/sync`, `backend/dispatcher`, `backend/routes/{c_telemetry,a2_source,b_code,e_diagrams,g_archives}`, `backend/postgres` (SQLAlchemy models, enum→CHECK generation, naming convention), `migrations`, `backend/review` (flag models, fingerprints, staged payload, resume, rules engine), `backend/indexing/commit.py`.

## Publish first (others code against these)

1. `backend/postgres/models.py` for the M1 tables (`sync_roots`, `drive_folders`, `drive_items`, `blobs`, `blob_derivations`, `jobs`) and the `StrEnum` classes for every `status` column, with the Alembic migration.
2. `backend/dispatcher/contract.py`: the `ProcessedDocument` output contract of file 03 §1.4 (Pydantic), including `Flag` with `fingerprint` and the stable `Anchor` model (`doc_id`, `page_no`, `line_start`, `t_start_ms`, `sheet_name`, `cell_range`, `content_sha256`).
3. `backend/review/api_models.py`: request/response models for cases, resolutions, rules and dry-run (file 08 §4.4), so S3 can build the Review UI against them.
4. The `rules` precedence resolver signature and the `channel_map` body schema (file 03 §C.0), so S5 can write rule YAML fixtures.

## Depends on

S4: `.env` contract loader, compose stack, queue definitions. S2: `index_document()` entry point for enrichment and embeddings (you call it from the commit path). S5: route fixtures and sanity ranges.

## Milestones

M1 (primary), M2 (primary), M3 review API (supporting), M4 commit path and migrations (supporting), M6 full-corpus run (primary with S4), M7 routes E and G.

## First tasks

1. Models + migration for the M1 tables with CHECK-constrained statuses and every FK indexed; the CI query that lists FK columns without an index.
2. MSAL device-code sign-in and silent refresh with the token cache at `DCL_TOKEN_CACHE_PATH`; the outside-share negative check.
3. Delta crawl of the four roots from `DCL_FOLDER_IDS`, metadata-only first, with the folder tree and computed paths; gate tiers 1–3 from `config/gate.yaml`; `HELD_BY_SCOPE` handling.
4. Downloader with streamed SHA-256 and quickXorHash verification, conflict-safe blob insert, `(quick_xor_hash, size_bytes)` skip.
5. `jobs` idempotency with the `job_key` rule; the queue load-test harness (5,000 synthetic tasks, failure injection, OOM containment).
6. Then M2: type resolution and sniffers, folder context, assembler, route gating, CIR writer, Route C end to end (channel-map pass into `rules`, `.dat/.cfg`, TDMS, CSV triage, XLSX dual read, mystery formats, sub-runs, t0, Parquet, catalog, three-tier stats), flags with fingerprints and staged payloads, `resume_from_staged`.

## Definition of done

Wiki: map page updated and plan sheet deleted (see below). Then, per feature:

Unit tests; CIR snapshot fixture for each route; a flag fixture for each flag the route can raise; migration applies on the pinned ParadeDB image; `alembic check` clean; status entry in `docs/sessions/STATUS.md`; merge request to `DCL Lead`.

## Wiki duty (applies to every task)

Read `.wiki/index.md` and your feature's map page first. Open a plan sheet (`.wiki/_templates/plan-sheet.md`) with the exact workspace and rubric; work only inside it; when done, update the map page (status, location, interfaces, workspace, change log), update the area index, delete the plan sheet. Your map pages are listed in `.wiki/<area>/index.md` under your session id.

## When in doubt or blocked

Write the question or the blocker to `docs/sessions/STATUS.md`, message `DCL Lead` (or the session you wait on) once, and end your turn. Never improvise around the manual and never keep working "on the side" while waiting.

## Coordination rules

- Never load pickle files; never put document state on `drive_items`; never store node ids durably.
- Schema changes: message `DCL Lead` before adding a table (the three-tier rule in file 05 applies).
- S2 owns the chunker and enrichment; you call them through `index_document(doc_id)`; do not reimplement.
