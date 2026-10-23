# Milestone acceptance checklists

| Field | Value |
|-------|-------|
| Feature id | `quality/acceptance` |
| Status | in-progress |
| Owner session | S5 |
| Spec | docs/architecture/10_development_plan.md §5 |
| Last updated | 2026-10-22 |

## Purpose

Executable acceptance checks per milestone mirroring file 10 §5.

## Location

Code:
- `backend/tests/acceptance/README.md` (how checks run)
- `backend/tests/acceptance/M1.md`, `M2.md` (criterion → check or procedure)
- `backend/tests/acceptance/m1_state.py` (read-only registry queries; snapshot/compare CLI)
- `backend/tests/acceptance/m2_state.py` (read-only Route C, Parquet (MinIO GET) and TP7 CONFLICT checks)
- `backend/tests/acceptance/FORMATS.md`, `test_format_routes.py` (route entry points over the public format samples, values in git-ignored `data/benchmark/formats.local.yaml`)
- `backend/tests/acceptance/M5.md`, `m5_state.py` (A1 crop geometry, table crops, figure content, contact sheets; `report` CLI)
- `backend/tests/acceptance/conftest.py` (opt-in live session, read-only)

Tests and fixtures:
- `backend/tests/acceptance/test_m1_acceptance.py` (live stack, `DCL_ACCEPTANCE=1`)
- `backend/tests/acceptance/test_m1_checks_on_seeded_db.py` (disposable DB, `DCL_TEST_DATABASE_URL`)
- `backend/tests/acceptance/test_m2_acceptance.py` (live stack, `DCL_ACCEPTANCE=1`, `DCL_MINIO_*` for Parquet)
- `backend/tests/acceptance/test_m2_checks_on_seeded_db.py` (disposable DB; Parquet from a dict)
- `backend/tests/acceptance/test_m5_acceptance.py` (live stack), `test_m5_checks_on_seeded_db.py` (disposable DB)

## Interfaces

Provides:
- pass/fail per milestone criterion; registry snapshots for the event-driven procedures
- TP7 footer CONFLICT check (file 03 §1.2)

Consumes:
- `backend/schema-and-migrations` (registry models, Alembic), `backend/gate-and-scope` (`in_scope`, `pipeline_config`), DECISIONS.md allowlist row
- `backend/route-c-telemetry` (documents, review_flags, telemetry_runs/channels, normalized Parquet), `backend/route-a1-office` (CONFLICT evidence), `backend/common/units.py` (`to_canonical`)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/tests/acceptance/README.md`
- `backend/tests/acceptance/M1.md`
- `backend/tests/acceptance/M2.md`
- `backend/tests/acceptance/m1_state.py`
- `backend/tests/acceptance/m2_state.py`
- `backend/tests/acceptance/conftest.py`
- `backend/tests/acceptance/test_m1_acceptance.py`
- `backend/tests/acceptance/test_m1_checks_on_seeded_db.py`
- `backend/tests/acceptance/test_m2_acceptance.py`
- `backend/tests/acceptance/test_m2_checks_on_seeded_db.py`
- `backend/tests/acceptance/M5.md`
- `backend/tests/acceptance/FORMATS.md`
- `backend/tests/acceptance/test_format_routes.py`
- `backend/tests/acceptance/m5_state.py`
- `backend/tests/acceptance/test_m5_acceptance.py`
- `backend/tests/acceptance/test_m5_checks_on_seeded_db.py`

## Rubric (what "done" means for this feature)

- [x] M1 checklist: every criterion mapped; DB-state checks automated, read-only, opt-in
- [x] Each automated M1 check proven to pass on a good and fail on a bad seeded state
- [ ] M1 checks green on the live stack (Lead runs them); procedure 7 SUPERSEDES half after the dispatcher; procedure 10 once S4's harness is on main and the stack is redeployed
- [x] M2 Route C checks (criteria 1, 6 and the reported outcome) executable, read-only, proven on a seeded DB
- [x] TP7 footer CONFLICT check executable, read-only, proven on a seeded DB
- [ ] M2 checks green on the live stack (Lead runs them); 1c waits on Route C suggestions, TP7 on A1 dispatch
- [x] M5 crop checks (size, page share, full-page rule, table crops, figure content, contact sheets) executable, read-only, proven on a seeded DB
- [x] Route-level format checks: 13 (A1, B, C, E, G) over the public samples, each failing on changed values; docx needs tesseract (parse image)
- [ ] M5 crop checks run on the live stack after S1's re-dispatch and S2's crop fix (S5 runs, Lead triggers)
- [ ] M2 criteria 3 and 4 executable (wait on Routes A2 and B)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

Verification: `DCL_TEST_DATABASE_URL=<disposable db> uv run pytest backend/tests/acceptance && uv run ruff check backend`

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-23 | S5 | formats cases moved from the engine suite to route-level checks (`test_format_routes.py`, Lead ruling) |
| 2026-10-23 | S5 | M5 crop checks and `m5_state.py report`; 7 seeded-DB proofs |
| 2026-10-22 | S5 | M2 Route C checks (status counts, flag/status, unit cases, SI Parquet, duplicate flags) and the TP7 footer CONFLICT check; 11 seeded-DB proofs |
| 2026-10-22 | S5 | M1.md procedure 10 gets S4's queue load-test harness and expected report |
| 2026-10-22 | S5 | M1.md procedures 6–9 get S1's commands (delta crawl, downloader, resync) |
| 2026-10-22 | S5 | M1 checklist with 5 automated checks (read-only, opt-in) and 5 procedures with a snapshot/compare CLI; 7 seeded-DB proofs; M2 draft |

## Related

- `.wiki/index.md`
- `backend/sync-engine`, `backend/gate-and-scope`, `backend/schema-and-migrations`
- `quality/fixtures` (M2 inputs)
- `backend/route-c-telemetry`, `backend/route-a1-office`
