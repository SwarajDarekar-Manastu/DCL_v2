# Gemini gateway client and capability probe

| Field | Value |
|-------|-------|
| Feature id | `platform/gemini-gateway-client` |
| Status | in-progress |
| Owner session | S4 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §5.4, §7, §7.1; 05 §4.6; 09 §H.1, §H.3 |
| Last updated | 2026-10-21 |

## Purpose

The only module that talks to the Manastu Cloud Run gateway: structured output, function calling, thinking level, image/PDF parts, streaming, retry/backoff, budget guard, llm_calls hook, capability flags from a probe.

## Location

Code:
- `backend/llm_engine/gemini_client.py` (request builder, parser, retry, client)
- `backend/llm_engine/gemini_types.py` (capability flags, parts, messages, results, records, budget, errors)
- `backend/llm_engine/gemini_probe.py`
- `backend/llm_engine/gemini_capabilities.json` (written by the probe; committed; all `unknown` until the first real probe)

Tests and fixtures:
- `backend/tests/unit/llm_engine/gemini/test_gemini_client.py`
- `backend/tests/unit/llm_engine/gemini/test_gemini_probe.py`
- `backend/tests/unit/llm_engine/gemini/responses/` (hand-written OpenAI-compatible fixtures; replace with real recordings once the gateway is reachable)
- `backend/tests/unit/llm_engine/test_gateway_isolation.py` (no Google SDK import, no gateway URL/key outside the three allowed files)

## Interfaces

Provides:
- `GeminiClient(settings=None, *, capabilities=None, ledger=None, budget=None, prices=None, …)`; refuses to start with `GOOGLE_API_KEY` set or the Gemini group incomplete
- `await client.generate(model=, messages=, context=CallContext(purpose=…), schema=None, tools=, tool_choice=, thinking=, include_thoughts=, media_resolution=, temperature=, max_output_tokens=, cached_content=)` → `GenerateResult(text, parsed, tool_calls, usage, model, finish_reason, request_id, latency_ms, thoughts)`; `generate_sync(...)` for Celery prefork workers
- `client.stream(...)` → `TextDelta`… then one `StreamDone(result)`
- Types import from `backend.llm_engine.gemini_types`, the client from `backend.llm_engine.gemini_client`
- `Message.system/user/assistant/tool_result`, parts `Text`, `Image(bytes, mime)`, `Pdf(bytes, filename)`, `ToolSpec`, `ToolCall`
- Capability flags `Capability.*`, `Capabilities.load()`; disabled → fallback (structured output: schema in prompt + local validation; streaming: one chunk; thinking, thoughts, media resolution, cache: omitted) or `CapabilityUnavailable` (tools, image, PDF)
- Errors: `GatewayError(status_code, retryable)`, `BudgetExhausted` (retry later so queues wait), `StructuredOutputError(raw_text)`, `CapabilityUnavailable`
- `DailyTokenBudget(limit_tokens, usage_today=None)`; `LlmCallRecord` per call for the `llm_calls` ledger (status `ok` | `error`)
- Probe CLI: `uv run python -m backend.llm_engine.gemini_probe [--write]` prints the file 09 §H.1 table

Consumes:
- `platform/env-contract` (`Group.GEMINI`)
- later: `llm_calls` table (S1) for the ledger and the budget's `usage_today`; `pipeline_config` `cloud.daily_token_budget`, `models.*`, prices

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/gemini_client.py`
- `backend/llm_engine/gemini_types.py`
- `backend/llm_engine/gemini_probe.py`
- `backend/llm_engine/gemini_capabilities.json`
- `backend/tests/unit/llm_engine/gemini/`
- `backend/tests/unit/llm_engine/test_gateway_isolation.py`

## Rubric (what "done" means for this feature)

- [ ] Probe result recorded in docs/architecture/09 §H.1 (blocked: `GEMINI_BACKEND`, `GEMINI_GATEWAY_URL` not in `.env`)
- [x] Budget cap stops new calls and queues wait (test: no request once the cap is reached; `BudgetExhausted` for Celery retry)
- [x] No other module imports a Google SDK or the gateway URL (test)
- [ ] A Gemini structured call through the gateway is logged with tokens (M0 acceptance; needs the gateway and the `llm_calls` table)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S4 | Types, flags and errors moved to `gemini_types.py` (no behavior change); client under 600 lines |
| 2026-10-21 | S4 | Client and probe against the OpenAI-compatible shape; every capability behind a flag; retry with Retry-After; budget guard; ledger hook; 45 tests on fixture responses; real probe blocked on missing gateway env names |

## Related

- `platform/env-contract`
- `backend/vision-service`, `backend/enrichment`, `backend/answer-engine` (S2 consumers)
- `.wiki/index.md`
