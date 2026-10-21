# 09 — Validation of the Earlier Design: Gaps Found and Fixes Adopted

This file lists what was wrong, fragile, or missing in the design conversation and what this manual does about it. Items marked **(integrated)** are already specified in files 02–08; items marked **(decision needed)** are for the team.

## A. Ingestion & sync

| # | Issue in the earlier design | Why it matters | Fix (where) |
|---|-----------------------------|----------------|-------------|
| A1 | Change detection keyed on `parentReference.path` and `eTag`/`cTag` | Graph delta does **not** populate `parentReference.path`, does not re-emit children on folder rename, and omits `cTag` on OneDrive for Business create/modify; `eTag` changes on metadata-only edits → spurious re-processing and missed moves | Track by **item id**; detect content change with `quickXorHash`; rebuild paths from a local folder tree (file 02 §3.1, §5) **(integrated)** |
| A2 | Delta-expiry handling described as "fall back to a full metadata walk" | A naive walk followed by deletes can wipe the index on a partial enumeration | 410 → staged resync table → diff → per-item confirmation before any delete (file 02 §3.5) **(integrated)** |
| A3 | Polling only | Scan guidance says poll ≤ daily and use webhooks | Webhooks + debounced delta + daily safety delta (file 02 §3.3) **(integrated)** |
| A4 | Delegated token lifecycle unmonitored | Refresh token revocation silently stops ingestion | 15-min token health check, Console re-auth flow, `REAUTH_REQUIRED` state (file 02 §1) **(integrated)**. **(decision needed)** whether admin would grant application permissions later, which removes this risk |
| A5 | SHA-256 per file only | Copies of the same file in two folders get processed and indexed twice; re-saved HEIC/JPG photos double the vision cost; v1/v2 reports pollute top-k | Four-layer model: quickXorHash → SHA-256 blobs (many locations, one document) → page/sheet hashes → pHash/MinHash (file 02 §5) **(integrated)** |
| A6 | Junk list applied by extension regardless of location | `.csv/.png/.xml` are junk only under `site-packages`; the same extensions in team folders are data | Tier-1 path gate before Tier-2 extension gate (file 02 §4) **(integrated)** |
| A7 | `_to_delete` content "logged but not indexed" without a path back | Engineers move folders in and out | Quarantine is a path state recomputed from the folder tree; moving out re-activates with zero reprocessing (file 02 §5.1) **(integrated)** |
| A8 | No handling of secrets in `.cfg`/`.txt`/`.py` | API keys would be sent to Gemini and indexed | Tier-4 secret scan → `SENSITIVE_CONTENT`, restricted blob prefix (file 02 §4, file 06) **(integrated)** |
| A9 | No idempotency/versioning story | Re-runs after crashes duplicate nodes; prompt changes force re-OCR | `stage_completions`, `parser_version` vs `pipeline_version`, CIR in MinIO, transactional index commit (file 02 §7.1, file 04 §7) **(integrated)** |
| A10 | Zip handling without a bomb guard | A hostile or accidental archive fills the disk | Ratio/size/depth/path-traversal guard (file 03 §11) **(integrated)** |

## B. Processing

