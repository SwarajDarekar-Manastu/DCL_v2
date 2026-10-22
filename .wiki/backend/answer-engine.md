# Answer Engine (workflow, tools, playbooks, sanitizer, verifier, DBOS)

| Field | Value |
|-------|-------|
| Feature id | `backend/answer-engine` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/07_phase3_answer_engine.md (all) |
| Last updated | 2026-10-22 |

## Purpose

LlamaIndex Workflow under DBOS: query analysis, planner, tools T1–T6 and U1–U2 with template SQL, playbooks, IP sanitizer, synthesis contract with provenance labels, claim verifier, SSE API, extractive fallback.

## Location

Code:
- `backend/llm_engine/engine/analysis.py` (step 1: `QueryAnalysis`, `analyze`, `resolve`: entities via aliases, test ids via the dispatcher's patterns, unit-checked bounds, web policy)
- `backend/llm_engine/engine/synthesis.py` (steps 5–6: numbered evidence, `SynthesisOutput` with claims citing evidence ids, numeric string check, entailment verdicts, one repair pass, removal of what still fails)
- `backend/llm_engine/prompts/engine/` (`query_analysis.v1`, `synthesis.v1`, `verify.v1`, `physics_args.v1`, `chitchat.v2`, `external_intent.v1`, `external_search.v1`, `telemetry_args.v1`); `backend/llm_engine/prompts/vision/relook.v1.md` (T3 relook)
- `backend/llm_engine/engine/playbooks.py` (step 2: `build_plan(question, analysis) -> Plan{calls, caveats, needs_physics_args, read_top_document}`; one playbook per intent; telemetry metric and run comparison plan T2 (arguments from `telemetry_args.v1`) plus a tables-only report search to cross-check; a failure investigation with a test plan also runs T2; visual lookup and failure investigation plan T3)
- `backend/llm_engine/engine/workflow.py` (`AnswerWorkflow`: analysis → plan → tools in parallel → insufficient-evidence check → synthesis + verification → frames and trace; chit-chat, clarification, extractive fallback on `GeminiError`; `EngineDeps`; `build_runtime` for DBOS; `ordered` restores frame order)
- `backend/llm_engine/engine/tools/` (`__init__.py`: `ToolResult`, `Source`, `Provenance`, `provenance_of`, `tool_spec`; `search.py` T1; `documents.py` U1, U2; `code_diagrams.py` T4; `physics.py` T5; `external.py` T6; `visuals.py` T3; `telemetry.py` T2)
- `backend/llm_engine/engine/sanitizer.py`
- `backend/llm_engine/engine/verifier.py` (numeric check; LLM entailment with M8)
- `backend/api/engine.py`
- `frontend/openwebui/skills/` (13 playbook `SKILL.md` files with front matter `name, description, intents, tools`; `publish_skills.py` publishes them through Open WebUI's `/api/v1/skills`)

Tests and fixtures:
- `backend/tests/integration/llm_engine/engine/`
- `backend/tests/unit/llm_engine/engine/`
- `backend/tests/integration/llm_engine/engine/` (DCL_TEST_DATABASE_URL: tools on rows, `test_workflow_dbos.py` under DBOSRuntime, `test_workflow_restart.py` + `_restart_worker.py` kill-and-resume in subprocesses)
- `backend/tests/benchmark/suites/`

## Interfaces

Provides:
- `POST /v1/answer` (SSE): request `AnswerRequest`; events `step`, `token`, `citation`, `embed`, `needs_confirmation`, `done`, `error` (models and `to_sse` in `backend/api/engine.py`; example stream in `backend/tests/unit/llm_engine/engine/example_answer_stream.sse`); streams the workflow; 503 when the engine is not configured or not installed; a failure ends the stream with `error` (`gemini_unavailable` retryable, else `internal`)
- `POST /v1/answer/{trace_id}/confirm` (`ConfirmationReply`), `GET /v1/traces/{trace_id}` and `GET /v1/traces?chat_id=&message_id=` (`TraceView`, 404 when none), `POST /v1/traces/{trace_id}/feedback` (`FeedbackRequest {kind, comment, citation_id}` → 202); 501 until M8; `needs_confirmation` carries `trace_id`
- Identity: headers `X-DCL-User-Id`, `X-DCL-User-Email`, `X-DCL-User-Groups`, `X-DCL-Timestamp`, `X-DCL-Signature` = hex HMAC-SHA256(`DCL_PIPE_SHARED_SECRET`, "ts\nuser_id\nemail\ngroups\nsha256(body)"), skew ≤ 300 s (`sign_identity`)
- `sanitize_query(query, proprietary_terms, organization_names, people, folder_names, public_terms) -> SanitizedQuery(text, original_sha256, removed)`; raises `SanitizerRefused` when fewer than two content words remain (`engine/sanitizer.py`)
- `check_numeric_claims(claims, tool_outputs) -> list[NumericMismatch]`: value and unit strings of a claim must appear in a tool result (`engine/verifier.py`)
- Tools (each `(session?, args) -> ToolResult{tool, call_id, result, provenance[Source], warnings, display}`; `display` is what synthesis quotes and the numeric verifier checks): `search_documents` (T1: alias expansion from `entity_aliases`, widening doc_kinds → test plan → parent scope), `get_document` (U1: ordered parents, page range, section, 40k-char budget with `start_ordinal`), `catalog_lookup` (U2: documents, halted with case keys, standards with revisions), `inspect_code_and_diagrams` (T4: qualname lookup, callers/callees, diagram neighbors/upstream/downstream/path over `documents.catalog {nodes[{id,tag,label,type}], edges[{source,target,medium,label,directed}]}`), `physics_calculator` (T5: unit_convert, mass_flow_from_thrust, isentropic_sizing, cea_performance with `config/propellants.yaml`, scale_thruster), `external_search` (T6, below), `inspect_visuals` (T3, below), `query_telemetry` (T2, below)
- Engine lifecycle for `backend/main.py`: `start_engine()` (idempotent; builds Gemini, models and session clients and launches DBOS in the DCL database, schema `dbos`) and `stop_engine()`; the endpoint starts it on first use if the lifespan did not
- Durability: a run is a DBOS workflow; after a crash the next `start_engine()` recovers pending runs. Completed steps are replayed from the journal; the step that was running is executed again, so tools must tolerate a rerun (they are read-only). The client's SSE connection does not survive; the finished run's trace is saved and readable by trace id
- Frames: `Emit{seq, payload}` stream events; under DBOS each stream write is its own task, so frames can arrive out of order and consumers read them through `ordered(handler.stream_events())`
- Trace record handed to `EngineDeps.save_trace`: `trace_id, query_analysis, tool_calls, retrieved, claims, citations, verifier_result, answer_markdown, mode, latency_ms` (logged until S1's `answer_traces` table exists)
- T6 `external_search(client, ExternalSearchArgs{purpose, query_intent}, policy=ExternalPolicy, trace_id)` (async): `external_intent.v1` writes ≤ 3 generic needs from the user's question alone; each passes `sanitize_query` (`answer.proprietary_terms`); a refused need is never sent. Gemini with Google Search grounding in an isolated call (the fixed one-line instruction plus the sanitized query; no history, no evidence); `literature` also queries the arXiv API (all words, then any word by relevance). Sources are `web` / `literature` with URLs (grounding redirect links resolved to the page). Each query is recorded as `external_queries` in the trace: purpose, sanitized text, SHA-256 of the original, provider, result count, Google's own queries, refusal or error
- External policy (file 07 §6): `pipeline_config` `answer.external_search_enabled` (kill switch, default on), `answer.external_allowed_groups` (default none: nobody), `answer.proprietary_terms`; the planner goes external on an explicit request, or for a design synthesis only when internal and library search found nothing; never with scope `internal_only`; a user outside the groups gets a caveat. Benchmark `options.benchmark.external_search = mock` returns canned results without network
- T2 `query_telemetry(session, QueryTelemetryArgs{run_ids, test_plan_id, test_run_ids, channels, metrics, window_kind, window, at_t_from_ignition_ms, compare_runs, plot}, connect)`: runs from `telemetry_runs` ⋈ `documents` (visible statuses, ≤ 12); a requested HALTED run → warning with its open HARD case keys, no numbers; semantic channels (`chamber_pressure`, `thrust`, `bed_temperature`, `mass_flow`, `heater_power`) → `canonical_name`s by quantity + role glob (`*chamber*`, `*bed*`/`*cat*`, …); one `UNION ALL` DuckDB statement from a template over `normalized.parquet` (catalog column names only, quoted; values bound). Metrics `peak_raw`, `peak_50ms` (Route C's centred moving mean, exact), `steady_mean` (stored window for a whole-run query, else the window mean), `max`, `min`, `mean`, `p99`, `duration`, `time_to_peak`, `value_at_t`, `window_stats`; windows `run`, `steady`, `valve_open` (longest pulse of the `valve_state` channel; S5's golden method), `custom` (on `t_from_ignition_ms`). `display` gives each number once with unit (barg / bara, K with °C), window, t0_method, rate, samples, Parquet URI; warnings for saturation and gauge pressure with unknown ambient. `plot=true` renders one PNG per run (Matplotlib Agg `Figure`, no pyplot; ≤ 4 channel panels over time from ignition, window shaded, peak marked, ≤ 4000 points), writes it to `dcl-assets` at `plots/{run_uuid}/{sha16 of channels+window}.png` through `put_asset` (same question overwrites), and returns `result.plots[{run_label, asset_uri, url (presigned 15 min), alt}]`; the workflow streams each as an `embed` frame `kind=plot` with `url`; without the asset store the plot is skipped with a warning. `start_engine` passes a DuckDB factory with httpfs and a MinIO secret (`telemetry_connect`); without MinIO, T2 says the store is not configured
- T3 `inspect_visuals(session, InspectVisualsArgs{query, kinds, test_plan_ids, failure_modes, components, k, similar_to_asset_id, relook_question, user_language}, embed_query, rerank, presign)`: T1 hybrid search restricted to the node types of the kinds (`hardware_photo` → photo + figure, `plot_figure` → figure, `video_frame` → video_event, `diagram` → diagram_summary + figure; none = all), failure modes and components join the query text (T1 has no entity filter); with `similar_to_asset_id`, RRF with an image-embedding kNN from that asset's node, the reference excluded. Result `visuals[]`: doc_id, title, anchor, node_type, reading, breadcrumb, page_no, asset_uri, `url_web`/`url_thumb` (presigned 15 min; thumb from the `photo_thumb` asset of the same blob, else the web image), similarity; no node ids. `relook(client, result, question, fetch)` (async): top ≤ 4 images + captions to Gemini (`relook.v1`, main model, high media resolution); returns `result.relook {source: "relook", answer, images[{image, observation, visible}], images_sent, persisted: false}` and an evidence line marked as an answer-time observation; nothing is written. The workflow runs relook when the call has `relook_question` (visual lookup) and `EngineDeps.fetch_asset` exists; a relook `GeminiError` becomes a warning. `start_engine` wires `presign`/`fetch_asset` from MinIO settings; without MinIO, T3 returns readings without links
- `photo_strips(results)` (workflow): one `embed` frame `kind=photo_strip` per T3 result with links (≤ 6 thumbnails, escaped self-contained HTML, links to the web image), emitted before the answer tokens
- `Provenance` (measured, internal_report, standard, vendor_claim, literature, calculation, web) is the one enum, also used by the SSE citation event
- Skills: `dcl-<folder>` in Open WebUI, one per §5 row (chit-chat excluded), active, public read; not attached to the engine model (DECISIONS 2026-10-23, option a). Front matter `dcl-playbook: <intent>` (also the tag `dcl-playbook:<intent>`); `AnswerOptions.playbook_hint` (an `Intent` or null) carries the intent of a $-mentioned skill (S3's Pipe forwards `chat_context.mentioned_skill_ids` in M9) and `playbooks.apply_hint` adds it to the analysed intents (a chit-chat reading gives way to the playbook). The `tools` front matter equals the planner's tools for the skill's intents (`test_skills.py`)

Consumes:
- retrieval
- gateway client
- telemetry catalog
- DBOS runtime (platform)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/engine/workflow.py`
- `backend/llm_engine/engine/playbooks.py`
- `backend/llm_engine/engine/analysis.py`
- `backend/llm_engine/engine/synthesis.py`
- `backend/llm_engine/prompts/engine/`
- `backend/llm_engine/engine/tools/`
- `backend/llm_engine/engine/sanitizer.py`
- `backend/llm_engine/engine/verifier.py`
- `backend/api/engine.py`
- `frontend/openwebui/skills/`
- `backend/tests/integration/llm_engine/engine/`
- `backend/tests/unit/llm_engine/engine/`
- `backend/tests/benchmark/suites/`

## Rubric (what "done" means for this feature)

- [x] SSE contract published: signed identity refused when tampered; example stream validates (`test_engine_api.py`)
- [ ] Golden suite: telemetry exactness 100%, citation recall ≥0.85, faithfulness ≥0.95
- [x] Every numeric claim string-matches a tool result (verifier wired into the workflow; `test_workflow.py` checks the streamed answer against the tool output)
- [x] Fact question streams steps, tokens, citations and done; chit-chat without tools; clarification mode; insufficient-evidence template; extractive fallback on Gemini outage (`test_workflow.py`, 6 tests)
- [x] Workflow runs under DBOSRuntime against PostgreSQL with frame order restored (`test_workflow_dbos.py`)
- [x] External queries pass the sanitizer and are logged in the trace (`test_external.py`: the captured grounded request holds no internal identifier, history or evidence; refused needs are never sent; `external_queries` in the trace; live check 2026-10-22: grounding returned 6 sources, redirects resolved)
- [x] Engine restart mid-answer resumes the run (`test_workflow_restart.py`: the worker process dies inside the tool step; a new process recovers the run by id; query analysis is replayed from the journal, not asked again; the tool reruns; the trace is saved by the new process)
- [x] Skills: 13 playbooks; a test builds the plan per skill and fails on drift (checked by breaking one); publish creates, then updates, activates, grants public read, dry run writes nothing (`test_skills.py`); live 2026-10-23 on a disposable Open WebUI v0.12.3: 13 created, second run 13 updates, read back with the `*` read grant
- [x] T2: metrics reproduce Route C's stored three-tier values and numpy on the same Parquet (whole run, valve-open window, user window, value_at_t, comparison); halted run reported with its case key; missing quantity, saturation and unknown-ambient warnings (`test_telemetry_db.py`, 5 tests); planner and workflow run T2 with extracted arguments (`test_playbooks.py`, `test_workflow.py`); plot PNG, deterministic key, presigned link and `plot` embed (`test_telemetry_db.py`, `test_workflow.py`); live 2026-10-22: DuckDB over `s3://dcl-telemetry/…` on the stack's one committed run, plot rendered
- [x] T3: kinds restrict node types, test plan filter applies, halted documents never appear; `similar_to_asset_id` ranks by image embedding and skips the reference; results carry presigned URLs and the document, no node ids (`test_visuals_db.py`, 3 tests); relook sends ≤ 4 images, returns `persisted: false`, writes nothing (`test_visuals.py`; live check 2026-10-22: two synthetic mesh images, the model told the holed one from the intact one); visual lookup and failure investigation plan T3 and stream a `photo_strip` that validates against `EmbedEvent` (`test_playbooks.py`, `test_workflow.py`)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-23 | S2 | `chitchat.v2`: small talk stays `chitchat`, an out-of-scope question is refused in mode `insufficient_evidence`; a tool warning "halted for review" becomes a caveat and a `> Note:` line in the answer; 2 tests |
| 2026-10-23 | S2 | `engine_deps(settings)` shared with the benchmark runner; trace `tool_calls[].display` (≤ 4000 chars); T2 pressure units `barg`/`bara` (pint-parsable; "bar g" read as bar·gram) |
| 2026-10-23 | S2 | Playbook hint: `AnswerOptions.playbook_hint`, `apply_hint`, `dcl-playbook` front matter and tag; 13 + 2 tests |
| 2026-10-23 | S2 | Open WebUI Skills: 13 playbook SKILL.md files, `publish_skills.py`, drift test against the planner; 16 tests |
| 2026-10-22 | S2 | T2 plot embed: Matplotlib PNG to `dcl-assets/plots/…`, presigned `plot` embed frame; 1 DB + 1 unit test |
| 2026-10-22 | S2 | T2 `query_telemetry` over `telemetry_runs`/`telemetry_channels` (DuckDB templates, Route C-exact peaks, valve-open and user windows, halted runs with case keys); `telemetry_args.v1`; planner and workflow; 5 DB + 2 workflow + 1 planner tests |
| 2026-10-22 | S2 | T3 `inspect_visuals` (kinds → node types, image kNN by reference asset, presigned links) and relook (answer-time, not persisted); planner and `photo_strip` embed; 3 DB + 4 unit + 1 workflow + 1 planner tests |
| 2026-10-22 | S2 | T6 `external_search` (grounding + arXiv) under the §6 policy; planner and workflow wiring; benchmark mock; 11 unit + 6 workflow + 2 API/planner tests |
| 2026-10-22 | S2 | Restart-resume test: killed engine resumes the answer in a new process (completed steps replayed, interrupted step rerun) |
| 2026-10-22 | S2 | Workflow increment: playbooks, `AnswerWorkflow` (DBOS), `/v1/answer` streaming, frame ordering; 6 workflow + 4 planner + 4 API tests, 1 DBOS test |
| 2026-10-22 | S2 | Query analysis, synthesis contract and verifier (numeric + entailment, repair pass); 8 tests |
| 2026-10-22 | S2 | Tools increment 1: T1, U1, U2, T4, T5 with `ToolResult`/`Source`; 10 unit + 7 DB tests |
| 2026-10-22 | S2 | `trace_id` on `needs_confirmation`; trace lookup by chat/message and feedback routes for S3's Actions |
| 2026-10-21 | S2 | IP sanitizer (leak fixture, refusal rule) and deterministic numeric claim check; 24 tests |
| 2026-10-21 | S2 | `/v1/answer` SSE event schema, identity signature, trace view, example stream (publish-first #4); endpoints 501 until M8 |

## Related

- `.wiki/index.md`
