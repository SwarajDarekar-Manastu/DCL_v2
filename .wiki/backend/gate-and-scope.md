# Junk gate, quarantine, download and processing scopes

| Field | Value |
|-------|-------|
| Feature id | `backend/gate-and-scope` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/02_phase1_ingestion_sync.md §3.1a, §4 |
| Last updated | 2026-10-21 |

## Purpose

Reject junk from Graph metadata (tiers 1–3), quarantine paths and secrets (tier 4), and hold items outside the download or processing scope without flags.

## Location

Code:
- `services/sync/gate.py`
- `services/sync/scope.py`
- `config/gate.yaml`

Tests and fixtures:
- `tests/unit/sync/test_gate.py`
- `tests/fixtures/gate/`

## Interfaces

Provides:
- gate decision + reason per item
- HELD_BY_SCOPE handling

Consumes:
- pipeline_config keys sync.download_scope, processing.scope

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/sync/gate.py`
- `services/sync/scope.py`
- `config/gate.yaml`
- `tests/unit/sync/test_gate.py`
- `tests/fixtures/gate/`

## Rubric (what "done" means for this feature)

- [ ] ~105k junk items rejected with a recorded reason, none downloaded
- [ ] Data-like extensions under team folders are accepted
- [ ] Widening a scope enqueues held items in batches
- [ ] Secret-pattern hit quarantines the blob under _restricted
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
