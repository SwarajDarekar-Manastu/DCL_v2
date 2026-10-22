# 05 — Storage: MinIO Layout, Parquet Conventions, PostgreSQL Schema

Everything is keyed by content hash or surrogate id; nothing is keyed by a OneDrive path. The schema has **26 tables**, each labelled with one of three tiers that decide how it is treated:

| Tier | Tables | Rules |
|------|--------|-------|
| **Authored** | `rules`, `review_flags` (resolutions), `pipeline_config`, `benchmark_cases`, `entities`/`entity_aliases` (merges) | written by humans or by code on a human's behalf; never rebuilt; every change audited in `audit_events`; exportable to YAML |
| **Registry** | `sync_roots`, `drive_folders`, `drive_items`, `blobs`, `blob_derivations`, `documents`, `document_sources`, `document_relations`, `jobs`, `telemetry_runs` | the system's memory of what exists and in which state; updated in place; soft-deleted only where an outside source of truth says "deleted" |
| **Derived** | `document_nodes`, `entity_mentions`, `numeric_facts`, `assets`, `telemetry_channels`, `documents.catalog`, `llm_calls`, `answer_traces`, `benchmark_runs`, `benchmark_results` | rebuildable from the CIR, Parquet or traces; hard-deleted and re-inserted; never hand-edited |

Types are PostgreSQL. `JSONB` columns have their expected shape spelled out. A ✓ after a column means a `text` column with a named `CHECK` constraint whose allowed values are generated from one Python `StrEnum` (no native PG enum types).

## 1. MinIO buckets

| Bucket | Key layout | Contents | Lifecycle |
|--------|-----------|----------|-----------|
| `dcl-raw` | `{sha256[0:2]}/{sha256[2:4]}/{sha256}` with object metadata `original_name`, `mime_detected`, `first_location_id` | original bytes of every accepted file and every archive member | kept while any `document_sources` row references the blob; purged 90 days after the last referencing document is `DELETED` |
| `dcl-raw` | `_restricted/{sha256}` | blobs quarantined for secrets/sensitive markings | never sent to Gemini; purge on operator action |
| `dcl-cir` | `{sha256}/{route}/v{parser_version}/…` | Canonical Intermediate Representations (file 03 §2); `{sha256}/staged.json` for halted documents | versioned; older parser versions purged 30 days after a newer one is committed |
| `dcl-cir` | `_vision_cache/{model}/{prompt_version}/{input_sha256}.json` | VisionService results | MinIO lifecycle rule: expire 180 days after last modification |
| `dcl-assets` | `pages/{sha256}/{page:04d}.png` · `figures/{sha256}/{figure_id}.png` · `crops/{sha256}/{crop_id}.png` · `photos/{sha256}/web.jpg` · `photos/{sha256}/thumb.jpg` · `frames/{sha256}/{t_ms}.jpg` · `diagrams/{sha256}/{page}.png` · `sparklines/{run_uuid}/{channel}.png` | everything the UI renders; keys are deterministic per blob so re-indexing overwrites instead of duplicating | follows the blob |
| `dcl-telemetry` | `{run_uuid}/raw.parquet` · `{run_uuid}/normalized.parquet` · `{run_uuid}/schema.json` | time-series | follows the run |
| `dcl-exports` | `benchmarks/{run_id}.json` · `reports/…` · `rules/{date}.yaml` | downloadable artifacts | 180 days |

Presigned GET URLs (15-minute TTL) are minted by the Console API / Answer Engine API after checking the caller's session. Open WebUI never talks to MinIO directly.

## 2. Parquet conventions

- One run per directory named by the run's UUID (labels can change; UUIDs cannot); `raw.parquet` keeps original column names and units; `normalized.parquet` uses canonical snake_case names with the unit suffix: `t_rel_ms`, `t_from_ignition_ms`, `pt_101_chamber_bar_abs`, `pt_101_chamber_bar_g`, `thrust_n`, `tc_bed_k`, `mdot_g_s`, `heater_w`, `valve_state` (int8 0/1), `sub_run` (int16).
- Each Parquet **field** carries key-value metadata: `unit`, `quantity`, `raw_name`, `raw_unit`, `conversion`, `sensor_tag`. Each **file** carries `run_uuid`, `run_label`, `source_blob_sha256`, `parser_version`, `t0_ignition_ms`, `t0_method`, `t0_confidence`.
- Row groups of 100k rows, ZSTD compression, dictionary encoding for `valve_state`.
- DuckDB access: `INSTALL httpfs; SET s3_endpoint=…; SELECT … FROM read_parquet('s3://dcl-telemetry/{run_uuid}/normalized.parquet')`. The Answer Engine's telemetry tool builds SQL only against `normalized.parquet` and only with column names taken from `telemetry_channels`.

