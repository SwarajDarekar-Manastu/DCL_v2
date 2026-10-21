# Gemini gateway client and capability probe

| Field | Value |
|-------|-------|
| Feature id | `platform/gemini-gateway-client` |
| Status | planned |
| Owner session | S4 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §7, §7.1; 09 §H.1 |
| Last updated | 2026-10-21 |

## Purpose

The only module that talks to the Manastu Cloud Run gateway: structured output, function calling, thinking level, image/PDF parts, streaming, retry/backoff, budget guard, llm_calls hook, capability flags from a probe.

## Location

Code:
- `backend/llm_engine/gemini_client.py`
- `backend/llm_engine/gemini_probe.py`

Tests and fixtures:
- backend/tests/unit/llm_engine/gemini/ (recorded responses)

## Interfaces

Provides:
- GeminiClient
- capability flags

Consumes:
- env contract

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/gemini_client.py`
- `backend/llm_engine/gemini_probe.py`
- backend/tests/unit/llm_engine/gemini/ (recorded responses)

## Rubric (what "done" means for this feature)

- [ ] Probe result recorded in docs/architecture/09 §H.1
- [ ] Budget cap stops new calls and queues wait
- [ ] No other module imports a Google SDK or the gateway URL
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
