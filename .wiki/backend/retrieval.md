# Hybrid retrieval (dense exact/HNSW, BM25 per language, RRF, rerank, parent expansion)

| Field | Value |
|-------|-------|
| Feature id | `backend/retrieval` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/07_phase3_answer_engine.md §4 T1; 04 §5–§6 |
| Last updated | 2026-10-22 |

## Purpose

search_documents implementation: alias expansion, exact-distance path for selective filters, HNSW with iterative scan otherwise, BM25 over per-language fields and content_codes, RRF k=60, rerank, near-duplicate collapse, stable anchors in results.

## Location

Code:
- `backend/indexing/retrieval.py` (`search`, `SearchFilters`, `Scope`, `Hit`, `SearchResult`, legs, RRF, collapse)
- BM25 DDL: S1's pinned migration (sent 2026-10-22; until it lands the test creates it from `backend/tests/integration/retrieval/bm25_ddl_sent_to_s1.sql`)

Tests and fixtures:
- `backend/tests/integration/retrieval/test_retrieval.py` (needs `DCL_TEST_DATABASE_URL`, an empty ParadeDB 0.26.2 database)
- `backend/tests/benchmark/retrieval_set.yaml` (S5, planned: the 40-query recall set)

## Interfaces

Provides:
- `search(session, query, embed_query=, rerank=, filters=, scope=, k=8, user_language=, alias_surfaces=) -> SearchResult(hits, warnings, dense_path, rerank_margin_1_5, leg_counts)`; `embed_query`/`rerank` are `ModelsClient.embed_queries(...)[0]` and `ModelsClient.rerank`
- `Hit`: doc fields, `anchor` (serialized stable anchor of the best passage), `parent_text`, `passage`, `web_url`, `asset_id`, `needs_review`, scores, `also_in` (near-duplicates collapsed into it); no node ids
- BM25 field names the SQL relies on: `content` (icu), `content_stem_{en,de,fr,es,it,ru}`, `content_{ja,ko,zh}`, `content_codes` (whitespace), `content_en`, `breadcrumb`, literal filter fields
- `POST /v1/retrieval/search` (`backend/api/engine.py`, Console user): `RetrievalLabRequest {query, filters, scope, k ≤ 50, user_language, rerank}` → `SearchResult` with hits, legs, dense path and margin
- planned: doc-level `search_text` leg, alias expansion from `entity_aliases`

Consumes:
- `backend/embedding-service`, `backend/reranker-service` (through the callables)
- `backend/schema-and-migrations` (S1): `document_nodes`, `documents`, `document_relations`, `document_sources`, `drive_items`; the BM25 migration

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/indexing/retrieval.py`
- `backend/api/engine.py` (retrieval-lab route)
- `backend/tests/integration/retrieval/`
- `backend/tests/benchmark/retrieval_set.yaml`

## Rubric (what "done" means for this feature)

- [ ] recall@30 ≥0.9 on the SME query set incl. cross-lingual queries
- [x] Identifier queries hit lexically (`test_identifier_query_hits_lexically_without_dense_help`)
- [x] Filtered searches on one test plan return k results, on the exact path
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | Retrieval-lab endpoint for S3 |
| 2026-10-22 | S2 | Hybrid search: exact/HNSW dense leg, per-language BM25 (pg_search 0.26.2), RRF, parent collapse, rerank with margin and fallback, near-duplicate collapse; 11 DB tests; BM25 DDL sent to S1 |

## Related

- `.wiki/index.md`
