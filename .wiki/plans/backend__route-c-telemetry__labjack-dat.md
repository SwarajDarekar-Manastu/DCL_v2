# Plan: backend/route-c-telemetry — LabJack .dat/.dat_fail: raw Parquet, stats, channel map, HARD flags, halt

| Field | Value |
|-------|-------|
| Feature | `backend/route-c-telemetry` (map: `.wiki/backend/route-c-telemetry.md`) |
| Session | S1 |
| Branch | claude/competent-brahmagupta-3a5541 |
| Opened | 2026-10-22 |
| Delete when | rubric below is green and the map page is updated |

## Intent

Step 1 of Route C (file 03 §C.1, §C.0 lookup side, file 06 §2/§7): the adapter recognizes the real LJStreamM layout seen in the crawl (date line, time line, blank lines, tab header `Time v0… y0…`); the run streams into `dcl-telemetry/{run_uuid}/raw.parquet` (original names, ZSTD, 100k-row groups, file metadata of file 05 §2); `run_uuid` = uuid5 of the blob SHA-256; per-column stats (n, min, max, mean, std, p50, p99, nulls), actual sampling rate, gaps and duplicate timestamps; `run_label` from folder context; `.dat_fail` → `FAILED_RUN`. Channels: `v*` are LabJack voltages (unit V, no flag); every `y*` and any other column must resolve through `channel_map` rules (resolver of `backend/review/rules.py`); an unresolved channel raises HARD `UNIT_AMBIGUITY` with header lines and stats as evidence. Any HARD flag → the validation gate halts: staged payload (`ProcessedDocument`) in `dcl-cir/{sha}/staged.json`, flags upserted, document HALTED, no telemetry rows. Dispatch hands documents whose adapter matches to the `telemetry_stream` queue when `routes.C.enabled`. Normalized Parquet, t0, three-tier metrics, catalog rows and the commit follow in step 2 (after the first mapping).

## Workspace

Files to change (exact):
- `backend/routes/c_telemetry/labjack.py`, `run.py`, `pipeline.py`, `__init__.py`
- `backend/dispatcher/adapters.py` (registry)
- `backend/review/rules.py` (`resolve_where`), `backend/storage/minio.py` (`put_file`, `open`)
- `backend/storage/parquet.py`
- `backend/review/staged.py` (validation gate halt)
- `backend/dispatcher/routing.py` (adapter registry, re-dispatch of parked documents)
- `backend/celery_redis/tasks_process.py` (`dcl.process.route_c`)
- `backend/tests/unit/routes/c_telemetry/` (conftest, test_labjack, test_run, test_pipeline), `backend/tests/unit/sync/conftest.py` (clear `rules`)
- `pyproject.toml`, `uv.lock`
- `.wiki/backend/route-c-telemetry.md`, `.wiki/backend/review-backend.md`, `.wiki/backend/dispatcher-and-route-gating.md`, `.wiki/backend/registry-and-blobs.md`, `docs/sessions/STATUS.md`

## Rubric for this task

- [ ] (map) every allowlisted .dat produces Parquet + a UNIT_AMBIGUITY case (no SI columns until mapped)
- [x] (task) header parsed exactly; stats equal a direct numpy computation; actual rate from timestamps
- [x] (task) run_uuid stable per content; .dat_fail → FAILED_RUN
- [x] (task) a channel_map rule for the folder resolves a channel and removes its flag
- [x] (task) HALTED with staged payload that round-trips as ProcessedDocument; flags upserted by fingerprint (re-run: same rows)
- [ ] live: the E1–E11 .dat documents processed; counts reported
- [x] `uv run pytest`, ruff check and format check pass
