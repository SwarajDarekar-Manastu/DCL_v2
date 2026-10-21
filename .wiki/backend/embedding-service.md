# Embedding service (EmbeddingGemma 2, text + image, GPU)

| Field | Value |
|-------|-------|
| Feature id | `backend/embedding-service` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/04_metadata_enrichment_chunking_embedding.md §5; 01 §5.4 |
| Last updated | 2026-10-21 |

## Purpose

FastAPI service wrapping EmbeddingGemma 2 at 768-d with the vision encoder loaded, bfloat16 guard, batch endpoints, health checks; the only producer of vectors.

## Location

Code:
- `backend/llm_engine/local_models.py`

Tests and fixtures:
- `backend/tests/unit/llm_engine/local_models/`

## Interfaces

Provides:
- /embed/text, /embed/image, /health

Consumes:
- GPU container (platform/compose-stack)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/local_models.py`
- `backend/tests/unit/llm_engine/local_models/`

## Rubric (what "done" means for this feature)

- [ ] Returns 768-d normalized vectors for text and image
- [ ] Refuses float16
- [ ] Throughput measured and recorded on the real GPU
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
