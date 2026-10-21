# Chunker, contextual headers, stable anchors, identifier extraction

| Field | Value |
|-------|-------|
| Feature id | `backend/chunker-and-anchors` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/04_metadata_enrichment_chunking_embedding.md §4, §6 |
| Last updated | 2026-10-21 |

## Purpose

Parent/child/table/special nodes from `ProcessedDocument.nodes`, English contextual headers, `embed_text` capped at 8,000 tokens, stable anchors (content hash + page/line/time/cells), and `extract_identifiers()` shared with the query side.

## Location

Code:
- `backend/indexing/chunker.py` (`chunk_document`, `build_embed_texts`, `IndexNode`, `ChunkingConfig`)
- `backend/indexing/tables.py` (`table_rows`, `row_groups`, `split_table`, `table_to_text`)
- `backend/indexing/anchors.py` (`content_hash`, `make_anchor`, `resolve_among`, `resolve_anchor`, `NodeView`, `AnchorResolution`)
- `backend/indexing/identifiers.py` (`extract_identifiers`, `content_codes`)
- `backend/indexing/index_document.py` (planned: chunk → enrich → overlays → embed → commit)

Tests and fixtures:
- `backend/tests/unit/indexing/` (`identifier_cases.json` is the one fixture for indexer and query side)
- `backend/tests/integration/indexing/test_resolve_anchor.py` (needs `DCL_TEST_DATABASE_URL`, an empty ParadeDB database)

## Interfaces

Provides:
- `chunk_document(doc, config=None, count_tokens=None) -> list[IndexNode]`; `build_embed_texts(nodes, doc.document, entities_by_ref)` sets `embed_title`, `embed_text`, `embed_text_hash` (SHA-256 of the exact model input)
- `IndexNode`: one future `document_nodes` row without ids or vectors; `ref`/`parent_ref` for S1's commit; `embed` says whether a text vector is needed
- `extract_identifiers(text) -> list[str]` (uppercased full forms plus separator-less variants); `content_codes(text) -> str`
- `content_hash(text)`, `make_anchor(doc_id, node) -> Anchor` (S1's model), `resolve_among(anchor, nodes) -> AnchorResolution(status exact|page_fallback|document_only, page_no, matches, boxes)`
- `resolve_anchor(session, anchor) -> AnchorResolution`: one query over `document_nodes` (hash prefix or locator cover), matches are request-scoped `NodeView`s
- planned: `index_document()`

Consumes:
- `backend/dispatcher/contract.py` (S1): `ProcessedDocument`, `ProcessedNode`, `Anchor`, `PageBox`
- `backend/embedding-service`: `count_tokens` (EmbeddingGemma tokenizer), `format_document`

## Input conventions routes rely on

- Text is `parent` or `child` nodes; consecutive text nodes with the same breadcrumb and parent_ref form one section. One node per paragraph gives per-paragraph pages and boxes.
- A text node named as parent_ref by a special node (transcript section) is kept whole.
- `table` content is HTML (`<thead>` or a first all-`<th>` row is the header); `table_row` nodes name their table.
- Every node needs a page, line, time or cell locator to be anchorable.

## Workspace (files to touch when modifying this feature)

- `backend/indexing/chunker.py`
- `backend/indexing/tables.py`
- `backend/indexing/anchors.py`
- `backend/indexing/identifiers.py`
- `backend/indexing/index_document.py`
- `backend/tests/unit/indexing/`
- `backend/tests/integration/indexing/test_resolve_anchor.py`

## Rubric (what "done" means for this feature)

- [x] No embed_text exceeds 8,000 tokens (real-tokenizer test with a 4,800-word section, a 2,000-row table and a 6,000-line function)
- [x] Tables never split mid-row (block test; rowspan groups kept together)
- [x] An anchor resolves after a chunk-size change, falling back to the page (`test_anchors_survive_a_chunk_size_change_by_falling_back_to_the_page`)
- [x] Indexer and query side share one identifier fixture test
- [x] `resolve_anchor` over `document_nodes` (database test: exact, then page fallback after a chunk-size change, then document)
- [ ] `index_document()` end to end (waits for enrichment and S1's commit path)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | `resolve_anchor` over `document_nodes` with a database test |
| 2026-10-22 | S2 | Table helpers moved to `tables.py` (Lead approval); chunker under 600 lines |
| 2026-10-21 | S2 | Chunker, contextual header, embed_text cap, identifiers with shared fixture, anchor hash/make/resolve; 47 tests |

## Related

- `backend/index-commit` (S1 maps `IndexNode` to `document_nodes`)
- `backend/retrieval` (query side of `extract_identifiers`)
- `frontend/viewer` (S3 uses `AnchorResolution`)
- `quality/benchmark-suites` (gold anchors)
- `.wiki/index.md`
