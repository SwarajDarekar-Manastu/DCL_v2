# Hybrid retrieval (dense exact/HNSW, BM25 per language, RRF, rerank, parent expansion)

| Field | Value |
|-------|-------|
| Feature id | `backend/retrieval` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/07_phase3_answer_engine.md §4 T1; 04 §5–§6 |
| Last updated | 2026-10-21 |

## Purpose

search_documents implementation: alias expansion, exact-distance path for selective filters, HNSW with iterative scan otherwise, BM25 over per-language fields and content_codes, RRF k=60, rerank, near-duplicate collapse, stable anchors in results.

## Location

Code:
- `backend/indexing/retrieval.py`
- `backend/indexing/bm25_ddl.sql`

Tests and fixtures:
- `backend/tests/integration/retrieval/`
- `backend/tests/benchmark/retrieval_set.yaml`

## Interfaces

Provides:
- search_documents()
- retrieval lab endpoint data

Consumes:
- embedding-service
- reranker-service
- schema (BM25 index DDL via S1)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/indexing/retrieval.py`
- `backend/indexing/bm25_ddl.sql`
- `backend/tests/integration/retrieval/`
- `backend/tests/benchmark/retrieval_set.yaml`

## Rubric (what "done" means for this feature)

- [ ] recall@30 ≥0.9 on the SME query set incl. cross-lingual queries
- [ ] Identifier queries hit lexically
- [ ] Filtered searches on one test plan return k results
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
