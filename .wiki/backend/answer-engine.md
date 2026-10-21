# Answer Engine (workflow, tools, playbooks, sanitizer, verifier, DBOS)

| Field | Value |
|-------|-------|
| Feature id | `backend/answer-engine` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/07_phase3_answer_engine.md (all) |
| Last updated | 2026-10-21 |

## Purpose

LlamaIndex Workflow under DBOS: query analysis, planner, tools T1–T6 and U1–U2 with template SQL, playbooks, IP sanitizer, synthesis contract with provenance labels, claim verifier, SSE API, extractive fallback.

## Location

Code:
- `backend/llm_engine/engine/workflow.py`
- `backend/llm_engine/engine/tools/` (`__init__.py`: `ToolResult`, `Source`, `Provenance`, `provenance_of`, `tool_spec`; `search.py` T1; `documents.py` U1, U2; `code_diagrams.py` T4; `physics.py` T5)
- `backend/llm_engine/engine/sanitizer.py`
- `backend/llm_engine/engine/verifier.py` (numeric check; LLM entailment with M8)
- `backend/api/engine.py`
- `frontend/openwebui/skills/`

Tests and fixtures:
- `backend/tests/integration/llm_engine/engine/`
- `backend/tests/unit/llm_engine/engine/`
- `backend/tests/integration/llm_engine/engine/` (DCL_TEST_DATABASE_URL) (API contract tests)
- `backend/tests/benchmark/suites/`

## Interfaces

Provides:
- `POST /v1/answer` (SSE): request `AnswerRequest`; events `step`, `token`, `citation`, `embed`, `needs_confirmation`, `done`, `error` (models and `to_sse` in `backend/api/engine.py`; example stream in `backend/tests/unit/llm_engine/engine/example_answer_stream.sse`); 501 until M8
- `POST /v1/answer/{trace_id}/confirm` (`ConfirmationReply`), `GET /v1/traces/{trace_id}` and `GET /v1/traces?chat_id=&message_id=` (`TraceView`, 404 when none), `POST /v1/traces/{trace_id}/feedback` (`FeedbackRequest {kind, comment, citation_id}` → 202); 501 until M8; `needs_confirmation` carries `trace_id`
- Identity: headers `X-DCL-User-Id`, `X-DCL-User-Email`, `X-DCL-User-Groups`, `X-DCL-Timestamp`, `X-DCL-Signature` = hex HMAC-SHA256(`DCL_PIPE_SHARED_SECRET`, "ts\nuser_id\nemail\ngroups\nsha256(body)"), skew ≤ 300 s (`sign_identity`)
- `sanitize_query(query, proprietary_terms, organization_names, people, folder_names, public_terms) -> SanitizedQuery(text, original_sha256, removed)`; raises `SanitizerRefused` when fewer than two content words remain (`engine/sanitizer.py`)
- `check_numeric_claims(claims, tool_outputs) -> list[NumericMismatch]`: value and unit strings of a claim must appear in a tool result (`engine/verifier.py`)
- Tools (each `(session?, args) -> ToolResult{tool, call_id, result, provenance[Source], warnings, display}`; `display` is what synthesis quotes and the numeric verifier checks): `search_documents` (T1: alias expansion from `entity_aliases`, widening doc_kinds → test plan → parent scope), `get_document` (U1: ordered parents, page range, section, 40k-char budget with `start_ordinal`), `catalog_lookup` (U2: documents, halted with case keys, standards with revisions), `inspect_code_and_diagrams` (T4: qualname lookup, callers/callees, diagram neighbors/upstream/downstream/path over `documents.catalog {nodes[{id,tag,label,type}], edges[{source,target,medium,label,directed}]}`), `physics_calculator` (T5: unit_convert, mass_flow_from_thrust, isentropic_sizing, cea_performance with `config/propellants.yaml`, scale_thruster); planned: T2 telemetry (Route C tables), T3 visuals, T6 external
- `Provenance` (measured, internal_report, standard, vendor_claim, literature, calculation, web) is the one enum, also used by the SSE citation event
- Skills markdown

Consumes:
- retrieval
- gateway client
- telemetry catalog
- DBOS runtime (platform)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/engine/workflow.py`
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
- [ ] Every numeric claim string-matches a tool result (check built and tested; wired into the workflow in M8)
- [ ] External queries pass the sanitizer and are logged in the trace (sanitizer built and tested on a leak fixture; trace logging with M8)
- [ ] Engine restart mid-answer resumes the run
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | Tools increment 1: T1, U1, U2, T4, T5 with `ToolResult`/`Source`; 10 unit + 7 DB tests |
| 2026-10-22 | S2 | `trace_id` on `needs_confirmation`; trace lookup by chat/message and feedback routes for S3's Actions |
| 2026-10-21 | S2 | IP sanitizer (leak fixture, refusal rule) and deterministic numeric claim check; 24 tests |
| 2026-10-21 | S2 | `/v1/answer` SSE event schema, identity signature, trace view, example stream (publish-first #4); endpoints 501 until M8 |

## Related

- `.wiki/index.md`