| # | Issue | Why it matters | Fix |
|---|-------|----------------|-----|
| B1 | "Docling flags HANDWRITTEN regions" | Docling's layout model has no reliable handwriting class; OCR confidence alone misses neat handwriting | Three-source region detection incl. a cheap Flash-Lite page triage with 0–1000 bboxes (file 03 §A1.7) **(integrated)** |
| B2 | Sending 743 team PNGs through the hardware-inspection prompt | Most are exported plots/screenshots; the prompt would hallucinate hardware | Classify first (hardware photo / plot / document scan / diagram / other) (file 03 §8) **(integrated)** |
| B3 | Docling `table_score` assumed usable | Not implemented yet | Own table QA + VLM A/B check (file 03 §A1.4) **(integrated)** |
| B4 | `.tex`/`.json` as text source, PDF "stored for viewing" — but citations need page numbers | Engineers want "page 12", not "line 418 of results.tex" | Page map built by aligning source headings to PDF page texts; PDF-only pages appended (file 03 §A1.0) **(integrated)** |
| B5 | Multi-file LaTeX/JSON fragmentation | Sections lose test/hardware context | Folder-level assembler, document-level header on every chunk (file 03 §1.3, file 04 §4.2) **(integrated)** |
| B6 | `.dat` processed without the `.cfg` channel map | Columns stay `AIN0/AIN1` → useless for DuckDB | Two-pass folder order with a 10-min wait, review rules as maps (file 03 §C.0) **(integrated)** |
| B7 | Excel values read with one openpyxl mode | Formula caches missing/`#REF!` | Dual read + LibreOffice recalculation + `CONFLICT` (file 03 §C.4) **(integrated)** |
| B8 | Clock drift across video/LabJack/LabVIEW ignored | Joins on `t=0` are wrong by seconds | Ignition-event alignment with confidence and `t_from_ignition_ms` (file 03 §C.6) **(integrated)** |
| B9 | `.plotdata` loaded with `pickle.load` | **Arbitrary code execution** on untrusted files | Never unpickle; `pickletools` inspection; ask for a CSV re-export (file 03 §C.5) **(integrated)** |
| B10 | Whole 50-kHz files loaded into pandas inside the same worker as Docling | OOM kills the worker | Streaming PyArrow on a memory-limited queue; separate pools (file 03 §12) **(integrated)** |
| B11 | Gauge → absolute conversion without ambient reference | Vacuum vs sea level changes every pressure number | `ambient_condition` required for pressure channels; otherwise `UNIT_AMBIGUITY` HARD (file 03 §C.1) **(integrated)** |
| B12 | Single firing per file assumed | Files with several firings produce meaningless "steady-state" means | Sub-run segmentation (file 03 §C edge cases) **(integrated)** |
| B13 | Sensor saturation not detected | A flat-top "peak" reported as the true peak | `saturated` flag per channel (file 05 §4.4) **(integrated)** |
| B14 | ECSS supersession rule applied by regex to all documents | Reports would be auto-superseded by near-duplicates | Automatic supersession **only** for standards; reports linked, never auto-superseded (file 04 §2.2) **(integrated)** |
| B15 | Very large PDFs processed in one pass | A 900-page standard blocks a worker for an hour and dies on timeout | Page windows + checkpointed CIR + time budget (file 03 §A1.1, §12) **(integrated)** |
| B16 | EXIF kept wholesale | GPS of test site, device ids | GPS stripped; faces not described (file 03 §8) **(integrated)** |
| B17 | Figure handling treated all pictures alike | Logos/signatures cost vision calls; plots and schematics need different schemas | Docling picture classification → per-class VLM schema; identical crops cached (file 03 §3, §A1.6) **(integrated)** |

## C. Metadata, taxonomy, search