## 3. PostgreSQL conventions

- Extensions: `vector` (pgvector 0.8.x), `pg_search` (ParadeDB, pinned version), `pg_trgm`, `pgcrypto`.
- `TIMESTAMPTZ` everywhere, UTC. Surrogate keys are `uuid` for registry tables and `bigint identity` for the two high-volume derived tables (`entity_mentions`, `numeric_facts`).
- Naming: plural snake_case tables; FK columns named exactly like the referenced key (`doc_id`, `blob_sha256`); `*_at` for timestamps, `*_uri` for object paths, `is_`/`has_` for booleans; every lifecycle column is called `status` and is CHECK-constrained.
- **Every FK column has an index.** A CI query lists FK columns without a leading index and fails the build.
- No native enum types; no table partitioning (volumes stay in the low millions per year; HNSW must be a single index).
- SQLAlchemy `MetaData(naming_convention=…)` is set before the first migration so constraint names are stable across environments. Alembic autogenerate is used with `include_object` excluding the HNSW and BM25 indexes and CHECK constraints, which live in hand-written migration files. CI runs `alembic upgrade head` and `alembic check` on the pinned ParadeDB image.
- Hot paths (node, mention, fact bulk insert at commit) use Core + `COPY`; Console CRUD uses the ORM.

## 4. Tables

### 4.1 Registry and processing (6)

**`sync_roots`** — one row per shared folder we crawl.

| Column | Type | Meaning |
|--------|------|---------|
| `root_name` | text PK | human name as shared (`APU Injector`) |
| `remote_drive_id`, `remote_item_id` | text | owner's drive and folder item ids |
| `delta_link` | text | last committed `@odata.deltaLink` |
| `next_link_checkpoint` | text | last committed `@odata.nextLink` during a crawl (resume point) |
| `status` ✓ | text | `ACTIVE`, `CRAWLING`, `RESYNCING`, `UNREACHABLE`, `PAUSED` |
| `auth_status` ✓ | text | `OK`, `REAUTH_REQUIRED` |
| `subscription_id`, `subscription_expires_at` | text, timestamptz | Graph webhook subscription |
| `cloud_allowed` | boolean | may content under this root be sent to Gemini |
| `default_source_origin` ✓ | text | `internal` or `external_kept` for documents under this root unless a folder rule or detector says otherwise |
| `last_full_crawl_at`, `last_delta_at` | timestamptz | — |

**`drive_folders`** — folder tree; the only source of paths and of O(1) junk/quarantine decisions.

| Column | Type | Meaning |
|--------|------|---------|
| `folder_id` | uuid PK | surrogate |
| `drive_id`, `item_id` | text | UNIQUE together (Graph ids are unique only within a drive) |
| `parent_item_id` | text | indexed, **no FK** (children can arrive before parents) |
| `root_name` | text FK | — |
| `name` | text | — |
| `is_junk`, `is_quarantine` | boolean | Tier-1 / quarantine pattern matched |
| `source_origin_override` ✓ | text | optional per-folder origin (`external_kept` for a library subfolder) |
| `path_cached` | text | computed breadcrumb path |
| `deleted_at` | timestamptz | — |

**`drive_items`** — one row per OneDrive file item: the *location* of content. Phase 1 state only.

