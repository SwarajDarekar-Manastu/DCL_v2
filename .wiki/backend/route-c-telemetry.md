# Route C: telemetry, LabVIEW, spreadsheets, arrays

| Field | Value |
|-------|-------|
| Feature id | `backend/route-c-telemetry` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §7; 05 §4.4; 06 §4 |
| Last updated | 2026-10-21 |

## Purpose

Deterministic path from .dat/.tdms/.csv/.xlsx/.npy to normalized Parquet, telemetry catalog, three-tier stats, sub-runs, t0 alignment, and unit/schema flags.

## Location

Code:
- `backend/routes/c_telemetry/`
- `backend/common/units.py`

Tests and fixtures:
- `backend/tests/unit/routes/c_telemetry/`
- `backend/tests/fixtures/route_c/`

## Interfaces

Provides:
- telemetry_runs/telemetry_channels rows
- `normalized.parquet`
- run summary node

Consumes:
- rules (backend/review-backend)
- pint registry (quality/config-data)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/c_telemetry/`
- `backend/common/units.py`
- `backend/tests/unit/routes/c_telemetry/`
- `backend/tests/fixtures/route_c/`

## Rubric (what "done" means for this feature)

- [ ] DuckDB reproduces SME Excel peak/steady numbers within 0.5%
- [ ] Unknown unit or gauge/abs raises UNIT_AMBIGUITY HARD with a suggestion
- [ ] Pickle files are never loaded
- [ ] Files >1M rows stream through PyArrow within the queue memory limit
- [ ] Multiple firings in one file become sub-runs
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