| # | Issue | Why it matters | Fix |
|---|-------|----------------|-----|
| C1 | Closed taxonomy enums + `TAXONOMY_NEW_TERM` flag | Human work with no retrieval benefit; brittle as vocabulary evolves | Open-vocabulary extraction with closed **types**, deterministic alias normalization, no gate (file 04 §3) **(integrated, per your instruction)** |
| C2 | LLM-extracted numbers trusted as metadata | Hallucinated or mis-united numbers leak into filters | Grounding + `pint` + sanity checks; `numeric_facts` table with provenance (file 04 §3.2, §8) **(integrated)** |
| C3 | Embedding dimensions vs HNSW limits not checked | The first draft chose a 3072-d default model; pgvector HNSW on `vector` supports ≤ 2,000 | Moot after the switch to EmbeddingGemma 2 (768-d), stored as `halfvec(768)` (file 04 §5) **(integrated)** |
| C4 | Children embedded without context | "the pressure rose to 12.4 bar" is unretrievable by test id | Contextual header in `embed_text` (file 04 §4.2) **(integrated)** |
| C5 | BM25 tokenizer not considered for identifiers | `PT-104`, `C-103`, `ECSS-E-ST-35C` split or stemmed | `content_codes` generated column with identifier tokens, dash-less variants (file 04 §6) **(integrated)** |
| C6 | pg_search chosen without noting constraints | AGPL-3; must run ParadeDB build; DDL/score function names changed across versions | Pin version, isolate DDL in one migration, document the native-FTS fallback (file 01 §5.5) **(integrated)**; **(decision needed)** confirm AGPL is acceptable for an internal tool (it is, if not distributed) |
| C7 | Filtering with HNSW ignored | Post-filtering with `ef_search=40` returns too few rows for selective filters | `hnsw.iterative_scan = relaxed_order`, raised `ef_search`, B-tree/partial indexes on filter columns (file 05, file 07 §T1) **(integrated)** |
| C8 | Reranker assumed in the same model family | Gemini has no reranker endpoint | Local bge-reranker-v2-m3 service, Flash-Lite listwise fallback (file 01 §5.4) **(integrated)** |

## D. Review and halting

| # | Issue | Why it matters | Fix |
|---|-------|----------------|-----|
| D1 | Any flag halts the whole file | One illegible margin note hides a 40-page report | HARD/SOFT severities; strict mode switch (file 06 §2) **(integrated; decision needed on the default: this manual defaults to two-tier)** |
| D2 | Flags as tickets per issue | Reviewer fatigue | Case per document-page; impact-sorted queue; rules with scope (file 06 §5, §9) **(integrated)** |
| D3 | Resolution re-runs OCR/VLM | Slow, costly | Staged payload + resume; re-embed only changed nodes (file 06 §7) **(integrated)** |
| D4 | No undo, no audit | Mistaken bulk rule corrupts 116 runs | `review_events`, 30-day undo, rule versioning (file 06 §6, §8) **(integrated)** |
| D5 | No behavior defined for halted data at answer time | Engine silently answers from other runs | Engine reports the halted case (file 06 §10, file 07 §12) **(integrated)** |

## E. Answer engine

| # | Issue | Why it matters | Fix |
|---|-------|----------------|-----|
| E1 | Sanitizer scope unclear after moving to Gemini | Sanitizing Gemini inputs would destroy the pipeline; not sanitizing web queries leaks IP | Sanitizer applies to **web** only; Gemini via Vertex enterprise terms (file 01 §7, file 07 §6) **(integrated; decision needed: Vertex project/region)** |
| E2 | Free-form SQL from the LLM for DuckDB | Wrong columns/units; injection | Template SQL with validated canonical channel names (file 07 §T2) **(integrated)** |
| E3 | No claim-level verification | Hallucinated numbers in prose | Structured claims + verifier + string match for numerics (file 07 §7–8) **(integrated)** |
| E4 | Prompt injection from documents not considered | A PDF containing "ignore instructions" could steer the agent | Retrieved text as quoted data; tools never execute content; monitor (file 07 §12) **(integrated)** |
| E5 | External results blended with internal | Mis-attribution | Separate "External sources" block; provenance per trade-matrix cell (file 07 §6, §9.5) **(integrated)** |
| E6 | Clarification policy undefined | Engine guesses the run | Ask only when it changes a tool call; offer the default (file 07 §10) **(integrated)** |
| E7 | Degradation on LLM outage undefined | Hard failure | Extractive mode (file 07 §12) **(integrated)** |

## F. Frontend