| Column | Type | Meaning |
|--------|------|---------|
| `location_id` | uuid PK | surrogate |
| `drive_id`, `item_id` | text | UNIQUE together |
| `root_name` | text FK | — |
| `parent_item_id` | text | indexed, no FK |
| `name`, `extension`, `size_bytes` | — | from Graph |
| `quick_xor_hash`, `etag` | text | L0 change detection; metadata change marker |
| `web_url` | text | clickable OneDrive link |
| `last_modified_at`, `created_at_source` | timestamptz | display only |
| `path_cached` | text | computed from the folder tree |
| `status` ✓ | text | `SEEN`, `SKIPPED_JUNK`, `SKIPPED_EMPTY`, `SKIPPED_SHORTCUT`, `SKIPPED_UNSUPPORTED_PACKAGE`, `QUARANTINED`, `HELD_LARGE_FILE`, `HELD_BY_SCOPE`, `PENDING_DOWNLOAD`, `DOWNLOAD_FAILED`, `LANDED`, `DELETED` |
| `gate_reason` | text | tier and matched pattern (`T1:.venv`, `T2:.aux`, `T4:secret`, `SCOPE:not_in_download_scope`) |
| `detected_mime`, `ext_mime_mismatch` | text, boolean | post-download type check |
| `blob_sha256` | char(64) FK → blobs, indexed | null until landed |
| `previous_blob_sha256` | char(64), partial index (where not null), no FK (blobs may be purged) | set by `land_item` when new content replaces a different blob at this location; a pending (non-null) value is never overwritten, so a fast double edit still points at the oldest superseded blob. The dispatcher writes `document_relations(SUPERSEDES)` new → old, marks the old document `SUPERSEDED` only when no live location still holds the old blob, then clears the column. A periodic sweep catches documents that no live location holds (decided 2026-10-22) |
| `resync_gen` | int | generation stamp written during a 410 resync; items not stamped with the current generation are candidates for the per-item deletion check (replaces a staging table) |
| `last_seen_delta_at`, `deleted_at`, `error_last` | — | — |

Document-level state (processing, halted, indexed) is **not** on this table; it lives on `documents`, which is shared by every location of the same content. Locations of a document are derived: `document_sources ⋈ drive_items ON blob_sha256`.

**`blobs`** — content-addressed objects.

| Column | Type | Meaning |
|--------|------|---------|
| `sha256` | char(64) PK | identity |
| `quick_xor_hash`, `size_bytes` | text, bigint | indexed together: the "have I seen this quickXorHash" lookup that skips a download on second sighting (quickXorHash is not cryptographic, hence the size in the key) |
| `mime_detected` | text | — |
| `minio_uri` | text | `s3://dcl-raw/…` or `_restricted/…` |
| `restricted` | boolean | quarantined content |
| `first_seen_at` | timestamptz | — |

Blob insert is `ON CONFLICT DO NOTHING` so two parallel downloads of the same new content cannot create two documents (the partial unique index on `document_sources` below is the second guard). No reference counter: the weekly purge uses `NOT EXISTS` against `document_sources` and `drive_items`.

**`blob_derivations`** — parent-to-child blob relationships: archive members, PDF attachments, embedded workbooks, redacted or replacement copies uploaded by an operator.

| Column | Meaning |
|--------|---------|
| `parent_blob_sha256`, `member_path` | PK pair (`member_path` is the path inside the archive, the attachment name, or `redacted`/`replacement`) |
| `child_blob_sha256` | FK → blobs, indexed |
| `kind` ✓ | `archive_member`, `pdf_attachment`, `embedded_object`, `redacted_copy`, `replacement_upload` |
| `gate_reason` | for members skipped by the gate |
| `created_by` | `system` or operator id |

**`jobs`** — idempotency ledger and task history in one table.

| Column | Meaning |
|--------|---------|
| `job_id` uuid PK | — |
| `job_key` text UNIQUE NOT NULL | built by code from `stage:` + `blob_sha256` or `doc_id` + `:v{parser_version}.{pipeline_version}`; never contains a location id (a second copy of known content must not become a new job) |
| `stage` ✓ | `download`, `dispatch`, `parse`, `enrich`, `index`, `resume`, `reembed`, `translate` |
| `blob_sha256`, `doc_id` | indexed; nullable depending on stage |
| `parser_version`, `pipeline_version` | — |
| `status` ✓ | `queued`, `running`, `done`, `failed` |
| `attempts`, `celery_task_id`, `worker` | — |
| `started_at`, `finished_at`, `duration_ms`, `peak_rss_mb`, `error` | — |

Retention of failed/old job rows must never delete `done` rows of live documents; the idempotency check falls back to `documents.pipeline_version` plus CIR existence if a `done` row is missing.

