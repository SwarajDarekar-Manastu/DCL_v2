# Gemini gateway client and capability probe

| Field | Value |
|-------|-------|
| Feature id | `platform/gemini-gateway-client` |
| Status | in-progress |
| Owner session | S4 |
| Spec | docs/architecture/01 §5.4, §7, §7.1; 05 §4.6; 09 §H.1 (verified gateway contract), §H.3 |
| Last updated | 2026-10-22 |

## Purpose

The only module that talks to the Manastu Cloud Run gateway. Adapters own the wire format; the client owns transport, resilience and accounting; the probe confirms which capabilities the gateway passes through.

## Location

Code:
- `backend/llm_engine/gemini_client.py` (transport, retries, breaker, limits, budget, ledger, streaming)
- `backend/llm_engine/gemini_adapters.py` (`ManastuGatewayAdapter` default, `GeminiNativeAdapter`, `OpenAICompatAdapter`)
- `backend/llm_engine/gemini_types.py` (flags, parts, messages, results, records, budget, errors)
- `backend/llm_engine/gemini_probe.py`
- `backend/llm_engine/gemini_capabilities.json` (written by a real probe run on 2026-10-22)

Tests and fixtures:
- `backend/tests/unit/llm_engine/gemini/test_manastu_adapter.py` (recorded from the real gateway; ids and signatures redacted)
- `backend/tests/unit/llm_engine/gemini/responses/manastu/` (recordings)
- `backend/tests/unit/llm_engine/gemini/test_gemini_client.py` + `responses/*.json|sse` (OpenAI shape, client behavior)
- `backend/tests/unit/llm_engine/gemini/test_gemini_probe.py`
- `backend/tests/unit/llm_engine/test_gateway_isolation.py`

## Interfaces

Provides:
- `GeminiClient(settings=None, *, capabilities, ledger, budget, prices, timeout, stream_idle_s=60, max_attempts=5, max_concurrency_per_model=8, breaker, …)`
- `await generate(...)`, `generate_sync(...)`, `async for ev in stream(...)`; options: `tools`, `tool_choice`, `thinking`, `include_thoughts`, `media_resolution`, `temperature`, `max_output_tokens`, `cached_content`, `safety_settings` (default none sent)
- Types from `backend.llm_engine.gemini_types`: `Message` (`tool_result(id, content, name=)`), `Text`, `Image`/`Pdf` (per-part `media_resolution`), `ToolSpec`, `ToolCall` (`thought_signature`), `GenerateResult` (`quota`), `Usage` (`estimated`), `LlmCallRecord` (`usage_estimated`)
- Safety: `SafetySetting(HarmCategory, HarmBlockThreshold)`, `EXTRACTION_SAFETY` = DANGEROUS_CONTENT at BLOCK_ONLY_HIGH for extraction capabilities (S2 turns it on per capability from config); BLOCK_NONE/OFF not representable; manastu sends `config.safety_settings`, native top-level `safetySettings`, openai style refuses
- Errors: `GatewayError(status_code, retryable)`, `GatewayUnavailable` (breaker open), `BudgetExhausted` (budget or gateway quota), `RequestTooLarge`, `StructuredOutputError`, `CapabilityUnavailable`
- `GEMINI_API_STYLE`: `manastu` (default) | `gemini` | `openai`
- Probe: `uv run python -m backend.llm_engine.gemini_probe [--write]`

Consumes:
- `platform/env-contract` (`Group.GEMINI`); later `llm_calls` (S1) for the ledger and the budget's `usage_today`

## Production checklist (audit of 2026-10-22: Google Gemini API docs + client resilience)

