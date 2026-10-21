# S2 — ML / LLM (vision, enrichment, embeddings, retrieval, answer engine)

**Mission:** everything that touches a model: the shared VisionService on Gemini, Route A1 (PDF/Office with page triage, per-script OCR, tables, figures, handwriting), Routes D (photos) and F (video), the enrichment layer, the local embedding and reranker services on the GPU, the chunker with stable anchors, hybrid retrieval, and the Answer Engine with its tools, playbooks, sanitizer and verifier.

## Read first

`docs/architecture/03_phase2_processing_routes.md` (§3, §4, §8, §10), `04_metadata_enrichment_chunking_embedding.md` (all), `07_phase3_answer_engine.md` (all), `05_storage_schema.md` (§4.2, §4.3, §4.7), `01_system_overview_and_tech_stack.md` §5.3–5.4 and §7.

## You own

`services/vision`, `services/routes/{a1_office,d_photos,f_video}`, `services/enrichment`, `services/embedding_service`, `services/reranker_service`, `services/indexing/{chunker,anchors,overlays,retrieval}.py`, `services/engine`, `config/prompts`.

## Publish first

1. `services/embedding_service` (FastAPI, EmbeddingGemma 2, text + image, bfloat16, 768-d) and `services/reranker_service` with their client classes; both containerized for the GPU with S4.
2. `services/indexing/anchors.py`: `make_anchor(node)` and `resolve_anchor(anchor)` (page + content hash, fallback to page), used by S1's commit path, S3's viewer and S5's benchmark gold.
3. `services/indexing/index_document.py`: the entry point S1 calls after a route finishes (chunk → enrich → overlays → embed → rows), and `extract_identifiers()` shared by indexer and query side.
4. `services/engine/api.py`: the `/v1/answer` SSE event schema (`step`, `token`, `citation`, `embed`, `needs_confirmation`, `done`) and `/v1/traces/{id}`, so S3 can write the Open WebUI Pipe against it.
5. `services/vision/schemas.py`: the structured-output schemas of file 03 §3 (triage, handwriting, table, plot, schematic, photo, slide, video, page transcription).

## Depends on

S4: gateway client (`services/common/gemini.py`) and its capability flags, GPU containers. S1: `ProcessedDocument` contract, the commit path, the `rules`/flags models. S5: prompts' evaluation sets, retrieval query set, golden cases.

## Milestones

M0 model services (supporting), M4 (primary), M5 (primary), M7 routes D and F, M8 (primary), M10 benchmark engine mode (supporting).

## First tasks

1. Embedding and reranker services with health checks, dtype guard (never float16), batch endpoints, and a throughput measurement on the real GPU.
2. Gemini VisionService over S4's gateway client: prompt files under `config/prompts` with versions, structured outputs, the MinIO cache, `llm_calls` logging; a capability probe test.
3. Chunker (parent/child/table/figure/code/slide/transcript/run-summary nodes), contextual headers, token counting with the embedding model's tokenizer, stable anchors.
4. Enrichment call per parent (English outputs, grounding checks, `pint` validation), entity normalization against `entities`/`entity_aliases`, numeric facts with provenance.
5. Hybrid retrieval: dense (exact path for selective filters, HNSW otherwise), BM25 with per-language fields and `content_codes`, RRF, reranker, parent expansion, near-duplicate collapse; the Retrieval lab endpoint for S3.
6. Route A1 in the order: pre-flight → page triage (language/script) → Docling by script group → tables QA → figures → handwriting → page map; then D and F.
7. Answer Engine: query analysis schema, planner, tools T1–T6 and U1–U2 with template SQL, playbooks as Skills markdown, sanitizer, synthesis contract with provenance labels, verifier, DBOS runtime, extractive fallback.

## Definition of done

Wiki: map page updated and plan sheet deleted (see below). Then:

Golden-document fixtures with expected CIR; prompt versions recorded; `llm_calls` rows for every call; retrieval recall@30 ≥ 0.9 on S5's query set before M4 closes; the 60-case suite passing before M8 closes; status entry; merge request.

## Wiki duty (applies to every task)

Read `.wiki/index.md` and your feature's map page first. Open a plan sheet (`.wiki/_templates/plan-sheet.md`) with the exact workspace and rubric; work only inside it; when done, update the map page (status, location, interfaces, workspace, change log), update the area index, delete the plan sheet. Your map pages are listed in `.wiki/<area>/index.md` under your session id.

## When in doubt or blocked

Write the question or the blocker to `docs/sessions/STATUS.md`, message `DCL Lead` (or the session you wait on) once, and end your turn. Never improvise around the manual and never keep working "on the side" while waiting.

## Coordination rules

- Every number the engine states must come from a tool result; the verifier enforces it. No exceptions for "obvious" numbers.
- Prompts are files with versions, never inline strings.
- Do not write to the database outside S1's commit path and the review overlay interface; message `DCL S1 Backend` for schema needs.
