# Ops page (failed tasks; sync, queues and cost to follow)

| Field | Value |
|-------|-------|
| Feature id | `frontend/ops-page` |
| Status | in-progress (failed tasks, queue depths, documents by status, open flags, last run per suite, model calls today done; sync status per root waits for S1) |
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
- `frontend/console/src/lib/components/ops/FailedTasks.svelte`, `OpsOverview.svelte` (summary panels; refresh every 30 s and on live review/run events)
- `frontend/console/src/lib/api_endpoint.ts` (`listFailedTasks`)

Tests and fixtures:
- `backend/tests/unit/api/test_ops_route.py`
- `frontend/console/tests/ops/FailedTasks.test.ts`, `frontend/console/tests/api_endpoint.test.ts` (`listFailedTasks`)

## Interfaces

Provides:
- `GET /ops/failed-tasks?limit=100` (admin; 1–500) → `{items: [{task_id, task, queue, args, kwargs, error, retries, at}]}` newest first. `args`/`kwargs` are the shortened reprs S4 stores. Malformed entries are skipped with a warning; Redis unreachable → 503 "the failed-task list is unavailable".
- No retry (deferred by the Lead).
- `GET /ops/summary` (viewer) → `{queues: [{queue, waiting}], documents_by_status, open_flags: {HARD, SOFT}, last_runs: [{suite, run_id, status, pass_rate, cases_done, cases_total, started_at, finished_at}], llm_today: {calls, input_tokens, output_tokens, cached_tokens, cost_estimate}, notes: {part: reason}}`. Queue depth = Redis `LLEN` per Celery queue (same as S4's gauge); flags counted open = OPEN, IN_PROGRESS, REOPENED; `llm_today` from `llm_calls` since 00:00 UTC (file 05 columns) once S1's model exists. Each part is read on its own: an unreadable part is null with a note.

Consumes:
- `dead_letters(limit)` over Redis list `dcl:dead_letter` (`backend/celery_redis/app.py`, S4)

## Workspace (files to touch when modifying this feature)

- `backend/api/ops.py`, `backend/tests/unit/api/test_ops_route.py`, `backend/tests/integration/api/test_ops_summary.py`
- `frontend/console/src/routes/ops/`
- `frontend/console/src/lib/components/ops/`
- `frontend/console/src/lib/api_endpoint.ts` (ops section)
- `frontend/console/tests/ops/`

## Rubric (what "done" means for this feature)

- [x] Failed tasks: admin only (401/403), limit 1–500, newest first, malformed entries skipped, Redis down → 503 (unit tests)
- [x] Importing the router does not build the Celery app (subprocess test)
- [x] Console lists failed tasks with error and stored args, empty state (component test); live read against the stack's Redis returns without error
- [x] Queue depths, documents by status, open HARD/SOFT flags, last run per suite (unit tests, integration test on the real schema, in-process run on the stack data)
- [x] Model calls, tokens and cost today from the live `llm_calls` (0012 applied; integration test sums today only)
- [ ] Sync status per root (needs S1)
- [ ] Retry (only if S4 stores replayable args)

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | S3 | Model calls today read from the live `llm_calls` (0012); integration test |
| 2026-10-23 | S3 | `GET /ops/summary` and the overview panels (queues, documents, open flags, last runs, model calls today) |
| 2026-10-22 | S3 | Map created; `GET /ops/failed-tasks` and the Failed tasks section |

## Related

- `.wiki/index.md`
- `platform/observability` (queue metrics), `backend/sync-engine` (sync status)
- `frontend/console-shell-auth` (ops topic on the live channel)
