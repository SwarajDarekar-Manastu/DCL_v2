# Index commit path (transaction, overlays, vector reuse)

| Field | Value |
|-------|-------|
| Feature id | `backend/index-commit` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/04_metadata_enrichment_chunking_embedding.md §7 |
| Last updated | 2026-10-23 |

## Purpose

One transaction per document: delete all nodes by doc_id, apply resolved review overlays, bulk insert nodes/mentions/facts via COPY reusing vectors by embed_text_hash, upsert assets and flags, update documents.

## Location

Code:
- `backend/indexing/commit.py` (`commit_document(session, document, processed, plan, pipeline_version)`: entities/aliases idempotent, assets upsert by URI, old nodes/mentions/facts/telemetry of the document deleted, nodes inserted with refs → ids and `needs_review` from open SOFT flags, mentions, facts, `telemetry_runs`/`telemetry_channels`, documents row (enrichment, entity ids, search text, status, `indexed_at`); refuses a document with an open HARD flag; `default_indexer(models_url, minio)` binds S2's `index_document`)

Tests and fixtures:
- `backend/tests/integration/indexing/test_commit.py` (planned)
- `backend/tests/unit/routes/c_telemetry/test_pipeline.py` (commit of a Route C run with S2's real `index_document`, label collision, resume)

## Interfaces

Provides:
- `commit_document()` and the `Indexer` callable `(session, ProcessedDocument, doc_id, cloud_allowed) -> IndexPlan`

Consumes:
- chunker/anchors/enrichment (backend/… via S2 features)
- review overlays (backend/review-backend)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/indexing/commit.py`
- `backend/tests/integration/indexing/test_commit.py`

## Rubric (what "done" means for this feature)

- [ ] Old pipeline versions never remain in HNSW/BM25 after a re-index
- [ ] A corrected handwritten value survives a forced re-index
- [ ] Unchanged chunks are not re-embedded (vector reuse by `embed_text_hash` wired through `existing_vectors`; not yet measured)
- [ ] Review overlays re-applied on rebuild (file 04 §7): not yet
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S1 | First commit path (Route C first): entities, nodes, mentions, facts, telemetry catalog, documents row, run-label collisions |
| 2026-10-23 | S1 | `strip_nul()` over the ProcessedDocument and IndexPlan at the start of `commit_document` (PostgreSQL refuses NUL); `backend/tests/unit/indexing/test_commit_nul.py` |
| 2026-10-23 | S1 | `revision_marker` written on commit; `backend/indexing/revisions.py` `apply_revisions`: newer revision of a drawing in the same folder SUPERSEDES the older, equal claims raise CONFLICT SOFT (file 02 §5.1); `test_revisions.py` |

## Related

- `.wiki/index.md`
