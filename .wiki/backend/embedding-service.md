# Embedding service (EmbeddingGemma 2, text + image, GPU)

| Field | Value |
|-------|-------|
| Feature id | `backend/embedding-service` |
| Status | done |
| Owner session | S2 |
| Spec | docs/architecture/04_metadata_enrichment_chunking_embedding.md §4.3, §5; 01 §5.4; 10 §2.1 (roles) |
| Last updated | 2026-10-21 |

## Purpose

EmbeddingGemma 2 (`google/embeddinggemma-2`, text and vision encoders, audio not loaded) at 768-d, served by `backend/main.py` with `ROLE=models`; the only producer of vectors. Every other process calls it over HTTP through `ModelsClient`.

## Location

Code:
- `backend/llm_engine/local_models.py` (models, formatting, guards, `ModelsClient`)
- `backend/api/models.py` (router, mounted by `backend/main.py` for `models` and `all`)

Tests and fixtures:
- `backend/tests/unit/llm_engine/local_models/` (torch-free fakes in `conftest.py`; only `test_gpu_models.py` needs torch, CUDA and 3 GiB free; `measure_throughput.py` prints the table below)

## Interfaces

Provides:
- `POST /embed/text` `{kind: document|query, items: [{text, title?}]}` (≤ 256 items) → `{model: "embeddinggemma-2@768", dim: 768, vectors}`
- `POST /embed/image` `{images_b64: [...]}` (≤ 32) → same response
- `GET /models/health` → `{embedding_model, reranker_model, dim, device, dtype}`; the first call loads both models (use it as the compose healthcheck)
- Python: `ModelsClient(base_url=settings.models_url).embed_documents(texts, titles)`, `.embed_queries(queries)`, `.embed_images(bytes_list)`; raises `ModelServerUnavailable` (connection, timeout, 5xx) or `ModelRequestRejected` (4xx)
- Python: `count_tokens(texts)` with the model's own tokenizer, CPU only (for the chunker)
- Document input `title: {title} | text: {text}` (`title: none` without title); query input `task: search result | query: {q}`; images raw

Consumes:
- GPU container and `DCL_MODELS_URL` (platform/compose-stack, platform/env-contract)

## Behavior that callers rely on

- bfloat16 on GPUs that support it, else float32; float16 and any other dtype refused at load.
- Vectors are re-normalized in float64; a non-finite, collapsed or non-768 vector is an error (HTTP 500).
- `embed_text` over 8,000 tokens, or an input over the 8,192-token context, is refused with 422, never truncated.
- Weights load once per process on first use; GPU calls are serialized; CUDA out-of-memory halves the batch and retries (the card is shared).

## Measured throughput (2026-10-21, RTX 5060 8 GB shared with two other projects' containers, bfloat16)

| Workload | Result |
|----------|--------|
| Text, 512 children of ~321 tokens, batch 16 | 125 chunks/s |
| Estimated 250k-chunk backfill | 33 min |
| Images, 1600×1200 JPEG | 10.9 images/s |
| One query embed | 17 ms p50 |
| Peak GPU memory (both models loaded) | 2.6 GiB |

## Workspace (files to touch when modifying this feature)

- `backend/llm_engine/local_models.py`
- `backend/api/models.py`
- `backend/tests/unit/llm_engine/local_models/`

## Rubric (what "done" means for this feature)

- [x] Returns 768-d normalized vectors for text and image (`test_gpu_models.py`)
- [x] Refuses float16 (`test_local_models.py`, `test_gpu_models.py`)
- [x] Throughput measured and recorded on the real GPU (table above)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | Unit tests run without torch (dtype check before import, CUDA OOM recognized by name, torch-free fakes); only `test_gpu_models.py` needs torch |
| 2026-10-21 | S2 | Built `local_models.py`, `/embed/text`, `/embed/image`, `/models/health`, `ModelsClient`; GPU throughput measured |

## Related

- `backend/reranker-service` (same module and process)
- `backend/chunker-and-anchors` (uses `count_tokens`)
- `backend/index-commit` (writes the vectors as `halfvec(768)`)
- `platform/compose-stack`, `platform/env-contract`
- `.wiki/index.md`