| # | Issue | Why it matters | Fix |
|---|-------|----------------|-----|
| F1 | "Custom React/Svelte sidebar tabs inside Open WebUI" | Not supported without forking a fast-moving repo | Separate Console + Pipe/Action/embeds/Skills integration (file 08 §2) **(integrated)** |
| F2 | Pipelines server assumed | Marked legacy | Pipe function in-process (file 08 §1) **(integrated)** |
| F3 | Built-in Evaluations assumed to cover benchmarking | It is arena/ELO, not golden-set regression | Benchmark UI with retrieval-only metrics and failure classes (file 08 §5) **(integrated)** |
| F4 | Benchmark measured only end-to-end | Cannot tell retrieval misses from synthesis errors | `retrieval_gold_node_ids`, recall@30/@8, failure classification, Retrieval lab (file 08 §5.4) **(integrated)** |
| F5 | Judge = the same model/prompt as the answerer | Self-grading bias | Separate verifier prompt; same verifier in prod and bench; hold-out cases (file 08 §5.7) **(integrated)** |

## G. Operations and cost

| # | Issue | Fix |
|---|-------|-----|
| G1 | No cost ledger for cloud calls | `llm_calls` + daily budget alerts; Batch API for backfills; vision cache; one enrichment call per parent (file 04 §9) **(integrated)** |
| G2 | No observability plan | OpenTelemetry across FastAPI/Celery/LlamaIndex; Prometheus metrics; Ops page (file 01 §5.7, file 08 §4.2) **(integrated)** |
| G3 | No retention policy | File 05 §6 **(integrated; decision needed on windows)** |
| G4 | Environment reproducibility | Review rules and prompts versioned and exportable to the repo (file 06 §8, file 08 §3.2) **(integrated)** |

## H. Decisions (resolved 2026-10-21)

| # | Question | Decision | Where it is applied |
|---|----------|----------|---------------------|
| 1 | Gemini endpoint | **Manastu's Gemini gateway on Cloud Run**, which calls Gemini in Manastu's Vertex AI project. The pipeline never calls Vertex or the Developer API directly. Configuration comes from the shared `.env` (`GEMINI_BACKEND=gateway`, `GEMINI_GATEWAY_URL`, `GEMINI_GATEWAY_KEY`); `GOOGLE_API_KEY` must never be set. Key values are filled in by the user once the code structure exists | file 01 §7, §7.1 |
| 2 | Default halt policy | **Two-tier** (HARD halts, SOFT flows); strict mode stays a switch | file 06 §2 |
| 3 | Fallback for Gemini | **None.** Every other model is local; Gemini is the only cloud model and has no offline stand-in. On outage the Answer Engine degrades to extractive mode and ingestion waits. In Open WebUI only Gemini credentials are configured | files 01 §5.4, 07 §12, 08 §1 |
| 4 | Graph application permissions | **Future scope.** Build on the delegated app `dcl-reader-delegated` as decided; the env already carries the certificate variables for a later application-permission variant | file 02 §1 |
| 5 | Retention windows | **Defaults** (90 / 30 / 180 / 365 days) | file 05 §6 |
| 6 | Teams digests for review aging | **Not now.** The existing alert webhook is reserved for operational alerts | file 06 §9 |
| 7 | Root-level ACLs | **Confirmed**: all engineers see all four roots; the per-root switch remains available | file 07 §13 |
| 8 | Workflow durability runtime | **DBOS** (`llama-agents-dbos`, PostgreSQL-backed) | files 01 §5.2, 07 §2 |
| 9 | pg_search (AGPL) | **Keep it as long as it is the most favorable choice**: it stays while (a) identifier and multilingual lexical recall on the benchmark beats the native-FTS fallback, (b) the pinned ParadeDB image is maintained for the PostgreSQL major version in use, and (c) the deployment remains internal (no distribution). Any of these failing triggers the documented fallback switch | file 01 §5.5 |
| 10 | Translation mode default | **`enrichment_only`**; revisit after the first `MULTILINGUAL` benchmark run | file 04 §10 |
| 11 | Download / processing scope during development | **Download everything the gate accepts** (all folders except the junk-mapped ones); **process** only the SME-chosen test folders until the full-corpus run (M6) | files 02 §3.1a, 10 §3 |
| 12 | GPU | **Yes**: EmbeddingGemma 2 and bge-reranker-v2-m3 run on the GPU with local disk storage; everything else on CPU, disk and RAM in Docker | files 01 §6, 10 §4 |