### 4.2 Documents (5)

**`documents`** — the logical unit of citation and status.

| Column | Type | Meaning |
|--------|------|---------|
| `doc_id` | uuid PK | — |
| `route` ✓ | text | `A1`, `A2`, `B`, `C`, `D`, `E`, `F`, `G` |
| `title` | text | L1 title |
| `doc_kind` ✓ | text | `standard`, `test_plan`, `test_report`, `failure_report`, `calibration`, `risk_assessment`, `material_spec`, `procedure`, `workshop_slides`, `code`, `tooling_doc`, `telemetry_run`, `engineering_table`, `hardware_photo`, `plot_figure`, `diagram`, `schema`, `video_transcript`, `video_timeline`, `cae_package`, `cad_reference`, `config`, `vendor_brochure`, `datasheet`, `academic_paper`, `article`, `book_excerpt`, `conference_paper`, `unknown` |
| `status` ✓ | text | `WAITING_FOR_ROUTE`, `PROCESSING`, `HALTED`, `ACTIVE`, `ACTIVE_WITH_SOFT_FLAGS`, `SUPERSEDED`, `QUARANTINED`, `DELETED`, `FAILED` |
| `source_origin` ✓ | text | `internal`, `external_kept` |
| `trust_tier` | smallint | 1–6 (file 04 §2) |
| `publisher` | text | vendor/publisher/journal when known |
| `external_ids` | jsonb | `{doi, arxiv, isbn, report_number}` |
| `test_plan_id`, `test_run_id`, `hardware_item` | text | L1 |
| `doc_date`, `date_source` | date, text | L1 with provenance |
| `standard_id`, `standard_revision` | text | standards only |
| `revision_marker`, `classification_marking` | text | footer/watermark findings |
| `language`, `languages_detected`, `number_locale` | text, text[], text | — |
| `page_count`, `unit_count` | int | pages / slides / sheets / symbols |
| `folder_context`, `metadata_sources`, `enrichment` | jsonb | file 03 §1.2, file 04 §2, §3.4 |
| `catalog` | jsonb | route-specific structured payloads that are too small for tables: the draw.io graph (`{nodes[], edges[]}`), the ANSYS project summary, the SpaceClaim/STEP reference |
| `entity_ids` | uuid[] | GIN; canonical entity ids (ids, not names, so merges do not stale it) |
| `search_text` | text | English title + summary + entity names; BM25 |
| `cir_uri` | text | prefix in `dcl-cir` |
| `staged_payload_uri` | text | CHECK: non-null exactly when `status = 'HALTED'` |
| `parser_version`, `pipeline_version` | int | — |
| `cloud_processed` | boolean | content was sent to Gemini |
| `created_at`, `updated_at`, `indexed_at` | timestamptz | — |

Indexes: `(status)`, `(doc_kind, status)`, `(test_plan_id)`, `(test_run_id)`, `(standard_id)`, `(source_origin, trust_tier)`, GIN `(entity_ids)`, GIN `(enrichment jsonb_path_ops)`, BM25 on `(search_text, title)`.

**`document_sources`** — the only link between documents and blobs.

| Column | Meaning |
|--------|---------|
| `doc_id`, `blob_sha256`, `role` | PK triple |
| `role` ✓ | `primary`, `part`, `visual_twin`, `channel_map`, `calibration`, `bibliography`, `attachment`, `replacement` |

Partial unique indexes: one `primary` per document, and one document per `primary` blob (the guard against two documents for one blob). Index on `blob_sha256`.

**`document_relations`**

| Column | Meaning |
|--------|---------|
| `doc_id_a`, `doc_id_b`, `relation` | PK triple; CHECK `doc_id_a < doc_id_b` for symmetric relations |
| `relation` ✓ | `SUPERSEDES` (a supersedes b), `NEAR_DUPLICATE`, `REFERENCES` |
| `score`, `created_by` | — |

Index on `doc_id_b`. Part-of, visual-twin, archive and photo-cluster relationships are **not** here (they live in `document_sources`, `blob_derivations` and `assets.photo_cluster_id`).

**`document_nodes`** — the retrieval unit (250–500k rows).

