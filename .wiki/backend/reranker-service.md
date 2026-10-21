# Reranker service (bge-reranker-v2-m3, GPU)

| Field | Value |
|-------|-------|
| Feature id | `backend/reranker-service` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §5.4; 07 §4 T1 |
| Last updated | 2026-10-21 |

## Purpose

Cross-encoder scoring of top-50 candidates with margin reporting.

## Location

Code:
- `backend/llm_engine/local_models.py`

Tests and fixtures:
- `backend/tests/unit/llm_engine/local_models/`

## Interfaces

Provides:
- `/rerank`

Consumes:
- GPU container

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/local_models.py`
- `backend/tests/unit/llm_engine/local_models/`

## Rubric (what "done" means for this feature)

- [ ] Scores 50 pairs within the latency budget of file 07 §11
- [ ] Falls back cleanly when down (RRF order kept)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
