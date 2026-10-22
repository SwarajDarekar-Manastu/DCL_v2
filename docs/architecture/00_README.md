# Document Context Layer (DCL v2) — Production Architecture Manual

**Project:** Manastu Space — Propulsion Intelligence & Synthesis Engine
**Scope:** OneDrive (Microsoft Graph) → Ingestion → Processing → Storage → Answer Engine → Open WebUI. The knowledge base is the team's own test data, reports, code and photos **plus the external library kept in OneDrive** (vendor brochures, datasheets, papers, articles), part of it in languages other than English.
**Status of this document:** Build manual. Descriptive, not code. Every section is written so an engineer can implement it without re-reading the design conversation.
**Date:** 2026-10-21

---

## How to read this manual

| # | File | What it covers | Read it when |
|---|------|----------------|--------------|
| 01 | [System overview & tech stack](01_system_overview_and_tech_stack.md) | Goals, principles, the full stack with justification, deployment topology, data governance for the Gemini cloud API | Day 1, everyone |
| 02 | [Phase 1 — Ingestion & sync](02_phase1_ingestion_sync.md) | Graph auth, delta sync, junk gate, hashing & deduplication, MinIO landing, registry state machine | Building the sync engine |
| 03 | [Phase 2 — Processing routes](03_phase2_processing_routes.md) | The dispatcher, the Canonical Intermediate Representation, and one section per route (A1, A2, B, C, D, E, F, G) with step-by-step processing, tools, edge cases, and flags | Building any parser |
| 04 | [Metadata, enrichment, chunking, embedding](04_metadata_enrichment_chunking_embedding.md) | Deterministic metadata layer, open-vocabulary LLM enrichment (replaces the taxonomy gate), chunking strategy, embeddings, hybrid index | Building the common tail of the pipeline |
| 05 | [Storage schema](05_storage_schema.md) | MinIO bucket layout, Parquet conventions, every PostgreSQL table and what every column means | Writing migrations, queries, or the UI |
| 06 | [Review flags & halt policy](06_review_flags_and_halt_policy.md) | The flag catalog, severity model, per-route triggers, what halts and what flows, resolution actions, re-processing | Building the Review Console or any flag emitter |
| 07 | [Phase 3 — Answer engine](07_phase3_answer_engine.md) | Tools, skills, router, how each question type is answered (with worked examples), web-search policy, verification, citations | Building the agent |
| 08 | [Frontend — Open WebUI & DCL Console](08_frontend_openwebui.md) | What Open WebUI actually offers (verified against v0.12.3), integration strategy, Configuration UI, Review UI, Benchmark UI internal structure | Building the UI |
| 09 | [Validation, gaps & fixes](09_validation_gaps_and_fixes.md) | Everything in the earlier design that was wrong, fragile, or missing, and the fix adopted in this manual | Before sprint planning |
| 10 | [Development plan](10_development_plan.md) | Milestones, workstreams, repo layout, test strategy, acceptance criteria, risks | Sprint planning |

Diagrams are Mermaid (renders in GitHub, VS Code, Obsidian). Where a diagram is critical to a decision it is duplicated as ASCII.

---

## Decisions carried over from the design conversation (unchanged)

These were settled in the design sessions and remain in force:

1. **Source of truth is OneDrive**, reached through Microsoft Graph with the delegated app `dcl-reader-delegated`, signed in once as `ai@manastuspace.com` (device-code flow, `Files.Read.All`). Four folders shared by `aps@`: `APU Injector`, `APU`, `APS - Library`, `APU Heater`.
2. **~95% of OneDrive is junk** (`.venv`, `site-packages`, build output, LaTeX intermediates). It is rejected from Graph metadata before any byte is downloaded.
3. **Every accepted file is landed in MinIO** (S3-compatible, local) and never re-downloaded unless its content hash changes.
4. **One route per format family** (A1 Office/PDF, A2 JSON/LaTeX source, B code/config, C telemetry/spreadsheets, D hardware photos, E diagrams/schemas, F video, G archives/CAE). New formats plug in through an adapter registry; unknown formats are flagged, not dropped.
5. **Telemetry never goes into the vector store.** It goes to Parquet and is queried deterministically with DuckDB. Only the run catalog and summaries are searchable text.
6. **PostgreSQL is the single relational + vector + lexical store** (pgvector + BM25). No second database to keep in sync.
7. **Hybrid retrieval** (dense + lexical, fused with Reciprocal Rank Fusion, then cross-encoder reranking) with parent-child chunking.
8. **Human review is halt-and-queue** for anything that would corrupt downstream numbers (units, unknown schemas, unreadable values).
9. **Outbound web queries are IP-sanitized.** Internal identifiers never leave the network in a search query.
10. **Open WebUI is the chat front end**, extended with a Review UI and a Benchmark UI.

## Decisions changed or added in this manual