| Column | Type | Meaning |
|--------|------|---------|
| `node_id` | uuid PK | regenerated on every re-index; never stored durably elsewhere (file 04 §4.4) |
| `doc_id` | uuid FK | index `(doc_id, ordinal)` |
| `parent_node_id` | uuid | indexed; null for parents and top-level special nodes |
| `node_type` ✓ | text | `parent`, `child`, `table`, `table_row`, `figure`, `code_symbol`, `module_header`, `slide`, `transcript_window`, `video_event`, `run_summary`, `photo`, `diagram_summary`, `diagram_component`, `question_proxy`, `config` |
| `level`, `ordinal`, `breadcrumb` | smallint, int, text | — |
| `language` | text | per node (page/segment) |
| `content` | text | clean text / HTML table / code / structured reading rendered as text, in the source language |
| `content_en` | text | optional Gemini translation when `translation.mode = full` |
| `content_codes` | text | identifier tokens computed in Python (file 04 §6) |
| `content_sha256` | char(64) | normalized-content hash used by stable anchors |
| `embed_text`, `embed_text_hash` | text, char(64) | what was embedded; hash enables vector reuse |
| `embedding` | halfvec(768) | text vector; null for parents when parent embedding is off |
| `image_embedding` | halfvec(768) | photo/figure nodes only |
| `embedding_model` | text | `embeddinggemma-2@768` |
| `token_count` | int | — |
| `page_no`, `page_end`, `bbox`, `line_start`, `line_end`, `t_start_ms`, `t_end_ms`, `sheet_name`, `cell_range` | anchors | `bbox` is a JSON list of `{page_no, x0, y0, x1, y1}` **normalized to 0..1 with a top-left origin** (one entry per page the node spans), so overlays scale to any render; routes convert Docling's bottom-left points |
| `asset_id` | uuid FK → assets, indexed | figure/photo/frame/crop |
| `source` ✓ | text | `printed`, `ocr`, `vlm`, `source_code`, `structured`, `human` |
| `confidence` | real | for `ocr`/`vlm` |
| `needs_review` | boolean | a SOFT flag anchors here |
| `doc_kind`, `test_plan_id`, `source_origin`, `trust_tier`, `doc_status` | denormalized from `documents` at commit | lets filtered vector searches avoid the join; `doc_status` is refreshed by the (rare) status changes |
| `metadata` | jsonb | node-type-specific: tables `{n_rows, n_cols, units_by_column, caption, part}`, figures `{class, structured_reading}`, handwriting `{regions[]}`, code `{symbol, qualname, calls[], imports[]}`, runs `{run_uuid}`, diagrams `{component_tag, neighbors[]}` |
| `pipeline_version` | int | informational (visibility no longer depends on it) |

Indexes: HNSW `(embedding halfvec_cosine_ops) WITH (m=16, ef_construction=128)`; HNSW on `image_embedding`; BM25 over `(content, breadcrumb, content_codes, content_en)` with per-language fields; btree `(doc_id, ordinal)`, `(node_type)`, `(parent_node_id)`, `(test_plan_id)`, `(doc_kind)`, `(source_origin, trust_tier)`; partial `(doc_id) WHERE needs_review`. For selective filters (one test plan) the retriever skips the ANN index and computes exact distances over the btree-filtered rows (file 07 §4 T1).

**`assets`** — renderable artifacts; follow the blob, survive re-index.

| Column | Meaning |
|--------|---------|
| `asset_id` uuid PK | — |
| `minio_uri` text UNIQUE | deterministic per blob/page/crop; upsert key |
| `blob_sha256` FK, indexed | owner |
| `kind` ✓ | `page_render`, `figure_crop`, `handwriting_crop`, `table_crop`, `photo_web`, `photo_thumb`, `photo_in_doc`, `video_frame`, `diagram_render`, `sparkline` |
| `page_no`, `bbox`, `t_ms` | anchors |
| `width`, `height`, `bytes` | — |
| `phash` | 64-bit hex for images |
| `photo_cluster_id`, `is_cluster_representative` | uuid, boolean |
| `exif` | jsonb (GPS removed) |

Only `document_nodes.asset_id → assets` exists; there is no back-reference from assets to nodes.

### 4.3 Entities and numbers (4)

**`entities`** — `entity_id` uuid PK; `type` ✓; `canonical_name`; `canonical_key`; UNIQUE `(type, canonical_key)`; `created_by` ✓ (`seed`, `system`, `operator`); `first_seen_doc_id`.

