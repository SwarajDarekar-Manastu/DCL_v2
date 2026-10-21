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
- `backend/sync/delta.py` (`seed_roots`, `run_root` crawl/delta with page checkpoints, `upsert_page`, `finalize_root` paths + gate + scope; 410 and forced resync with generation stamps and per-item 404 confirmation; CLI `crawl | resync`)
- `backend/sync/folder_listing.py` (S5's allowlist listing: folders.csv + library_pdfs.csv; CLI)
- `backend/celery_redis/tasks_sync.py` (io_light: `dcl.sync.delta_root` time-budgeted + self re-enqueue + per-root Redis lock, `dcl.sync.delta_all`, `dcl.sync.download` (3 attempts → DOWNLOAD_FAILED), `dcl.sync.enqueue_downloads`, `dcl.sync.token_health` (first-root probe))
- `backend/sync/webhooks.py` (planned)

Tests and fixtures:
- `backend/tests/unit/sync/test_auth.py`, `backend/tests/unit/sync/test_graph_client.py`, `backend/tests/unit/sync/test_delta.py`, `backend/tests/unit/sync/test_tasks_sync.py`, `backend/tests/unit/sync/conftest.py`
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
- `backend/sync/delta.py`
- `backend/sync/folder_listing.py`
- `backend/celery_redis/tasks_sync.py`
- `backend/tests/unit/sync/test_delta.py`
- `backend/tests/unit/sync/test_tasks_sync.py`
- `backend/tests/unit/sync/conftest.py`
- `backend/sync/webhooks.py`
- `backend/tests/unit/sync/`
- `backend/tests/integration/sync/`

## Rubric (what "done" means for this feature)

- [ ] Full metadata crawl of the four roots completes and records ~110k items
- [x] Items tracked by (drive_id,item_id); folder rename updates paths with zero downloads (unit-tested)
- [x] Crash mid-crawl resumes from the page checkpoint; 429/503 honor Retry-After (unit-tested; Redis-wide pause with the Celery task)
- [x] 410 resync produces no deletion without a per-item 404 check (unit-tested; drill: `python -m backend.sync.delta resync --root NAME`)
- [x] Outside-share item returns 403/404 in the negative test (live 2026-10-22: four roots 200, outside item 404)
- [x] Token cache Fernet-encrypted, mode 600 in a 700 dir, atomic replace; an undecryptable file (v1 cache) is refused and left untouched
- [x] Silent acquisition first; device-code sign-in as any account other than DCL_DELEGATED_USERNAME is rejected and not saved
- [x] Graph client has no write path; the token is only sent to graph.microsoft.com
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | MSAL auth with encrypted cache, GET-only Graph client, access check and CLI (28 unit tests); device flow verified live against the tenant with scope A |
| 2026-10-22 | S1 | Metadata crawl/delta (`delta.py`) and S5's folder listing; 10 tests; live crawl of the four roots run against a disposable DB |
| 2026-10-22 | S1 | Celery tasks (tasks_sync.py): budgeted delta with resume and lock, downloads, token health; 8 tests |
| 2026-10-22 | S1 | 410/forced resync in `delta.py` (no separate resync.py); generation = max(resync_gen)+1 per root committed with the first page |

## Related

- `.wiki/index.md`
