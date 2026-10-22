# Plan: backend/route-c-telemetry — adapters for .csv, .tdms, .xlsx and .cfg

| Field | Value |
|-------|-------|
| Feature | `backend/route-c-telemetry` (map: `.wiki/backend/route-c-telemetry.md`) |
| Session | S1 |
| Branch | claude/competent-brahmagupta-3a5541 |
| Opened | 2026-10-22 |
| Delete when | rubric below is green and the map page is updated |

## Intent

The remaining Route C kinds (file 03 §C.2–C.4, §C.0), so the 20 parked C documents of E1–E12 move (12 xlsx, 4 cfg, 2 csv, 2 tdms). The LabJack time-series path becomes generic over a series source (header lines, columns, units per channel), shared by `.dat`, `.tdms` and time-series `.csv`/sheet islands. Channel resolution order stays C.1 step 2: operator rule, then units the file states (header cell, TDMS `unit_string`), else HARD `UNIT_AMBIGUITY`. Tables (CSV below the time-series threshold, workbook islands) become HTML table nodes with row children; `.cfg` files become config documents. No decision changes; proposed rules are never applied.

## Workspace

Files to change (exact):
- `backend/routes/c_telemetry/{run,series,tdms,delimited,workbook,tables,config_file,pipeline}.py`
- `backend/dispatcher/adapters.py`, `backend/dispatcher/contract.py` (only if an evidence field is missing)
- `backend/celery_redis/tasks_process.py`
- `backend/tests/unit/routes/c_telemetry/`
- `.wiki/backend/route-c-telemetry.md`, `.wiki/backend/dispatcher-and-route-gating.md`, `docs/sessions/STATUS.md`

Out of scope: `backend/common/office.py` (S4: LibreOffice recalculation is called, not changed), `config/` (S5).

## Rubric for this task

- [ ] (task) generic series path: LabJack behaviour and tests unchanged
- [ ] (task) TDMS: groups/channels, time from a time channel, `wf_increment` or the group scan rate; `unit_string` resolves a channel; none → HARD with sibling CSV units as evidence
- [ ] (task) CSV: preamble kept as header lines, delimiter/decimal sniffed, units from header cells, time column parsed; ≥ 100 rows → series, else table
- [ ] (task) xlsx: cached values, recalculation when formulas lack cached values or hold errors, islands, hidden sheets, merged cells, dimensionless headers, table + row nodes; time-series islands → series
- [ ] (task) `.cfg`: INI, JSON or key=value parsed into a config document
- [ ] live: the 20 parked C documents processed on the stack after the redeploy; counts reported
- [ ] `uv run pytest`, ruff check and format check pass
