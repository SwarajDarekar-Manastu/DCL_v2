# Route C: telemetry, LabVIEW, spreadsheets, arrays

| Field | Value |
|-------|-------|
| Feature id | `backend/route-c-telemetry` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §7; 05 §4.4; 06 §4 |
| Last updated | 2026-10-23 |

## Purpose

Deterministic path from .dat/.tdms/.csv/.xlsx/.npy to normalized Parquet, telemetry catalog, three-tier stats, sub-runs, t0 alignment, and unit/schema flags.

## Location

Code:
- `backend/routes/c_telemetry/series.py` (the shared time-series path: `SeriesSource` (header lines, columns, stated units, batches), `resolve_channels` (operator rule → unit stated by the file → unresolved), `entry_from_unit`, `process_series`, `source_from_schema` for resume, run keys for several runs per file)
- `backend/routes/c_telemetry/tdms.py` (C.2: largest group, time from a time channel / `wf_increment` / `ScanRate`, `unit_string` incl. NI spellings, properties as header lines)
- `backend/routes/c_telemetry/delimited.py` (C.3: encoding, delimiter, decimal comma, preamble, footer, header units, time column incl. clock times; ≥ 100 rows → series, else table)
- `backend/routes/c_telemetry/workbook.py` (C.4: cached values, LibreOffice recalculation via S4's `office.convert`, islands, captions, merged/hidden sheets, percent, formula-error CONFLICT, time-series islands → runs)
- `backend/routes/c_telemetry/tables.py` (HTML table node + row children with the header repeated; units from headers, units rows or a Unit column; SOFT `UNIT_AMBIGUITY` except dimensionless headers; `table_document`)
- `backend/routes/c_telemetry/config_file.py` (`.cfg`/`.ini`: INI, JSON, key=value → `config` document)
- `backend/routes/c_telemetry/labjack.py` (LJStreamM layout: `parse_header`, `can_handle`, `is_voltage`, `read_batches` in Arrow batches)
- `backend/routes/c_telemetry/run.py` (LabJack wrapper over the series path; `process_labjack`: raw Parquet, streaming stats + quantiles, time base (actual rate, gaps, duplicates), channel resolution through `channel_map` rules, `UNIT_AMBIGUITY` HARD per unresolved channel, `schema.json` + `stats.json` in `dcl-cir/{sha}/C/v1/`, run summary node; `run_uuid_for(sha)` = uuid5)
- `backend/routes/c_telemetry/ljstream_cfg.py` (folder LJStreamM `.cfg`: scan rate, per-channel scaling equations, `linear()`; evidence only, it states no unit)
- `backend/routes/c_telemetry/normalize.py` (`plan_channel` → SI affine conversion, scaling/expression (arithmetic over `val` only), gauge kept + `*_bar_abs` when the ambient is known, valve `open_threshold` → 0/1; `normalize_run` → `normalized.parquet` with `t_rel_ms`, `t_from_ignition_ms`; `detect_t0` (pressure slope 20 ms, valve edge, temperature slope; confidence); `three_tier_metrics` (peak, 50 ms rolling peak, steady mean + window); saturation; S5's sanity ranges (first match))
- `backend/routes/c_telemetry/pipeline.py` (`process_document(session, minio, doc_id, indexer)`: primary blob, folder context, folder `.cfg`, rule target, rules, sanity ranges and `telemetry.*` config, gate (stale channel flags AUTO_RESOLVED), index + commit; `resume_document` from `raw.parquet` + `schema.json` header; `halted_documents_for_rule`)
- `backend/indexing/commit.py` (the commit for every route: entities, assets, nodes, mentions, facts, telemetry catalog, documents row; run-label collisions renamed with CONFLICT SOFT; `default_indexer` = S2's `index_document` via the models role)
- `backend/postgres/models/telemetry.py` + migration `0009_telemetry_catalog` (`telemetry_runs`, `telemetry_channels`)
- `backend/storage/parquet.py` (`write_batches`: 100k-row groups, ZSTD; `schema_with_metadata`; `telemetry_key`)
- `backend/review/staged.py` (validation gate, staged payload) and `backend/dispatcher/adapters.py` (registry entry `labjack_dat`)
- `backend/celery_redis/tasks_process.py` (`dcl.process.route_c`, `dcl.process.resume_route_c` on `telemetry_stream`; `dcl.process.resume_for_rule` on io_light; transient model/gateway errors retry, others leave the document FAILED)
- `backend/common/units.py` (pint registry + `config/units.txt`, S5 aliases, gauge/absolute from the spelling, canonical units, gauge → absolute)

Tests and fixtures:
- `backend/tests/unit/common/test_units.py`
- `backend/tests/unit/routes/c_telemetry/` (`test_adapters.py` (CSV, TDMS, workbooks, configs on synthetic files in the corpus layouts), `test_pipeline_adapters.py` (all kinds through dispatch and commit), `test_labjack.py`, `test_ljstream_cfg.py`, `test_normalize.py` (synthetic firing); `test_run.py` with MinIO; `test_pipeline.py` with PostgreSQL + MinIO incl. commit and resume; synthetic LJStreamM in `conftest.py`)
- `backend/tests/fixtures/route_c/`

## Interfaces

Provides:
- `parse_unit(text) -> ParsedUnit{unit, dimension, gauge_or_abs, canonical}` (raises `UnitError`), `to_canonical(value, unit) -> (value, unit)` in bar / N / K / g/s / W or base SI, `ambient_bar_abs(condition, recorded)`, `gauge_to_absolute()`, `has_dimension()`, `fits_quantity(unit, Quantity)` with `QUANTITY_DIMENSIONS` (used by S2's numeric-fact check); the `Quantity` vocabulary is in `backend/postgres/enums.py`
- `ProcessedDocument` with one `TelemetryRunRecord` (raw Parquet URI, schema URI, rates, gaps, per-channel stats) and the run summary node; `telemetry_runs`/`telemetry_channels` rows written by the commit
- `dcl-telemetry/{run_uuid}/raw.parquet` (original names, field metadata `raw_name`/`raw_unit`, file metadata `run_uuid`, `run_label`, `source_blob_sha256`, `parser_version`)
- `dcl-telemetry/{run_uuid}/normalized.parquet`: `t_rel_ms`, `t_from_ignition_ms` (null without t0), canonical SI columns, `*_bar_abs`, valve state 0/1; field metadata `raw_name`, `unit`, `quantity`, `gauge_or_abs`
- `telemetry_runs` / `telemetry_channels` (file 05 §4.4): t0 and method/confidence, ambient, three-tier metrics with `steady_window_ms`, `saturated`, `null_fraction`, `conversion`
- run summary node

Consumes:
- rules (backend/review-backend)
- pint registry (quality/config-data)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/c_telemetry/`
- `backend/storage/parquet.py`
- `backend/indexing/commit.py`
- `backend/postgres/models/telemetry.py`
- `backend/common/units.py`
- `backend/tests/unit/common/test_units.py`
- `backend/tests/unit/routes/c_telemetry/`
- `backend/tests/fixtures/route_c/`

## Rubric (what "done" means for this feature)

- [ ] DuckDB reproduces SME Excel peak/steady numbers within 0.5%
- [x] Unknown unit or gauge/abs raises UNIT_AMBIGUITY HARD with a suggestion (`suggest.py`; a unit only when a file states it, else an explicit no-suggestion; unit tests; live check after redeploy)
- [ ] Live: an SME-confirmed channel_map rule resumes its HALTED runs (`dcl.process.resume_for_rule`)
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
| 2026-10-22 | S1 | Live on the stack: 20 LabJack runs (4.94 M rows, 4,853 s, 256 MB raw Parquet, 1017.3 Hz, no gaps) HALTED with 160 UNIT_AMBIGUITY HARD; 0 FAILED |
| 2026-10-22 | S1 | Live: the 20 parked C documents processed (4 config ACTIVE; DAQ CSV 22 rows → table, 115 rows → first committed run, 8 thermocouple channels, weak-t0 CONFLICT SOFT; 2 TDMS HALTED with 8 HARD each; 12 workbooks indexed as tables, 3 ACTIVE, 9 with SOFT unit flags); 0 FAILED |
| 2026-10-22 | S1 | Adapters for .tdms, .csv, workbooks and .cfg on a shared series path; channels resolve by rule, then by the unit the file states; generic resume |
| 2026-10-22 | S1 | t0 on coarse data: sustain ≥ 2 samples, rise onset instead of the steep part (2 Hz DAQami; S2 report) |
| 2026-10-22 | S1 | `suggest.py`: every telemetry UNIT_AMBIGUITY gets `suggested_resolution` (stated raw unit 0.6, same-name sibling unit 0.5, unit in the channel name 0.4, else an explicit no-suggestion with the .cfg scaling); 5 tests |
| 2026-10-22 | S1 | Step 2: migration 0009, .cfg evidence, normalization, t0, metrics, bounds, commit, resume from raw.parquet, retroactive pass; 39 Route C tests |
| 2026-10-23 | S1 | Stable-anchor locators on table/table_row nodes (sheet + one-row cell_range; CSV file lines); first data row of tables with a Unit column no longer dropped; one-off `dcl.process.relocate_route_c_tables`; `test_locators.py` |
| 2026-10-23 | S1 | UNIT_AMBIGUITY evidence for the Review UI: `columns`, `column_index`, 20 `sample_rows`, `time_column`, ~200-point `series` streamed from raw.parquet (`raw_preview`, `with_preview`; under 50 KB per flag); one-off `dcl.process.refresh_halted_route_c` |

## Related

- `.wiki/index.md`
