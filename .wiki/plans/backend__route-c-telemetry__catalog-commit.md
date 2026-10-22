# Plan: backend/route-c-telemetry — step 2: catalog tables, normalization, metrics, commit, resume

| Field | Value |
|-------|-------|
| Feature | `backend/route-c-telemetry` (map: `.wiki/backend/route-c-telemetry.md`) |
| Session | S1 |
| Branch | claude/competent-brahmagupta-3a5541 |
| Opened | 2026-10-22 |
| Delete when | rubric below is green and the map page is updated |

## Intent

Step 2 of Route C (file 03 §C.0–C.7, file 05 §4.4, file 06 §2/§7/§8), with the plan and decisions unchanged: the approved `telemetry_runs`/`telemetry_channels` migration; the folder LJStreamM `.cfg` scaling as evidence on `UNIT_AMBIGUITY` (the file states no unit or quantity, so it is not a derived map); once every channel resolves through operator rules: `normalized.parquet` (SI, `t_rel_ms`, `t_from_ignition_ms`, separate `*_bar_abs`), t0 (§C.6), three-tier metrics, sanity bounds (S5's ranges), the commit through S2's `index_document`, and `resume_from_staged` from the run's own `raw.parquet`. Proposed rules (S5, `config/rules/proposed/`) are never applied.

## Workspace

Files to change (exact):
- `backend/postgres/models/telemetry.py`, `backend/postgres/models/__init__.py`, `backend/postgres/migrations/versions/0009_telemetry_catalog.py`
- `backend/routes/c_telemetry/{ljstream_cfg,normalize,run,pipeline}.py`
- `backend/indexing/commit.py`, `backend/review/staged.py`, `backend/review/rules.py`, `backend/dispatcher/contract.py` (evidence fields)
- `backend/celery_redis/tasks_process.py`
- `backend/tests/schema/test_m1_schema.py`, `backend/tests/unit/routes/c_telemetry/`, `backend/tests/unit/review/test_rules.py`, `backend/tests/unit/sync/conftest.py`
- `.wiki/backend/route-c-telemetry.md`, `.wiki/backend/index-commit.md`, `.wiki/backend/review-backend.md`, `docs/sessions/STATUS.md`

Out of scope: `config/rules/` (S5), the stack DB migration (S4), the review API resolve endpoint (next).

## Rubric for this task

- [x] (task) 0009 upgrades, downgrades, `alembic check` clean; schema tests cover both tables, CHECKs and cascade
- [x] (task) `.cfg` equations reach the flag evidence; the flag stays HARD
- [x] (task) normalization: units to SI, gauge kept and absolute separate, t0 within 10 ms on a synthetic firing, peak/50 ms/steady with the window stored, valve `open_threshold`, saturation, bounds → HARD
- [x] (task) commit: catalog rows, nodes, status ACTIVE/ACTIVE_WITH_SOFT_FLAGS, label collision renamed with CONFLICT SOFT
- [x] (task) resume from `raw.parquet` without the `.dat`; stale channel flags AUTO_RESOLVED; rule → halted runs it matches
- [x] `uv run pytest`, ruff check and format check pass (1,353 passed)
- [ ] live: 0009 on the stack (S4) and the stack image with step 2; then the first SME-confirmed rule resumes its runs
