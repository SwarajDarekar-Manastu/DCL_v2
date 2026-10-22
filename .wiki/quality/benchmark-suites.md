# Golden benchmark suites and verification notes

| Field | Value |
|-------|-------|
| Feature id | `quality/benchmark-suites` |
| Status | in-progress |
| Owner session | S5 |
| Spec | docs/architecture/08_frontend_openwebui.md §5.3, §5.7 |
| Last updated | 2026-10-22 |

## Purpose

The 60-case golden set across categories incl. MULTILINGUAL and LIBRARY_VS_INTERNAL, the 40-query retrieval set with gold anchors, verification scripts, hold-out subset.

## Location

Code:
- `backend/tests/benchmark/suites/telemetry.template.yaml` (questions, methods, units, tolerances; no values)
- `backend/tests/benchmark/suites/behaviour.template.yaml` (behaviour cases)
- `backend/tests/benchmark/suites/documents.template.yaml` (page-cited FACT_LOOKUP, FAILURE_ANALYSIS)
- `backend/tests/benchmark/suites/code.template.yaml` (CODE)
- `backend/tests/benchmark/verification/build_suites.py` (template + local fragments → importable suite)
- `backend/tests/benchmark/verification/telemetry_metrics.py` (metric functions, `build`)
- `backend/tests/benchmark/verification/README.md` (verification notes)
- `backend/tests/benchmark/retrieval_set.yaml` (planned)
- local, git-ignored: `data/benchmark/telemetry_sources.yaml`, `data/benchmark/*.local.yaml`, `data/benchmark/*.json` (values, citations)

Tests and fixtures:
- `backend/tests/benchmark/test_telemetry_suite.py`
- `backend/tests/benchmark/test_suites.py`

## Interfaces

Provides:
- suites in S3's import format (`POST /benchmark/suites/{suite}/import`), built locally with values; the M10 TELEMETRY_MATH gate runs on the stack host

Consumes:
- anchors (S2: `Anchor.serialize()` + doc_id)
- benchmark UI and `CaseCreate` model (S3, `backend/benchmark/catalog.py`)
- real samples (`quality/fixtures`)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/tests/benchmark/suites/telemetry.template.yaml`
- `backend/tests/benchmark/verification/telemetry_metrics.py`
- `backend/tests/benchmark/verification/README.md`
- `backend/tests/benchmark/suites/behaviour.template.yaml`
- `backend/tests/benchmark/suites/documents.template.yaml`
- `backend/tests/benchmark/suites/code.template.yaml`
- `backend/tests/benchmark/verification/build_suites.py`
- `backend/tests/benchmark/test_telemetry_suite.py`
- `backend/tests/benchmark/test_suites.py`
- `backend/tests/benchmark/retrieval_set.yaml`

## Rubric (what "done" means for this feature)

- [x] Every numeric case has an independent verification note (15 telemetry cases; TP7 cross-checked with the team workbook)
- [x] Hold-out subset recorded in DECISIONS.md (3 telemetry cases)
- [x] Behaviour cases: 2 halt (telemetry suite) + 6 (insufficient evidence ×2, out of scope, clarification, external labelling ×2)
- [ ] CONFLICT_BEHAVIOR case (needs two indexed documents that disagree)
- [x] 12 FACT_LOOKUP + 3 FAILURE_ANALYSIS (TP-23, TP12 reports) and 8 CODE cases; every answer found in the cited page or file by a test
- [ ] Visual/handwriting (5 more failure/visual), STANDARDS (E12 globs, after indexing), MULTILINGUAL, CONFLICT and the 40-query retrieval set
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S5 | documents suite (15) and code suite (8); `test_cited_pages_contain_the_answer` checks each answer in the cited page or source file; `verify_paths.yaml` settles shared file names |
| 2026-10-22 | S5 | behaviour suite (6 cases) and the generic suite builder; tool names checked against the engine's ToolName |
| 2026-10-22 | S5 | precondition (confirmed channel map, resolved bounds cases) in every numeric case's notes; hold-out recorded by the Lead |
| 2026-10-22 | S5 | First 15 TELEMETRY_MATH cases + 2 HALTED_DATA_BEHAVIOR cases; values local (option b); verification by telemetry_metrics.py, recompute test |

## Related

- `.wiki/index.md`
