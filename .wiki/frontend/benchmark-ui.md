# Benchmark UI (suites, cases, runs, results, drilldown, compare, retrieval lab)

| Field | Value |
|-------|-------|
| Feature id | `frontend/benchmark-ui` |
| Status | in-progress (API and Console screens done; live runs wait for S2's runner, M10) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §5 |
| Last updated | 2026-10-22 |

## Purpose

Golden-suite management and regression dashboards with failure classes and trace drilldowns; draft approval from chat.

## Location

Code:
- `backend/benchmark/catalog.py` (S3: `CaseSpec` for `benchmark_cases.spec`, API models, queries over S1's benchmark tables; the runner, metrics and judge in this package are S2's)
- `backend/api/benchmark.py` (thin routes, prefix `/benchmark`)
- `frontend/console/src/routes/benchmark/` (`+page.svelte` suites, recent runs, compare picker, export; `suites/[suite]` cases and drafts to approve; `cases/[case_id]` editor and history, `new` creates; `runs/[run_id]` results dashboard; `compare`; `retrieval` lab)
- `frontend/console/src/lib/components/benchmark/` (`CaseEditor`, `ResultDrilldown`, `RetrievalLab`; logic in `case_form.ts`, `run_view.ts` (dashboard helpers, `runRequest`, `runProgress`, `isActive`, `POLL_MS`), `links.ts`)

Tests and fixtures:
- `backend/tests/unit/api/test_benchmark_routes.py` (roles, validation, Pipe-only drafts)
- `backend/tests/integration/api/test_benchmark.py` (real ParadeDB via `DCL_TEST_DATABASE_URL`)
- `frontend/console/tests/benchmark/` (form round trip of every CaseSpec field, dashboard helpers, Retrieval lab, editor, drilldown)

## Interfaces

Provides (viewer reads; reviewer writes):
- `GET /benchmark/suites` (case counts by status and category, last run with pass rate); `GET /benchmark/suites/{suite}/export`; `POST /benchmark/suites/{suite}/import` (counts created / versioned / unchanged)
- `GET /benchmark/cases?suite&status&category` (latest versions); `GET /benchmark/cases/{case_id}` (all versions); `POST /benchmark/cases`; `POST /benchmark/cases/{case_id}/versions` (an edit is a new version); `POST …/approve` (draft → active); `POST …/retire`
- `POST /benchmark/drafts` (signed Pipe identity only; Add-to-benchmark action; status `draft`, `source_trace_id` kept)
- `GET /benchmark/runs?suite&limit`; `POST /benchmark/runs` (snapshot `{case_id: version}` of the active cases or a subset; status `queued` for S2's runner); `GET /benchmark/runs/{run_id}` (run + per-case results); `POST …/cancel`
- `GET /benchmark/compare?base&head` (newly failing / passing / still failing, numeric aggregate deltas, config diff)
- `CaseSpec` (file 08 §5.3): language, paraphrases, expected_numeric {metric, value, unit, tolerance_pct}, expected_citations / must_not_cite {file_name | doc_id | standard_id, page}, expected_tools {tools, ordered}, expected_entities, retrieval_gold_anchors {doc_id, anchor `<kind>:<value>:<hash>`}, expected_behavior (5 values), clarification_answer; unknown keys are refused

Every authored change writes `audit_events` (entity_type `benchmark_case`: create, new_version, approve, retired, draft_from_chat).

Runs are started from the suite page (all active cases, or a picked subset in suite order) and from the case editor ("Run this case now", one case id), both over `POST /benchmark/runs`. A queued or running run page shows a progress bar (results against the case snapshot) and re-reads `GET /benchmark/runs/{id}` every 5 s until the status is final, in addition to live `run` events, so it does not depend on the runner publishing them.

Results dashboard: ribbon of aggregate keys (pass_rate, numeric_exactness, citation_recall, faithfulness, recall_at_8, recall_at_30, latency_p95_ms, cost_total) with deltas against a chosen baseline run, failure classes, pass counts per category, newly failing cases; drilldown reads the per-result metric keys agreed with S2 (numeric, citations, tools, faithfulness, recall_at_8/30, reranker_margin, judge_rationale, warnings) and links gold anchors to the viewer.

Consumes:
- S1 migration 0006 (`benchmark_cases`, `benchmark_runs`, `benchmark_results`, enums), S2 runner fills runs and results, S2 `POST /v1/retrieval/search` for the Retrieval lab, S5 golden suites (import format = `SuiteExport`)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/benchmark/catalog.py`
- `backend/api/benchmark.py`
- `frontend/console/src/routes/benchmark/`
- `frontend/console/src/lib/components/benchmark/`
- `frontend/console/src/lib/api_endpoint.ts` (benchmark section)
- `backend/tests/unit/api/test_benchmark_routes.py`, `backend/tests/integration/api/test_benchmark.py`
- `frontend/console/tests/benchmark/`

## Rubric (what "done" means for this feature)

- [x] Case versions are immutable; approve and retire are audited; chat drafts keep their source trace (integration tests)
- [x] A run snapshots the active case versions and stays queued for the runner
- [x] Runs start for a suite, a picked subset or one case; the run page shows progress and polls until the status is final (unit tests in `run_view.test.ts`)
- [x] Compare lists newly failing / passing cases with failure classes and aggregate deltas
- [ ] A deliberate regression is caught with the right failure class (needs S2's runner, M10)
- [ ] A re-index does not zero retrieval metrics (anchors resolve; needs the runner)
- [x] Console screens (suites, case editor, runs, results with baseline, drilldown, compare, retrieval lab); checked in the browser against a mock API, including a reranker-off regression shown as RERANK_MISS with the config diff
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S3 | Benchmark API and `CaseSpec` over migration 0006; unit and ParadeDB integration tests |
| 2026-10-22 | S3 | Console screens and Retrieval lab; live `run` topic refreshes run pages |
| 2026-10-22 | S3 | Subset and single-case runs, run progress bar, polling while queued or running |

## Related

- `.wiki/index.md`
- `quality/benchmark-suites` (S5 authors suites in the export format)
- `backend/answer-engine` (runner, benchmark mode, retrieval search)
- `frontend/openwebui-actions-skills` (Add to benchmark posts `/benchmark/drafts`)