### H.1 Still open (not blocking the start)

- **Gateway API contract (verified live on 2026-10-21/22 against the Manastu gateway; host and key never recorded).**
  1. *Style and paths:* a custom Flask-style API wrapping the google-genai SDK. `GET /health` (public: status, project, location); `GET /models` (returns `default`, `embedding[]`, `generation[]`; `gemini-3.8-flash`, `gemini-3.8-flash-lite`, `gemini-3.8-pro` are listed, default is `gemini-3.7-flash`, so the client must always send `model`); `POST /generate`; `POST /stream` (server-sent events, `data: {...}` chunks, final event `{done, usage, quota}`); `POST /embed`; `GET /caches` and `POST /caches` (body needs `contents`); `GET /usage` (daily `limit`, `remaining`, `used_today`). Google-native and OpenAI-style paths do not exist. The client's default adapter is therefore `ManastuGatewayAdapter` (`GEMINI_API_STYLE=manastu`); the Gemini-native and OpenAI adapters stay for other gateways.
  2. *Auth:* header `X-API-Key: <GEMINI_GATEWAY_KEY>` only (Bearer, `api-key`, and query parameters are rejected). The key contains shell-special characters: parse `.env` with a dotenv parser, never by sourcing it in a shell.
  3. *Request body of `/generate`:* Gemini-native `contents` (or a plain `prompt`), optional `model`, and a `config` object with google-genai `GenerateContentConfig` fields (`generation_config` is accepted as an alias): `response_mime_type` + `response_schema` (structured output works and the response carries a `parsed` field), `thinking_config.thinking_level` / `include_thoughts`, `system_instruction`, `tools.function_declarations` (function calls come back as parts), `temperature`. Images as `inline_data` parts work; per-part `media_resolution` works (a 64 px test image cost 1,089 tokens at default or high and 256 at low).
  4. *Response of `/generate`:* the SDK response serialized: `candidates[].content.parts` (with `thought_signature`), `finish_reason`, `model_version`, `response_id` (the request id for `llm_calls`), `usage_metadata` (`prompt_token_count`, `candidates_token_count`, `thoughts_token_count`, per-modality details, `cached_content_token_count` when a cache is used), plus the gateway's `quota`. Upstream errors arrive as HTTP 502 `{error: "upstream Gemini error", detail}`; validation errors as 400 `{error}`.
  5. *PDF / large input:* not yet probed; use `inline_data` under 20 MB, otherwise page windows; a Files-API passthrough is not exposed.
  6. *Media resolution:* per-part `media_resolution.level` with values `media_resolution_low|medium|high`, policy in file 03 §3.
  7. *Caching:* implicit caching is automatic on 3.8 Flash; explicit caches via `POST /caches` with `contents` (fields to be confirmed when first used).
  8. *Batch:* not exposed; flag stays off.
  9. *Limits:* no documented body limit beyond the operator's 4 GB; apply the resilience checklist (429/503 Retry-After, jittered backoff, bounded concurrency, circuit breaker, idempotency key, timeouts).
  10. *Request id:* `response_id`.
  11. *Usage:* `usage_metadata` on every `/generate` response and in the final `/stream` event; `quota` on every response.
  12. *`/embed`:* `{model: "gemini-embedding-2", contents: [...], config: {output_dimensionality}}` returns `embeddings[].values` (3,072 dims by default, 768 when requested). **Not used by the pipeline**: the index uses local EmbeddingGemma 2 (file 04 §5), and vectors from two models cannot share one index; `/embed` remains available for benchmark comparisons only.
