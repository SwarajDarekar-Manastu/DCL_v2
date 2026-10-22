# Benchmark runner, metrics and judge

| Field | Value |
|-------|-------|
| Feature id | `backend/benchmark-runner` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/08_frontend_openwebui.md §5.4, §5.6; 10_development_plan.md M10 |
| Last updated | 2026-10-23 |

## Purpose

Executes a queued benchmark run (created by S3's `POST /benchmark/runs`) case by case through the Answer Engine's own workflow, scores every case with the metric rules of file 08 §5.4, classifies failures, writes `benchmark_results`, keeps the run aggregate and status current, and publishes `run` websocket events.

## Location

Code:
- `backend/benchmark/metrics.py` (pure: `Observed`, `quantities`, `numeric_exactness`, `citation_scores`, `tool_trajectory`, `retrieval_recall`, `behaviour`, `needs_judge`, `score_case`, `classify`, `aggregate`)
- `backend/benchmark/judge.py` (`judge(client, expectation, question, answer, sources)`; prompt `backend/llm_engine/prompts/benchmark/judge.v1.md`)
- `backend/benchmark/runner.py` (`RunnerDeps`, `start`, `run_one`, `complete_if_done`, `fail`, `run_benchmark`, `workflow_answer`, `default_deps`)
- `backend/benchmark/tasks.py` (Celery on `io_light`: `dcl.benchmark.start`, `dcl.benchmark.case`, `dcl.benchmark.sweep`)
- `backend/api/engine.py` `engine_deps(settings)` (shared with the API's `start_engine`)

Tests:
- `backend/tests/unit/benchmark/test_metrics.py`, `test_judge.py`
- `backend/tests/integration/benchmark/test_runner_db.py` (DCL_TEST_DATABASE_URL; S3's catalog creates the cases and the run)
- `backend/tests/unit/llm_engine/engine/test_workflow.py::test_benchmark_answers_take_the_chat_path_and_mock_makes_no_network_call`

## Interfaces

Provides:
- Run lifecycle: `queued` → `running` (claim; model config, pipeline version and ACTIVE document count snapshotted) → `completed` when every snapshotted case has a result (exactly one writer wins), or `failed` (start error, in `aggregate.error`); a `cancelled` run stops: cases not started are skipped, a case finishing after the cancel is dropped
- `benchmark_results` per case: `passed`, `failure_class`, `latency_ms`, `cost_estimate`, `trace_id`, `metrics` (`numeric{details,unit_error,verifier_dropped}`, `citations{recall,precision,forbidden_cited}`, `tools{expected,actual,missing}`, `entities`, `behavior{checks}`, `provenance_labeling`, `out_of_scope`, `faithfulness`, `retrieval{recall_at_30,recall_at_8,rerank_margin}`, `mode`, `latency_ms`, `failure_class`); a case whose engine call raised is `passed=false` with `metrics.error`
- `benchmark_runs.aggregate`: `cases_total`, `cases_done`, `pass_rate`, `numeric_exactness`, `citation_recall`, `faithfulness`, `retrieval_recall_at_8`, `retrieval_recall_at_30`, `latency_p50_ms`, `latency_p95_ms`, `cost_total`, `failure_classes`, `by_category`
- Websocket topic `run`, key = run id: `progress` (start; then per case `{case_id, passed, failure_class, cases_done, cases_total, pass_rate}`), `finished` (`{status, …aggregate}`)
- Benchmark answers: `AnswerWorkflow` in process (same code path as chat), caller groups `dcl-benchmark` + the external-allowed groups, external mode `mock` (canned results, no network); a clarification is answered once from `spec.clarification_answer` unless the case expects `must_clarify`
- Metric rules chosen where the manual is open: tools = every expected tool called (ordered when asked), extra tools allowed; numbers read from entailed claims, units converted with pint, gauge never converts to absolute; retrieval gold found by same document and same content hash or same locator; recall@30 from a pre-rerank search (k=30), recall@8 from a reranked search (k=8), both over the question without filters; judge (Gemini) only for `must_present_both_conflicting_values` and LIBRARY_VS_INTERNAL provenance labeling, everything else deterministic
- Failure class order: MISSING_DOCUMENT (an expected citation or gold anchor with no ACTIVE document, by doc_id, standard_id, title or drive item name) → BEHAVIOR_FAIL → RETRIEVAL_MISS (gold anchors) → RERANK_MISS → TOOL_MISROUTE → TOOL_ERROR → INSUFFICIENT_EVIDENCE (mode `insufficient_evidence` not asked for) → RETRIEVAL_MISS (no tool returned an expected document) → UNIT_ERROR → VERIFIER_FALSE_NEGATIVE → SYNTHESIS_ERROR; a case whose engine call raised or timed out is ENGINE_ERROR. The three new classes need S1's FailureClass/CHECK update
- Celery case tasks run their coroutines on one process-wide event loop (`tasks.run_async`); `asyncio.run` per task broke the shared gateway client on the first scored run

Consumes:
- `backend/benchmark/catalog.py` (S3: `CaseSpec`, the queued run with its case snapshot)
- `backend/answer-engine` (workflow, trace with tool calls, citations, claims and verdicts)
- `backend/retrieval` (`search`)
- `platform/gemini-gateway-client`, `platform/compose-stack` (io_light worker, Redis), websocket bridge (S3 `backend/api/ws.py`)

## Workspace (files to touch when modifying this feature)

- `backend/benchmark/metrics.py`, `judge.py`, `runner.py`, `tasks.py`
- `backend/llm_engine/prompts/benchmark/`
- `backend/tests/unit/benchmark/`, `backend/tests/integration/benchmark/`

## Rubric (what "done" means for this feature)

- [x] A queued run completes: one result per case, aggregate, `progress` per case and one `finished` event (`test_runner_db.py`)
- [x] Redelivery resumes without redoing recorded cases; a final run is left alone; cancel stops between cases and drops the case in flight (`test_runner_db.py`)
- [x] Sweep starts a queued run once, resumes a run whose heartbeat expired; a duplicate case task does nothing (`test_runner_db.py`)
- [x] Metric rules and failure classes (`test_metrics.py`, 17 tests); judge call and outage (`test_judge.py`)
- [x] Benchmark mock mode makes no network call (`test_workflow.py`)
- [ ] Wired in the stack: `backend.benchmark.tasks` in `TASK_MODULES` and a beat entry for `dcl.benchmark.sweep` (S4)
- [ ] The 60-case suite runs on the stack host (M10, S5's golden values)

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | S2 | After the first scored run (56 cases, 38 errors): one event loop per worker process for case tasks; failure classes MISSING_DOCUMENT, INSUFFICIENT_EVIDENCE, ENGINE_ERROR and RETRIEVAL_MISS without gold anchors; 1 + 1 unit tests, DB test extended |
| 2026-10-23 | S2 | Runner, metrics, judge, Celery tasks; 17 + 2 unit, 4 DB, 1 workflow tests |

## Related

- `frontend/benchmark-ui`, `quality/benchmark-suites`, `backend/answer-engine`, `backend/retrieval`
