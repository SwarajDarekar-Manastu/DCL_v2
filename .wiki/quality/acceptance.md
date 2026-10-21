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
- `backend/tests/acceptance/conftest.py` (opt-in live session, read-only)

Tests and fixtures:
- `backend/tests/acceptance/test_m1_acceptance.py` (live stack, `DCL_ACCEPTANCE=1`)
- `backend/tests/acceptance/test_m1_checks_on_seeded_db.py` (disposable DB, `DCL_TEST_DATABASE_URL`)

## Interfaces

Provides:
- pass/fail per milestone criterion; registry snapshots for the event-driven procedures

Consumes:
- `backend/schema-and-migrations` (registry models, Alembic), `backend/gate-and-scope` (`in_scope`, `pipeline_config`), DECISIONS.md allowlist row

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/tests/acceptance/README.md`
- `backend/tests/acceptance/M1.md`
- `backend/tests/acceptance/M2.md`
- `backend/tests/acceptance/m1_state.py`
- `backend/tests/acceptance/conftest.py`
- `backend/tests/acceptance/test_m1_acceptance.py`
- `backend/tests/acceptance/test_m1_checks_on_seeded_db.py`

## Rubric (what "done" means for this feature)

- [x] M1 checklist: every criterion mapped; DB-state checks automated, read-only, opt-in
- [x] Each automated M1 check proven to pass on a good and fail on a bad seeded state
- [ ] M1 checks green on the live stack (Lead runs them); procedure 7 SUPERSEDES half after the dispatcher; procedure 10 once S4's harness is on main and the stack is redeployed
- [ ] M2 checklist executable (draft written; waits on dispatcher, CIR writer, Route C)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

Verification: `DCL_TEST_DATABASE_URL=<disposable db> uv run pytest backend/tests/acceptance && uv run ruff check backend`

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S5 | M1.md procedure 10 gets S4's queue load-test harness and expected report |
| 2026-10-22 | S5 | M1.md procedures 6–9 get S1's commands (delta crawl, downloader, resync) |
| 2026-10-22 | S5 | M1 checklist with 5 automated checks (read-only, opt-in) and 5 procedures with a snapshot/compare CLI; 7 seeded-DB proofs; M2 draft |

## Related

- `.wiki/index.md`
- `backend/sync-engine`, `backend/gate-and-scope`, `backend/schema-and-migrations`
- `quality/fixtures` (M2 inputs)
