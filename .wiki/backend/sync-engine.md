# Graph sync engine (delta, webhooks, resync)

| Field | Value |
|-------|-------|
| Feature id | `backend/sync-engine` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/02_phase1_ingestion_sync.md §1–§3, §8 |
| Last updated | 2026-10-21 |

## Purpose

Enumerate the four shared OneDrive folders through Microsoft Graph delta, react to webhooks, run the daily safety delta, and recover from HTTP 410 with a generation-stamped resync.

## Location

Code:
- `services/sync/graph_client.py`
- `services/sync/auth.py`
- `services/sync/delta_runner.py`
- `services/sync/webhooks.py`
- `services/sync/resync.py`

Tests and fixtures:
- `tests/unit/sync/`
- `tests/integration/sync/`

## Interfaces

Provides:
- delta runs per root
- sync_roots state
- webhook receiver endpoint

Consumes:
- env contract (platform/env-contract)
- registry tables (backend/registry-and-blobs)
- queues (platform/compose-stack)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/sync/graph_client.py`
- `services/sync/auth.py`
- `services/sync/delta_runner.py`
- `services/sync/webhooks.py`
- `services/sync/resync.py`
- `tests/unit/sync/`
- `tests/integration/sync/`

## Rubric (what "done" means for this feature)

- [ ] Full metadata crawl of the four roots completes and records ~110k items
- [ ] Items tracked by (drive_id,item_id); folder rename updates paths with zero downloads
- [ ] 410 resync produces no deletion without a per-item 404 check
- [ ] 429/503 pauses all Graph calls process-wide for Retry-After
- [ ] Outside-share item returns 403/404 in the negative test
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