| # | Item | Where | State |
|---|------|-------|-------|
| 1 | Retry only transient failures: 408, 429, 500, 503, 504; never 400/401/403/404 | `adapters.retryable` | done, tested |
| 2 | Upstream code inside the gateway's 502 decides (`ClientError: 400 …` no retry, `ServerError: 503 …` retry) | `ManastuGatewayAdapter.retryable` | done, tested against a recording |
| 3 | Backoff ~1 s doubling to 60 s with jitter; honor `Retry-After` (seconds or HTTP date, capped 300 s); max 5 attempts | `backoff_delay` | done, tested |
| 4 | Circuit breaker: 5 consecutive retryable failures open it for 30 s, then one trial call | `CircuitBreaker` | done, tested |
| 5 | Bounded concurrency per model (default 8, sync and async) | `_ModelLimits` | done |
| 6 | Idempotency key per call, stable across retries; recorded as request id when the gateway sends none | `Idempotency-Key` header | done, tested |
| 7 | Timeouts: connect 10 s, read 180 s, write 60 s, stream idle 60 s | client | done |
| 8 | Inline media size guard (20 MB, file 09 §H.1 item 5) before sending | `RequestTooLarge` | done, tested |
| 9 | Thought signatures echoed on function-call parts (Gemini 3) | adapters | done, verified live |
| 10 | Function responses carry the function name | `Message.tool_result(name=)` | done, verified live |
| 11 | `temperature` not sent to Gemini 3.6+ / 4 (ignored now, rejected later per Google) | `drops_temperature` | done, tested |
| 12 | Thinking level per model: 3.8 Flash accepts low/medium/high, not minimal (live 400) | caller choice | documented; the error is non-retryable |
| 13 | Usage from `usage_metadata`; stream gives a total only, so the split is estimated and marked | `estimate_usage` | done, tested |
| 14 | Gateway `quota.remaining` ≤ 0 stops new calls (BudgetExhausted) in addition to the daily token budget | client | done, tested |
| 15 | Media resolution per part (images high, PDF pages medium per Google; low = about 1/4 of the tokens) | adapters | done, verified live |
| 16 | Implicit caching: put large shared content first, ≥ 4,096 tokens on 3.8 Flash; no flag needed | caller guidance | documented |
| 17 | Single-page documents: text prompt after the page (Google) | caller guidance | documented |
| 18 | No secrets in logs, errors or records; key sent only as `X-API-Key`; `.env` parsed with dotenv | client, config | done, tested |
| 19 | Blocked responses (no candidates) raise with the block reason; finish reasons are returned | adapters | done |
| 20 | High thinking is expensive (one primality question used ~21k thinking tokens) | caller guidance | documented |
| 21 | Batch API | — | not exposed by the gateway (probe: endpoint missing); flag off |
| 22 | Explicit context caches (`POST /caches`) | — | endpoint present, not exercised; flag off until first use |
| 24 | Safety settings pass-through, default off; filters can be relaxed for extraction, never switched off | `safety_settings=` | done, tested, verified live 2026-10-22 |
| 23 | Google Search grounding: the model writes the Google queries from the whole prompt, so send only an already-sanitized query in a grounded call; queries and sources come back in `result.grounding` for the trace; source URIs are Vertex AI Search redirect links | `google_search=True` | done, verified live |

## Workspace (files to touch when modifying this feature)

- `backend/llm_engine/gemini_client.py`
- `backend/llm_engine/gemini_adapters.py`
- `backend/llm_engine/gemini_types.py`
- `backend/llm_engine/gemini_probe.py`
- `backend/llm_engine/gemini_capabilities.json`
- `backend/tests/unit/llm_engine/gemini/`
- `backend/tests/unit/llm_engine/test_gateway_isolation.py`

## Rubric (what "done" means for this feature)

- [x] Probe result recorded (real run 2026-10-22: style manastu detected; structured output, tools, thinking, thoughts, image, PDF, media resolution, streaming supported; stream usage total only; caches not exercised; batch missing). The Lead records it in docs/architecture/09 §H.1
- [x] Budget cap and gateway quota stop new calls (tests)
- [x] No other module imports a Google SDK or the gateway URL (test)
- [ ] A Gemini structured call through the gateway is logged with tokens in `llm_calls` (needs S1's table; the ledger record exists)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S4 | Client and probe against the OpenAI-compatible shape; every capability behind a flag |
| 2026-10-21 | S4 | Types, flags and errors moved to `gemini_types.py` |
| 2026-10-22 | S4 | Optional `safety_settings` pass-through (`EXTRACTION_SAFETY`), default off; live gateway call accepted |
| 2026-10-22 | S4 | Google Search grounding behind `Capability.GOOGLE_SEARCH` (`google_search=True`, `result.grounding`); probe re-run with the real `.env` |
| 2026-10-22 | S4 | Provider adapters (Manastu default, native, OpenAI); production checklist implemented; tests on recordings from the real gateway; probe with discovery and style detection; capabilities file from a real run |

## Related

- `platform/env-contract`
- `backend/vision-service`, `backend/enrichment`, `backend/answer-engine` (S2 consumers)
- `.wiki/index.md`
