# Index commit path (transaction, overlays, vector reuse)

| Field | Value |
|-------|-------|
| Feature id | `backend/index-commit` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/04_metadata_enrichment_chunking_embedding.md §7 |
| Last updated | 2026-10-21 |

## Purpose

One transaction per document: delete all nodes by doc_id, apply resolved review overlays, bulk insert nodes/mentions/facts via COPY reusing vectors by embed_text_hash, upsert assets and flags, update documents.

## Location

Code:
- `services/indexing/commit.py`

Tests and fixtures:
- `tests/integration/indexing/test_commit.py`

## Interfaces

Provides:
- index_document() commit stage

Consumes:
- chunker/anchors/enrichment (backend/… via S2 features)
- review overlays (backend/review-backend)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/indexing/commit.py`
- `tests/integration/indexing/test_commit.py`

## Rubric (what "done" means for this feature)

- [ ] Old pipeline versions never remain in HNSW/BM25 after a re-index
- [ ] A corrected handwritten value survives a forced re-index
- [ ] Unchanged chunks are not re-embedded
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
