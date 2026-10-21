# Chunker, contextual headers, stable anchors, identifier extraction

| Field | Value |
|-------|-------|
| Feature id | `backend/chunker-and-anchors` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/04_metadata_enrichment_chunking_embedding.md §4, §6 |
| Last updated | 2026-10-21 |

## Purpose

Parent/child/table/figure/code/slide/transcript/run-summary nodes, English contextual headers, stable anchors (page + content hash), extract_identifiers() shared with the query side.

## Location

Code:
- `backend/indexing/chunker.py`
- `backend/indexing/anchors.py`
- `backend/indexing/identifiers.py`
- `backend/indexing/index_document.py`

Tests and fixtures:
- `backend/tests/unit/indexing/`

## Interfaces

Provides:
- index_document() entry point
- `make_anchor/resolve_anchor`
- extract_identifiers

Consumes:
- embedding-service
- enrichment
- index commit

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/indexing/chunker.py`
- `backend/indexing/anchors.py`
- `backend/indexing/identifiers.py`
- `backend/indexing/index_document.py`
- `backend/tests/unit/indexing/`

## Rubric (what "done" means for this feature)

- [ ] No embed_text exceeds 8,000 tokens
- [ ] Tables never split mid-row
- [ ] An anchor resolves after a chunk-size change, falling back to the page
- [ ] Indexer and query side share one identifier fixture test
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
