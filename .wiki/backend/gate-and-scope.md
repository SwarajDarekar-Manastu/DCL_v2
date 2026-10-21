# Junk gate, quarantine, download and processing scopes

| Field | Value |
|-------|-------|
| Feature id | `backend/gate-and-scope` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/02_phase1_ingestion_sync.md §3.1a, §4 |
| Last updated | 2026-10-21 |

## Purpose

Reject junk from Graph metadata (tiers 1–3), quarantine paths and secrets (tier 4), and hold items outside the download or processing scope without flags.

## Location

Code:
- `backend/sync/gate.py` (`GateConfig`, `GateInput`, `gate_item()` tiers 1–3, `folder_flags()`)
- `backend/sync/scope.py` (`in_scope()`, `HELD_BY_DOWNLOAD_SCOPE`)
- `config/gate.yaml` (planned; S5 owns `config/*.yaml`, schema in the gate.py docstring)
- Tier 4 (magic bytes, secret scan) arrives with `backend/sync/downloader.py` (planned)

Tests and fixtures:
- `backend/tests/unit/sync/test_gate.py`, `backend/tests/unit/sync/gate_test_config.yaml` (test copy of the file 02 §4 lists)
- `backend/tests/fixtures/gate/` (planned, S5)

## Interfaces

Provides:
- `gate_item(GateInput, GateConfig) -> Verdict | None` with reasons `T1:<segment>`, `T1:quarantine:<segment>`, `T2:<ending|name|prefix>`, `T3:empty|package|shortcut|size`
- `in_scope(scope, root_name, ancestor_folder_ids, path)`; empty scope = everything
- gate decision + reason per item
- HELD_BY_SCOPE handling

Consumes:
- pipeline_config keys sync.download_scope, processing.scope

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/sync/gate.py`
- `backend/sync/scope.py`
- `config/gate.yaml`
- `backend/tests/unit/sync/test_gate.py`
- `backend/tests/unit/sync/gate_test_config.yaml`
- `backend/tests/fixtures/gate/`

## Rubric (what "done" means for this feature)

- [ ] ~105k junk items rejected with a recorded reason, none downloaded
- [x] Data-like extensions under team folders are accepted (and junk under a Tier-1 path), unit-tested
- [x] Every rejection carries a reason in the file 05 format, unit-tested
- [ ] Widening a scope enqueues held items in batches
- [ ] Secret-pattern hit quarantines the blob under _restricted
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | Gate tiers 1–3 and the download-scope matcher as pure functions; 49 unit tests |

## Related

- `.wiki/index.md`