**`entity_aliases`** — PK `(type, alias_key)`; `entity_id` FK indexed; `alias`; `created_by` ✓ (`seed`, `system_exact`, `system_fuzzy`, `operator`); `fuzzy_score`. A merge re-points aliases and mentions; there is no `merged_into` column.

**`entity_mentions`** — `mention_id` bigint identity PK; `node_id` FK **indexed**; `doc_id` indexed; `entity_id` FK indexed; `surface`; `span_start`, `span_end`; `confidence`; `source` ✓ (`regex`, `llm`, `human`).

**`numeric_facts`** — `fact_id` bigint identity PK; `node_id` FK **indexed**; `doc_id` indexed; `quantity` ✓; `value_raw`, `unit_raw`; `value_si`, `unit_si`; `gauge_or_abs` ✓ (`gauge`, `absolute`, `unknown`, `n/a`); `context`; `span_start`, `span_end`; `source` ✓ (`printed`, `ocr`, `vlm`, `table`, `telemetry_stat`, `vendor_claim`, `literature`, `human`); `confidence`; `suspect`; `needs_unit`; index `(quantity, value_si)`.

### 4.4 Telemetry (2)

**`telemetry_runs`**

| Column | Meaning |
|--------|---------|
| `run_uuid` uuid PK | stable; MinIO prefix |
| `run_label` text UNIQUE | display and tool input (`TP07_T01`, `INJ14_FAIL_01`); may be renamed by a rule without moving data |
| `doc_id` FK indexed | the document that holds the run summary node; test ids are read from it, not duplicated here |
| `blob_sha256` | source file |
| `source_format` ✓ | `labjack_dat`, `tdms`, `csv`, `xlsx_sheet`, `npy_mapped` |
| `run_status` ✓ | `NOMINAL`, `FAILED_RUN`, `COLD_FLOW`, `PRE_HEAT`, `ABORTED`, `UNKNOWN` |
| `ambient_condition` ✓, `ambient_pressure_bar_abs` | `VACUUM_CHAMBER`, `SEA_LEVEL`, `AMBIENT_RECORDED`, `UNKNOWN` |
| `sampling_rate_hz_nominal`, `sampling_rate_hz_actual`, `duration_s`, `n_rows`, `n_gaps`, `n_duplicate_ts` | — |
| `t0_ignition_ms`, `t0_method`, `t0_confidence` | alignment |
| `sub_runs` | jsonb `[{idx, t_start_ms, t_end_ms, label}]` |
| `raw_parquet_uri`, `normalized_parquet_uri`, `schema_uri` | — |
| `recorded_at` | from header/folder/filename |
| `channel_map_rule_id` | FK → rules; which rule (operator or derived) produced the mapping |
| `clock_offsets` | jsonb `{video_ms, tdms_ms}` |

**`telemetry_channels`** — PK `(run_uuid, canonical_name)`; `raw_name`, `raw_unit`; `quantity`, `unit_si`, `gauge_or_abs` ✓; `conversion` jsonb; `sensor_tag`; `range_min`, `range_max`; `stat_min`, `stat_max`, `stat_mean`, `stat_p50`, `stat_p99`, `stat_std`; `peak_raw`, `peak_50ms`, `steady_mean`, `steady_window_ms`; `saturated`, `null_fraction`; `sparkline_asset_id` FK.

### 4.5 Review (3)

**`review_flags`**

