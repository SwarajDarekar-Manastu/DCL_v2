# Reranker service (bge-reranker-v2-m3, GPU)

| Field | Value |
|-------|-------|
| Feature id | `backend/reranker-service` |
| Status | done |
| Owner session | S2 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §5.4; 07 §4 T1, §11, §12 |
| Last updated | 2026-10-21 |

## Purpose

Cross-encoder scoring of the top-50 candidates with margin reporting (rank 1 minus rank 5, the retrieval-confidence signal stored in the trace).

## Location

Code:
- `backend/llm_engine/local_models.py` (loaded with the embedding model, same process)
- `backend/api/models.py`

Tests and fixtures:
- `backend/tests/unit/llm_engine/local_models/`

## Interfaces

Provides:
- `POST /rerank` `{query, passages: [...]}` (≤ 100) → `{model: "BAAI/bge-reranker-v2-m3", scores, order, margin_1_5}`; `order` is passage indexes best first; `margin_1_5` is null below 5 passages
- Python: `ModelsClient.rerank(query, passages) -> RerankResult`; raises `ModelServerUnavailable` when the models role is down, so retrieval keeps the RRF order and notes it in the trace (file 07 §12)

Consumes:
- GPU container

## Measured latency (2026-10-21, RTX 5060 shared, bfloat16, max_length 512)

| 50 pairs, passage size | p50 | p95 |
|------------------------|-----|-----|
| ~325 tokens (typical child) | 349 ms | 351 ms |
| ~400 tokens (largest child) | 431 ms | 434 ms |

The rerank budget in file 07 §11 is 0.4 s; typical children fit, the largest children exceed it by ~8% on this card.

## Workspace (files to touch when modifying this feature)

- `backend/llm_engine/local_models.py`
- `backend/api/models.py`
- `backend/tests/unit/llm_engine/local_models/`

## Rubric (what "done" means for this feature)

- [x] Scores 50 pairs within the latency budget of file 07 §11 (typical child size; see the table for the largest)
- [x] Falls back cleanly when down: client raises `ModelServerUnavailable` within its timeout (`test_models_router_and_client.py`); RRF order is kept by `backend/retrieval`
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S2 | Built `/rerank` and `ModelsClient.rerank`; latency measured on the real GPU |

## Related

- `backend/embedding-service`
- `backend/retrieval` (calls rerank, keeps RRF order on `ModelServerUnavailable`)
- `.wiki/index.md`
