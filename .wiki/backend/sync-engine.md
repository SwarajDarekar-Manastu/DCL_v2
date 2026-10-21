# Graph sync engine (delta, webhooks, resync)

| Field | Value |
|-------|-------|
| Feature id | `backend/sync-engine` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/02_phase1_ingestion_sync.md §1–§3, §8 |
| Last updated | 2026-10-21 |

## Purpose

Enumerate the four shared OneDrive folders through Microsoft Graph delta, react to webhooks, run the daily safety delta, and recover from HTTP 410 with a generation-stamped resync.

## Location

Code:
- `backend/sync/graph_client.py` (GET-only Graph client; relative paths or absolute Graph links only)
- `backend/sync/auth.py` (encrypted MSAL cache, `TokenProvider` silent-first + device-code sign-in, `check_access`, CLI)
- `backend/sync/delta_runner.py` (planned)
- `backend/sync/webhooks.py` (planned)
- `backend/sync/resync.py` (planned)

Tests and fixtures:
- `backend/tests/unit/sync/test_auth.py`, `backend/tests/unit/sync/test_graph_client.py`
- `backend/tests/integration/sync/` (planned)

## Interfaces

Provides:
- `TokenProvider.create(GraphAuthConfig.from_settings(get_settings())).access_token` (raises `ReauthRequired`)
- `GraphClient(access_token)` with `.get(path_or_url, params)`; no write method exists
- `check_access(...)` → `AccessReport` (roots 200; outside item 403/404 from `DCL_TEST_OUTSIDE_DRIVE_ID`, default `DCL_DRIVE_ID`)
- operator CLI: `uv run python -m backend.sync.auth sign-in | check`
- delta runs per root
- sync_roots state
- webhook receiver endpoint

Consumes:
- env contract (platform/env-contract): Group.GRAPH incl. `DCL_TOKEN_CACHE_KEY` (Fernet), `DCL_TEST_OUTSIDE_DRIVE_ID`
- registry tables (backend/registry-and-blobs)
- queues (platform/compose-stack)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/sync/graph_client.py`
- `backend/sync/auth.py`
- `backend/sync/delta_runner.py`
- `backend/sync/webhooks.py`
- `backend/sync/resync.py`
- `backend/tests/unit/sync/`
- `backend/tests/integration/sync/`

## Rubric (what "done" means for this feature)

- [ ] Full metadata crawl of the four roots completes and records ~110k items
- [ ] Items tracked by (drive_id,item_id); folder rename updates paths with zero downloads
- [ ] 410 resync produces no deletion without a per-item 404 check
- [ ] 429/503 pauses all Graph calls process-wide for Retry-After
- [ ] Outside-share item returns 403/404 in the negative test (unit-proven: 403/404 pass, 200/401/500 fail; live run waits for the operator's one-time sign-in)
- [x] Token cache Fernet-encrypted, mode 600 in a 700 dir, atomic replace; an undecryptable file (v1 cache) is refused and left untouched
- [x] Silent acquisition first; device-code sign-in as any account other than DCL_DELEGATED_USERNAME is rejected and not saved
- [x] Graph client has no write path; the token is only sent to graph.microsoft.com
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | MSAL auth with encrypted cache, GET-only Graph client, access check and CLI (28 unit tests); device flow verified live against the tenant with scope A |

## Related

- `.wiki/index.md`