| Column | Meaning |
|--------|---------|
| `flag_id` uuid PK | — |
| `case_key` text NOT NULL, indexed | deterministic: `{doc_id or location_id}:{page_or_sheet}`; the Review UI groups by it |
| `doc_id`, `location_id` | nullable; CHECK at least one set (`HELD_LARGE_FILE` has no document yet) |
| `page_or_sheet` | text column (grouping key, not buried in JSON) |
| `fingerprint` | text; UNIQUE `(doc_id, fingerprint)`; built from flag type + CIR anchor so re-indexing upserts instead of duplicating |
| `flag_type` ✓ | `UNIT_AMBIGUITY`, `SCHEMA_UNKNOWN`, `LOW_CONFIDENCE_EXTRACTION`, `PARSE_FAILURE`, `UNSUPPORTED_FORMAT`, `CONFLICT`, `SENSITIVE_CONTENT`, `HELD_LARGE_FILE`, `CLOUD_RESTRICTED` |
| `severity` ✓ | `HARD`, `SOFT` |
| `status` ✓ | `OPEN`, `IN_PROGRESS`, `RESOLVED`, `REJECTED_FILE`, `AUTO_RESOLVED`, `REOPENED` |
| `route` | — |
| `anchor` | jsonb `{page, sheet, bbox, content_sha256, channel, column, line}` (stable anchor, no node ids) |
| `evidence`, `suggested_resolution`, `resolution` | jsonb |
| `resolution_rule_id` | FK → rules, indexed |
| `assigned_to`, `resolved_by`, `resolved_at`, `due_at`, `created_at` | — |

Case-level state (status, assignee, age) is derived in `v_review_cases` from its flags. Resolutions are **authored data**: the indexer re-applies them as overlays on every rebuild (file 04 §7).

**`rules`** — operator rules and system-derived maps in one table with one precedence resolver.

| Column | Meaning |
|--------|---------|
| `rule_id` uuid PK | — |
| `rule_type` ✓ | `channel_map`, `unit_mapping`, `schema_mapping`, `supersession`, `ignore_pattern`, `origin_override` |
| `origin` ✓ | `operator`, `cfg`, `header`, `config_json`, `tdms_props` |
| `scope_root`, `scope_folder_id`, `scope_filename_glob`, `scope_extension` | columns (the matching key and the specificity order) |
| `body` | jsonb (the mapping itself) |
| `precedence` | int; most specific scope wins, then precedence, then newest |
| `source_blob_sha256` | for derived rules: the `.cfg`/header they came from; replaced when that blob changes |
| `supersedes_rule_id` | versioning: operator rules are immutable; a change inserts a new row |
| `active`, `created_by`, `created_at` | — |

Partial index `(rule_type, scope_folder_id) WHERE active`. "Files affected by this rule" and "applied count" are derived from `review_flags.resolution_rule_id` and `telemetry_runs.channel_map_rule_id`, not stored. YAML export filters `origin = 'operator'`.

**`audit_events`** — append-only log of **human** actions: `event_id` bigint; `at`; `actor`; `entity_type` ✓ (`flag`, `case`, `rule`, `entity`, `config`, `benchmark_case`, `document`); `entity_id` text; `action`; `before`, `after` jsonb; index `(entity_type, entity_id, at)`. Machine activity is covered by `jobs` and `llm_calls`.

### 4.6 Configuration and operations (2)

**`pipeline_config`** — append-only; PK `(key, version)`; `value` jsonb; `updated_by`; `updated_at`; `description`; view `v_config_current` = latest version per key. Rollback = insert the old value as a new version. Secrets and endpoints (Graph app ids, gateway URL and key, database credentials, alert webhook) are **never** stored here; they come from the environment file (file 01 §7.1). Keys include: `gate.*`, `sync.download_scope` (list of root/folder ids/globs allowed to download; empty = everything), `sync.download_concurrency`, `sync.daily_delta_cron`, `processing.scope` (which landed blobs may be processed), `routes.<X>.enabled`, `routes.<X>.parser_version`, `routes.A1.ocr_engine_by_script`, `thresholds.*`, `chunking.*`, `models.*`, `translation.mode`, `translation.full_for`, `sources.origin_defaults`, `flags.severity_overrides`, `flags.strict_mode`, `cloud.vertex_project`, `cloud.region`, `cloud.daily_token_budget`, `sanity_ranges`, `critical_field_patterns`, `report_json_schemas`, `answer.external_allowed_groups` (seeded with `dcl-external-search` by migration seed data, S1), `answer.proprietary_terms` (seeded by S5 from the hardware and project names in the crawl, confirmed by the user), `answer.external_search_enabled` (kill switch, default true; the group list is the real gate).

**`llm_calls`** — `call_id`; `at` (indexed); `model`; `purpose`; `prompt_version`; `doc_id`, `node_anchor`, `trace_id` (no FKs: the ledger outlives documents); `input_tokens`, `output_tokens`, `cached_tokens`; `latency_ms`; `cost_estimate`; `status`; `error`; `request_id`. The daily budget guard aggregates this table.

