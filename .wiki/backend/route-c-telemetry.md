# Route C: telemetry, LabVIEW, spreadsheets, arrays

| Field | Value |
|-------|-------|
| Feature id | `backend/route-c-telemetry` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §7; 05 §4.4; 06 §4 |
| Last updated | 2026-10-22 |

## Purpose

Deterministic path from .dat/.tdms/.csv/.xlsx/.npy to normalized Parquet, telemetry catalog, three-tier stats, sub-runs, t0 alignment, and unit/schema flags.

## Location

Code:
- `backend/routes/c_telemetry/labjack.py` (LJStreamM layout: `parse_header`, `can_handle`, `is_voltage`, `read_batches` in Arrow batches)
- `backend/routes/c_telemetry/run.py` (`process_labjack`: raw Parquet, streaming stats + quantiles, time base (actual rate, gaps, duplicates), channel resolution through `channel_map` rules, `UNIT_AMBIGUITY` HARD per unresolved channel, `schema.json` + `stats.json` in `dcl-cir/{sha}/C/v1/`, run summary node; `run_uuid_for(sha)` = uuid5)
- `backend/routes/c_telemetry/pipeline.py` (`process_document(session, minio, doc_id)`: primary blob, folder context, rule target, rules, gate; a clean run is kept as `processed.json` and parked until the commit path)
- `backend/storage/parquet.py` (`write_batches`: 100k-row groups, ZSTD; `schema_with_metadata`; `telemetry_key`)
- `backend/review/staged.py` (validation gate, staged payload) and `backend/dispatcher/adapters.py` (registry entry `labjack_dat`)
- `backend/celery_redis/tasks_process.py` (`dcl.process.route_c` on `telemetry_stream`)
- `backend/common/units.py` (pint registry + `config/units.txt`, S5 aliases, gauge/absolute from the spelling, canonical units, gauge → absolute)

Tests and fixtures:
- `backend/tests/unit/common/test_units.py`
- `backend/tests/unit/routes/c_telemetry/` (`test_labjack.py`; `test_run.py` with MinIO; `test_pipeline.py` with PostgreSQL + MinIO; synthetic LJStreamM in `conftest.py`)
- `backend/tests/fixtures/route_c/`

## Interfaces

Provides:
- `parse_unit(text) -> ParsedUnit{unit, dimension, gauge_or_abs, canonical}` (raises `UnitError`), `to_canonical(value, unit) -> (value, unit)` in bar / N / K / g/s / W or base SI, `ambient_bar_abs(condition, recorded)`, `gauge_to_absolute()`, `has_dimension()`, `fits_quantity(unit, Quantity)` with `QUANTITY_DIMENSIONS` (used by S2's numeric-fact check); the `Quantity` vocabulary is in `backend/postgres/enums.py`
- `ProcessedDocument` with one `TelemetryRunRecord` (raw Parquet URI, schema URI, rates, gaps, per-channel stats) and the run summary node; `telemetry_runs`/`telemetry_channels` rows come with the step 2 migration
- `dcl-telemetry/{run_uuid}/raw.parquet` (original names, field metadata `raw_name`/`raw_unit`, file metadata `run_uuid`, `run_label`, `source_blob_sha256`, `parser_version`)
- `normalized.parquet` (step 2)
- run summary node

Consumes:
- rules (backend/review-backend)
- pint registry (quality/config-data)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/c_telemetry/`
- `backend/storage/parquet.py`
- `backend/common/units.py`
- `backend/tests/unit/common/test_units.py`
- `backend/tests/unit/routes/c_telemetry/`
- `backend/tests/fixtures/route_c/`

## Rubric (what "done" means for this feature)

- [ ] DuckDB reproduces SME Excel peak/steady numbers within 0.5%
- [ ] Unknown unit or gauge/abs raises UNIT_AMBIGUITY HARD with a suggestion (HARD with header lines and stats done for LabJack; the suggestion comes with the derived rules)
- [ ] Pickle files are never loaded
- [x] Files >1M rows stream through PyArrow within the queue memory limit (live dry run: 628 MB, 3.79 M rows, 3.7 s)
- [ ] Multiple firings in one file become sub-runs
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | backend/common/units.py (registry, aliases, references, canonical units); 29 tests |
| 2026-10-21 | S1 | Quantity vocabulary + fits_quantity(); entity/alias/fact enums for S2 |
| 2026-10-22 | S1 | Step 1, LabJack .dat/.dat_fail: raw Parquet, stats, channel_map lookup, UNIT_AMBIGUITY HARD, halt with staged payload, `dcl.process.route_c`; 11 tests |

## Related

- `.wiki/index.md`