| Topic | Before | Now | Why (details in file 09) |
|-------|--------|-----|--------------------------|
| LLM / VLM | Local Qwen2.5-32B + Qwen2.5-VL-7B, Gemini 2.5 as fallback | **Gemini 3.8 Flash** (`gemini-3.8-flash`) for reasoning, vision, handwriting, enrichment; **Gemini 3.1 Flash-Lite** for cheap classification/triage | Your instruction; one model family simplifies ops. Verified: 1,048,576-token input, text/image/video/audio/PDF input, structured outputs, function calling, thinking levels low/medium/high |
| Embeddings | BGE-M3 (1024-d) local | **EmbeddingGemma 2** (open weights, Apache 2.0) run locally: 768-d, multimodal (text, code, images), 8,192-token input, 100+ languages; model id recorded per row | Your instruction. No per-call cost, vectors never leave the network, photo similarity stays possible through its vision encoder (file 04 §5) |
| Knowledge base scope | In-house files only | **In-house files plus the external library.** Every document carries `source_origin` and a trust tier; OCR engine chosen per script; cross-lingual retrieval with an English enrichment layer; translation as a config mode | Your instruction (file 04 §2.3, §10; file 03 §A1.12) |
| Storage schema | ~40 tables | **26 tables** in three tiers (authored / registry / derived); stable anchors instead of node ids; review resolutions re-applied as overlays; every FK indexed; statuses CHECK-constrained | Independent schema review found over-design and four blocking defects (file 09 §I) |
| Rollout | Full ingestion from day one | **Metadata-only crawl of everything; downloads and processing limited to an allowlist** until Route A1 is accepted; then one full-corpus run (M6). Review UI pulled forward to M3; queue load test in M1 | Avoids paying vision costs twice while parsers and prompts are still moving (file 10 §3) |
| Reranker | bge-reranker-v2-m3 | **bge-reranker-v2-m3 kept (tiny local service)**, Flash-Lite listwise rerank as fallback | Gemini has no reranker endpoint; the cross-encoder is cheap and deterministic |
| Taxonomy | Closed enum + `TAXONOMY_NEW_TERM` review flag | **Open-vocabulary entity extraction** from surrounding context; alias table grows automatically; **no taxonomy flag** | Your instruction. A new material code (C-102 → C-103) is data, not an exception |
| Halt policy | Any flag halts the whole file | **Two severities.** HARD flags halt the file. SOFT flags commit the file and mark only the affected chunks `needs_review` | A single unreadable handwritten number must not hide a 40-page report. Strict mode remains a config switch |
| Change detection | Keyed on `parentReference.path` + eTag | **Keyed on item id + `quickXorHash` + `parentReference.id` + name**; paths rebuilt from a local folder tree | Graph delta does not return `parentReference.path`, omits `cTag` on OneDrive for Business, and does not re-emit children when a folder is renamed |
| Dedup | SHA-256 per file | **Four layers:** Graph `quickXorHash` (zero-download), SHA-256 content-addressed blobs (one blob, many paths), page/sheet text hashes (partial re-ingest), perceptual hash for images; MinHash near-duplicate linkage for report versions | Covers copies, moves, re-exports and v1/v2 pairs without double indexing |
| Lexical search | pg_search (ParadeDB) | **pg_search kept as default**, with the constraints spelled out (AGPL, must run the ParadeDB build, index syntax changed across releases) and native PostgreSQL FTS as the documented fallback | Exact part numbers need lexical recall; the fallback exists if the extension is a deployment problem |
| Frontend extension | "Custom React/Svelte sidebar tabs inside Open WebUI" | **Separate DCL Console app** (Review, Benchmark, Configuration) with shared SSO, plus a thin Open WebUI integration (Pipe + Action + Rich UI embeds + Skills). Open WebUI is **not forked** | Verified: Open WebUI has no supported way to add sidebar pages without forking; it does have Pipes, Actions, iframe embeds, Skills, and a citation event |

## Resolved decisions (2026-10-21)

Gemini only through Manastu's Cloud Run gateway (never Vertex or the Developer API directly); two-tier halt policy; no fallback model for Gemini; delegated Graph app with permission option A or B from the env; default retention; no Teams digests; all engineers see all four roots; DBOS as the workflow durability runtime; pg_search kept while it remains the most favorable choice; `enrichment_only` translation; download everything the gate accepts but process only the test folders until M6; one GPU for the embedding service and the reranker. Details and the two still-open items (gateway API contract, Graph permission option) are in file 09 §H.

## Glossary

- **DCL** — Document Context Layer: the ingestion + processing + storage half of the system.
- **Answer Engine** — the LlamaIndex Workflow that answers questions with tools.
- **Route** — a format-specific processing pipeline (A1…G).
- **CIR** — Canonical Intermediate Representation: the lossless parsed form of a file (Docling JSON, AST JSON, DataFrame schema, etc.) saved in MinIO so chunking/embedding can be re-run without re-parsing.
- **Node** — a retrievable chunk in `document_nodes` (text, table, figure, code symbol, transcript segment, photo analysis).
- **Parent / child node** — a 1,200–1,800-token section node and its 250–400-token children. Children are embedded; parents are what the LLM reads.
- **Flag** — a structured review request attached to a file/page/node. HARD or SOFT.
- **Halt** — a file whose HARD flag is open; nothing from it is in the active index.
- **Staged payload** — the fully processed output of a halted file, kept so resolution does not require re-parsing.
- **Blob** — a content-addressed object (SHA-256) in MinIO. Many OneDrive items can point to one blob.
- **Alias table** — `entities` + `entity_aliases`: surface forms (`C103`, `C-103 Niobium`, `Niob C-103`) → one canonical entity (`C-103`). Grows automatically.
- **Source origin** — `internal` (the team's own material), `external_kept` (brochures, datasheets, papers stored in OneDrive), `web_live` (fetched at answer time). Drives labeling and ranking.
- **Trust tier** — 1 measured telemetry, 2 internal reports/code/photos, 3 standards, 4 vendor datasheets, 5 papers/articles, 6 live web.
- **Stable anchor** — `{doc_id, page/line/time, content hash}`: how citations, flags and benchmark gold refer to content without depending on node ids, which change on every re-index.
- **Overlay** — a stored human resolution (corrected value, chosen table version, unit decision) that the indexer re-applies whenever the document is rebuilt.
- **Scope (download / processing)** — allowlists in `pipeline_config` that limit which folders are downloaded and processed before the full-corpus run.