### 4.7 Answer engine and benchmarks (4)

**`answer_traces`**

| Column | Meaning |
|--------|---------|
| `trace_id` uuid PK | also the OpenTelemetry trace id |
| `chat_id`, `message_id`, `user_id` | Open WebUI identifiers |
| `question`, `conversation_summary`, `user_language` | — |
| `query_analysis`, `tool_calls`, `retrieved` (stable anchors with ranks/scores), `external_queries` (sanitized text, original hash, provider, n_results), `claims`, `citations` (stable anchors), `verifier_result`, `model_config` | jsonb |
| `answer_markdown` | final |
| `latency_ms`, `tokens_in`, `tokens_out`, `cost_estimate` | — |
| `rating`, `feedback` | smallint, jsonb (thumbs, "report issue" payloads; appended by single-statement JSONB updates) |
| `pinned` | boolean; excluded from retention (referenced by benchmark cases) |
| `created_at` | — |

**`benchmark_cases`** — PK `(case_id, version)`; `suite` text; `status` ✓ (`draft`, `active`, `retired`); `category` ✓; `question`; `spec` jsonb (`paraphrases`, `expected_numeric`, `expected_citations`, `must_not_cite`, `expected_tools`, `expected_entities`, `expected_behavior`, `retrieval_gold_anchors` (stable anchors, not node ids), `clarification_answer`, `language`); `difficulty`; `notes`; `source_trace_id` (ON DELETE SET NULL); `created_by`, `created_at`.

**`benchmark_runs`** — `run_id` PK; `suite`; `case_versions` jsonb snapshot; `git_commit`; `model_config` jsonb; `pipeline_version`; `active_doc_count`; `status` ✓ (`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`); `started_at`, `finished_at`; `aggregate` jsonb.

**`benchmark_results`** — PK `(run_id, case_id)`; `case_version`; `trace_id`; `passed`; `failure_class` ✓; `latency_ms`; `cost_estimate`; `metrics` jsonb (numeric details, citation recall/precision, tool match, faithfulness, retrieval recall@8/@30, reranker margin, judge rationale).

## 5. Views the UI and Answer Engine rely on

- `v_active_nodes`: nodes of documents whose status is active (the denormalized `doc_status` makes this a single-table predicate), with title, test ids, kind, origin, tier and `has_soft_flags` derived from status.
- `v_doc_locations`: `documents → document_sources → drive_items` giving every OneDrive path and `web_url` of a document, correct under supersession and copies.
- `v_review_cases`: one row per `case_key` with counts by flag type, derived case status, assignee, oldest `created_at`, preview asset.
- `v_run_catalog`: runs with channel lists and three-tier stats pivoted for the telemetry tool, joined to `documents` for test ids.
- `v_config_current`: latest config per key.
- `v_rule_usage`: rules with derived counts of flags resolved and runs mapped.

## 6. Retention

| Data | Policy |
|------|--------|
| Raw blobs no longer referenced by any document source or live location | purge 90 days after the last referencing document was `DELETED` (weekly job, `NOT EXISTS`) |
| Old CIR parser versions | purge 30 days after a newer one is committed |
| Vision cache | MinIO lifecycle, 180 days |
| `llm_calls`, `jobs` (failed/old) | 180 days detail, aggregated forever; `done` job rows of live documents are kept |
| `answer_traces` | 365 days unless `pinned` |
| `audit_events`, `rules`, `pipeline_config` | forever |

Nightly batched deletes with an index on the timestamp column; no partitioning.

## 7. Creation schedule

Tables are created when the code that writes them is being built, not before (file 10): registry, `jobs` and `pipeline_config` (with `v_config_current`; the scopes and gate keys are read in M1) in M1; the document tables and the entity/fact tables were brought forward to the point where S2 started enrichment (2026-10-21), since that code writes them; `documents`, `document_sources`, `document_relations`, `document_nodes`, `assets`, `review_flags`, `rules`, `audit_events`, `pipeline_config`, `telemetry_*`, `llm_calls` in M2–M3; `entities`, `entity_aliases`, `entity_mentions`, `numeric_facts` in M4; `answer_traces` in M8; benchmark tables in M10. Creating empty tables early only guarantees they have the wrong shape when the code arrives.