- **Object store.** MinIO's images are no longer pullable (Docker Hub and quay) and the upstream repository is archived at `RELEASE.2025-10-15T17-29-55Z` (verified 2026-10-21). Decision: build MinIO from that pinned source tag in `backend/devops/docker/minio.Dockerfile` so M0 proceeds reproducibly on the internal network; S4 evaluates a maintained S3-compatible replacement (candidates: RustFS, SeaweedFS, Garage; must offer bucket versioning, lifecycle expiry, presigned GETs and DuckDB `httpfs` access) and the Lead decides **before the full-corpus run (M6)**, because migrating object storage after the corpus is loaded is expensive. S1's storage client stays plain S3-API code either way.
- **Graph permission option.** The env offers option A (`Files.SelectedOperations.Selected` on the shared folders, preferred) and option B (`Files.Read.All`). The code reads `DCL_PERMISSION_OPTION` and must work with either; A is the default assumption.

## I. Independent schema review (October 2026) and what changed

A second, independent review of file 05 (run against a throwaway PostgreSQL 16 instance, not from the text alone) found that the first schema had 40 tables, of which about a third held data for 1–6 source files or duplicated another table, plus defects that would have surfaced in production. All of it is now in file 05; the list below is the record.

### I.1 Consolidation (40 → 26 tables)

| Removed or folded | Into | Reason |
|-------------------|------|--------|
| `hash_memo` | index on `blobs(quick_xor_hash, size_bytes)` | same lookup |
| `drive_items_resync` | `drive_items.resync_gen` | a 410 resync is rare; a mirror table costs a migration per schema change |
| `archive_members` | `blob_derivations` (generalized) | the same parent→child shape is needed for PDF attachments, embedded workbooks and replacement uploads |
| `stage_completions` + `task_runs` | `jobs` | one unit of work, one row; the old key allowed duplicates through NULL columns and included a location id, which re-processed copies |
| `documents.primary_blob_sha256`, `documents.assembled_from`, `drive_items.doc_id` | `document_sources` only | three representations of one relationship; locations are derived by join |
| `node_image_embeddings` | `document_nodes.image_embedding` | one image vector per photo/figure node |
| `cad_geometries` | dropped | no STL/STEP files in the inventory; the single `.scdoc` is a `cad_reference` document |
| `cae_projects`, `diagram_nodes`, `diagram_edges` | `documents.catalog` JSONB | one ANSYS archive and six diagrams; traversal in Python |
| `folder_channel_maps` | `rules` | channel maps were stored twice (derived and operator) with two resolvers |
| `staged_payloads` | `documents.staged_payload_uri` | 1:1 with a halted document |
| `pipeline_config_history` | append-only `pipeline_config (key, version)` | history is just older versions |
| `vision_cache` | MinIO prefix with lifecycle | an LRU in PostgreSQL turns every cache hit into a write |
| `answer_feedback` | columns on `answer_traces` | one trace, one message, one user |
| `benchmark_suites` | `suite` column on cases + case-version snapshot on runs | a few suites of ~60 cases |
| `web_search_log` | `answer_traces.external_queries` | duplicate |
| `review_events` | `audit_events` (generalized) | entity merges, rule and config changes also need an audit home |
| `entity_aliases` (single table) | `entities` + `entity_aliases` | the only addition: as written, mentions could not reference a non-unique `entity_id` |

### I.2 Defects fixed

