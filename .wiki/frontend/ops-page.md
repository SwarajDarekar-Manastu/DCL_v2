# Ops page (failed tasks; sync, queues and cost to follow)

| Field | Value |
|-------|-------|
| Feature id | `frontend/ops-page` |
| Status | in-progress (Failed tasks done; sync status, queue depths, cost today, halted/soft counts and last benchmark pass rate not built) |
| Owner session | S3 (`backend/api/ops.py` by Lead ruling 2026-10-22) |
| Spec | docs/architecture/08_frontend_openwebui.md §4.2 (OpsPage), §4.4; 10_development_plan.md §4 (dead-letter queue) |
| Last updated | 2026-10-22 |

## Purpose

One Console page for operators: what failed, what is queued, what sync is doing and what today cost.

## Location

Code:
- `backend/api/ops.py` (`GET /ops/failed-tasks`; `FailedTask`, `FailedTasks`; `get_dead_letter_reader` imports S4's `backend.celery_redis.app.dead_letters` only when called)
- `backend/main.py` (router listed in `API_ROUTERS`; Lead's file, single-line change accepted)
- `frontend/console/src/routes/ops/+page.svelte` (Failed tasks section, admin only, Refresh)
- `frontend/console/src/lib/components/ops/FailedTasks.svelte`
- `frontend/console/src/lib/api_endpoint.ts` (`listFailedTasks`)

Tests and fixtures:
- `backend/tests/unit/api/test_ops_route.py`
- `frontend/console/tests/ops/FailedTasks.test.ts`, `frontend/console/tests/api_endpoint.test.ts` (`listFailedTasks`)

## Interfaces

Provides:
- `GET /ops/failed-tasks?limit=100` (admin; 1–500) → `{items: [{task_id, task, queue, args, kwargs, error, retries, at}]}` newest first. `args`/`kwargs` are the shortened reprs S4 stores. Malformed entries are skipped with a warning; Redis unreachable → 503 "the failed-task list is unavailable".
- No retry. A retry route comes only if S4 stores replayable args (Lead ruling).

Consumes:
- `dead_letters(limit)` over Redis list `dcl:dead_letter` (`backend/celery_redis/app.py`, S4)

## Workspace (files to touch when modifying this feature)

- `backend/api/ops.py`, `backend/tests/unit/api/test_ops_route.py`
- `frontend/console/src/routes/ops/`
- `frontend/console/src/lib/components/ops/`
- `frontend/console/src/lib/api_endpoint.ts` (ops section)
- `frontend/console/tests/ops/`

## Rubric (what "done" means for this feature)

- [x] Failed tasks: admin only (401/403), limit 1–500, newest first, malformed entries skipped, Redis down → 503 (unit tests)
- [x] Importing the router does not build the Celery app (subprocess test)
- [x] Console lists failed tasks with error and stored args, empty state (component test); live read against the stack's Redis returns without error
- [ ] Sync status per root, queue depths, cost today, halted/soft counts, last benchmark pass rate (file 08 §4.2)
- [ ] Retry (only if S4 stores replayable args)

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-22 | S3 | Map created; `GET /ops/failed-tasks` and the Failed tasks section |

## Related

- `.wiki/index.md`
- `platform/observability` (queue metrics), `backend/sync-engine` (sync status)
- `frontend/console-shell-auth` (ops topic on the live channel)
