# Benchmark UI (suites, cases, runs, results, drilldown, compare, retrieval lab)

| Field | Value |
|-------|-------|
| Feature id | `frontend/benchmark-ui` |
| Status | planned |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §5 |
| Last updated | 2026-10-21 |

## Purpose

Golden-suite management and regression dashboards with failure classes and trace drilldowns; draft approval from chat.

## Location

Code:
- `frontend/console/src/routes/benchmark/`
- `backend/api/benchmark.py`

Tests and fixtures:
- `frontend/console/tests/benchmark/`

## Interfaces

Provides:
- /benchmark/* API

Consumes:
- engine benchmark mode (backend/answer-engine)
- suites (quality/benchmark-suites)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/console/src/routes/benchmark/`
- `backend/api/benchmark.py`
- `frontend/console/tests/benchmark/`

## Rubric (what "done" means for this feature)

- [ ] A deliberate regression is caught with the right failure class
- [ ] A re-index does not zero retrieval metrics (anchors resolve)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