| # | Defect in the first schema | Why it hurt | Fix |
|---|----------------------------|-------------|-----|
| S1 | Human corrections written into derived rows; flags inserted without a key | a re-index wiped corrections and reopened resolved flags | resolutions stored on the flag with a stable anchor and re-applied as overlays; flags upserted by `(doc_id, fingerprint)` (file 04 §7, file 06 §1) |
| S2 | Node ids referenced durably (benchmark gold, citations, deep links) | node ids change on every re-index, silently zeroing retrieval metrics and breaking links | stable anchors `{doc_id, page/line/time, content hash}` resolved at read time (file 04 §4.4) |
| S3 | `content_codes` as a PostgreSQL generated column with a `\b` regex | `\b` is backspace in PG regex; set-returning functions are not allowed in generation expressions; PG 16 cannot alter the expression without a table rewrite | plain column computed in Python by the function the query side also uses (file 04 §6) |
| S4 | FK columns without indexes (`entity_mentions.node_id`, `numeric_facts.node_id`, …) | deleting one document's 250 nodes took 6.2 s instead of 7 ms in the reviewer's reproduction | every FK indexed; CI query enforces it (file 05 §3) |
| S5 | Commit deleted only the new `pipeline_version` | old versions accumulated in HNSW and BM25 forever and starved filtered scans | delete by `doc_id`, reuse vectors by text hash (file 04 §7) |
| S6 | Supersession per item, status per blob-level document | a copy of the old file elsewhere lost its status and its link | `SUPERSEDES` relation only; status changes when no live location holds the old blob; locations derived (file 02 §5.1) |
| S7 | PK `item_id` alone; FK from items to parent folder | Graph ids are unique only per drive; children arrive before parents | `(drive_id, item_id)` unique + surrogate keys; indexed parent column with no FK (file 02 §3.1) |
| S8 | `assets` duplicated on every re-index; circular FK with nodes | unbounded growth; awkward deletes | unique `minio_uri` with upsert; one FK direction (file 05 §4.2) |
| S9 | `telemetry_runs.run_id` as a mutable natural key and MinIO prefix | folder renames and collision suffixes renumbered runs and broke Parquet paths | `run_uuid` PK + unique `run_label` (file 03 §C.1) |
| S10 | Hot-update counters (`applied_count`, `ref_count`, `has_soft_flags`) | lock contention and drift | derived by query or view (file 05 §4.5, §6) |
| S11 | Enum values already disagreed between files | silent inconsistency | text columns with CHECK constraints generated from one Python enum (file 05 §3) |
| S12 | Review cases without a key or a home for assignment | duplicate cases from concurrent workers; `REOPENED` missing | deterministic `case_key`; `page_or_sheet` as a column; case state derived (file 06 §5) |
| S13 | JSONB/column balance wrong (rule scope in JSON; benchmark spec in columns) | scope is the matching key; benchmark fields drift | scope columns on `rules`; `spec`/`metrics` JSONB on benchmark tables (file 05 §4.5, §4.7) |
| S14 | Trace retention vs FKs | purging traces broke benchmark references | `pinned` traces; `ON DELETE SET NULL` (file 05 §6) |
| S15 | Two documents possible for one blob under parallel downloads | duplicate processing | conflict-safe blob insert + partial unique index on `document_sources` (file 02 §6) |
| S16 | Cloud/ACL policy per root, processing per blob, `documents.root_name` assumed | a document can live in several roots | most restrictive live location wins; roots derived via `v_doc_locations` (file 07 §13) |
| S17 | All tables created in M0 | empty tables created early end up with the wrong shape | tables created in the milestone whose code writes them (file 05 §7) |

## J. Changes after the first version of this manual (approved 2026-10-21)

| Topic | Change | Where |
|-------|--------|-------|
| Embeddings | Gemini Embedding 2 (cloud, 1536-d) → **EmbeddingGemma 2** (local, 768-d, multimodal, Apache 2.0) | files 01 §5.4, 04 §5, 05 §4.2, 10 M0 |
| Knowledge-base scope | external library (brochures, datasheets, papers, articles) made explicit with `source_origin`, trust tiers, provenance labels in answers | files 03 §A1.12, 04 §2.3, 05 `documents`, 07 §5–§7 |
| Multilingual | per-page language and script; OCR engine per script; English enrichment layer; cross-lingual retrieval; per-language BM25 fields; translation as a config mode; locale-aware numbers | files 03 §A1.2–A1.3, 04 §3.2, §5.5, §6, §10, 08 §3.2 |
| Schema | 40 → 26 tables; defects S1–S17 | file 05, section I above |
| Rollout | metadata-only crawl of everything; download and processing scopes; route gating; Review UI moved to M3; queue load test in M1; full-corpus run as M6 | files 02 §3.1a, 03 §1.6, 10 §3, §5 |
