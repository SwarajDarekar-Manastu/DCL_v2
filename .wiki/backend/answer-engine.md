# Answer Engine (workflow, tools, playbooks, sanitizer, verifier, DBOS)

| Field | Value |
|-------|-------|
| Feature id | `backend/answer-engine` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/07_phase3_answer_engine.md (all) |
| Last updated | 2026-10-21 |

## Purpose

LlamaIndex Workflow under DBOS: query analysis, planner, tools T1–T6 and U1–U2 with template SQL, playbooks, IP sanitizer, synthesis contract with provenance labels, claim verifier, SSE API, extractive fallback.

## Location

Code:
- `backend/llm_engine/engine/workflow.py`
- `backend/llm_engine/engine/tools/`
- `backend/llm_engine/engine/sanitizer.py`
- `backend/llm_engine/engine/verifier.py`
- `backend/api/engine.py`
- `frontend/openwebui/skills/`

Tests and fixtures:
- `backend/tests/integration/llm_engine/engine/`
- `backend/tests/benchmark/suites/`

## Interfaces

Provides:
- /v1/answer SSE
- `/v1/traces/{id}`
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
- `backend/tests/benchmark/suites/`

## Rubric (what "done" means for this feature)

- [ ] Golden suite: telemetry exactness 100%, citation recall ≥0.85, faithfulness ≥0.95
- [ ] Every numeric claim string-matches a tool result
- [ ] External queries pass the sanitizer and are logged in the trace
- [ ] Engine restart mid-answer resumes the run
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
