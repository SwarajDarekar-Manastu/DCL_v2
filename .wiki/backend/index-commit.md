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
- `backend/indexing/near_duplicates.py` (MinHash over 5-word shingles of the parent and table node text: `signature`, `similarity`, `apply_near_duplicates` called at the end of `commit_document`, `backfill`, `report`; CLI `python -m backend.indexing.near_duplicates backfill|report [--floor 0.7]`; links are `document_relations` NEAR_DUPLICATE rows with `created_by = 'minhash'`)
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
- `backend/indexing/near_duplicates.py`, `backend/postgres/models/documents.py` (`minhash` column), `backend/postgres/migrations/versions/0013_document_minhash.py`, `backend/tests/unit/indexing/test_near_duplicates.py`

## Rubric (what "done" means for this feature)

- [ ] Old pipeline versions never remain in HNSW/BM25 after a re-index
- [ ] A corrected handwritten value survives a forced re-index
- [ ] Unchanged chunks are not re-embedded (vector reuse by `embed_text_hash` wired through `existing_vectors`; not yet measured)
- [ ] Review overlays re-applied on rebuild (file 04 §7): not yet
- [x] Near-duplicate reports are linked: after a commit, two live documents of one route in one root with Jaccard ≥ 0.85 have one NEAR_DUPLICATE row (`doc_id_a < doc_id_b`, score set, `created_by = 'minhash'`); a re-index replaces only the rows with that `created_by`; neither document changes status (11 tests incl. a real `commit_document`)
- [x] The commit path writes NEAR_DUPLICATE (`retrieval._near_duplicates` read them with no writer until now)
- [ ] Threshold 0.85 checked on a real pair: the stack's 26 signed documents have a top score of 0.29, so no real near-duplicate pair exists to tune on yet (needs the user's v1/v2 example)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S1 | First commit path (Route C first): entities, nodes, mentions, facts, telemetry catalog, documents row, run-label collisions |
| 2026-10-23 | S1 | `strip_nul()` over the ProcessedDocument and IndexPlan at the start of `commit_document` (PostgreSQL refuses NUL); `backend/tests/unit/indexing/test_commit_nul.py` |
| 2026-10-23 | S1 | `revision_marker` written on commit; `backend/indexing/revisions.py` `apply_revisions`: newer revision of a drawing in the same folder SUPERSEDES the older, equal claims raise CONFLICT SOFT (file 02 §5.1); `test_revisions.py` |
| 2026-10-23 | Lead | MinHash near-duplicate step built. Gap: retrieval read NEAR_DUPLICATE rows, no code wrote them. `near_duplicates.py` runs at the end of `commit_document`; signature on `documents.minhash` (0013) from node body text (not `search_text`); `backfill` and read-only `report` CLI. Checked on a clone of the stack DB: 26 documents signed, 0 links, top score 0.29. See DECISIONS 2026-10-23 |

## Related

- `.wiki/index.md`
