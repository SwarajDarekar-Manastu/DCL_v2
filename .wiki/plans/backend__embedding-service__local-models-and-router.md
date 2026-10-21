# Plan: backend/embedding-service + backend/reranker-service — local models module, models router, HTTP client

| Field | Value |
|-------|-------|
| Feature | `backend/embedding-service` (map: `.wiki/backend/embedding-service.md`) and `backend/reranker-service` (map: `.wiki/backend/reranker-service.md`); both live in one module |
| Session | S2 |
| Branch | claude/infallible-swartz-58c96b (S2 worktree branch, kept per Lead instruction) |
| Opened | 2026-10-21 |
| Delete when | rubric below is green and both map pages are updated |

## Intent

Build `backend/llm_engine/local_models.py`: EmbeddingGemma 2 (text + vision encoders, audio not loaded, 768-d, bfloat16 or float32, never float16) and bge-reranker-v2-m3, loaded once per process when `backend/main.py` runs with `ROLE=models`; the thin router `backend/api/models.py` (`POST /embed/text`, `POST /embed/image`, `POST /rerank`, `GET /models/health`); and the HTTP client class that workers and the API role use (`ModelsClient`), which raises one typed error when the model role is down so retrieval can keep RRF order. Measure throughput on the real GPU. Must not touch `backend/main.py` (Lead), `backend/config.py` (S4) or compose/Dockerfiles (S4).

## Workspace

Files to read:
- docs/architecture/04_metadata_enrichment_chunking_embedding.md §4.3, §5
- docs/architecture/01_system_overview_and_tech_stack.md §5.4
- docs/architecture/07_phase3_answer_engine.md §4 T1, §11, §12
- docs/architecture/10_development_plan.md §2, §2.1

Files to change (exact):
- `backend/llm_engine/local_models.py` (new)
- `backend/api/models.py` (new)
- `backend/tests/unit/llm_engine/local_models/test_local_models.py` (new; fakes, no GPU)
- `backend/tests/unit/llm_engine/local_models/test_models_router_and_client.py` (new; fakes, no GPU)
- `backend/tests/unit/llm_engine/local_models/test_gpu_models.py` (new; real models, skipped without CUDA)
- `backend/tests/unit/llm_engine/local_models/measure_throughput.py` (new; prints the GPU numbers recorded in the map)
- `.wiki/backend/embedding-service.md`, `.wiki/backend/reranker-service.md`, `.wiki/backend/index.md` row status, `.wiki/index.md` (plan row)

Files explicitly out of scope (owned by another session → message them):
- `backend/main.py` (Lead): mount `backend.api.models.router` and call `load_models()` at startup when `ROLE=models`
- `backend/config.py`, `.env.example`, GPU Dockerfile, compose (S4): model-role base URL for clients, dtype/device env, pinned library versions, HF cache volume

## Steps

1. Load both models in a scratch script; confirm the sentence-transformers 6.1 API for text, image and cross-encoder scoring.
2. Write `local_models.py`: dtype guard, input formatting (`title: … | text: …`, `task: search result | query: …`), token cap 8,000 (refuse, never truncate silently), NaN/norm check on output, singleton `load_models()`/`get_models()`, `ModelsClient` + `ModelServerUnavailable`.
3. Write the router with Pydantic request/response models and batch limits.
4. Unit tests with fake models; GPU tests with the real models.
5. Measure throughput (text batch, image batch, rerank 50 pairs) and record it.

## Rubric for this task

- [ ] Returns 768-d normalized vectors for text and image (GPU test)
- [ ] Refuses float16 at load time (unit test)
- [ ] Throughput measured and recorded on the real GPU (map page)
- [ ] Reranker scores 50 pairs within the 0.4 s rerank budget of file 07 §11 (GPU test)
- [ ] Client raises `ModelServerUnavailable` within its timeout when the model role is down, so retrieval keeps RRF order (unit test)
- [ ] Inputs above 8,000 tokens are refused with 422, not truncated (unit test)
- [ ] Verification commands below pass

## Verification commands

```bash
.venv/bin/python -m pytest backend/tests/unit/llm_engine/local_models -q
.venv/bin/python backend/tests/unit/llm_engine/local_models/measure_throughput.py
```

## Risks and open questions

- GPU is shared with other projects' containers (about 3.4 GB free of 8 GB); the user allowed stopping the other bge reranker container if memory runs out.
- Model ids are constants in the module for now; file 05 §4.6 lists `models.*` in `pipeline_config`, read through S4's config once it exists.
