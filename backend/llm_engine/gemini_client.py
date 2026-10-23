"""The only module that talks to the Manastu Gemini gateway (docs/architecture/01 §7, §7.1; 09 §H.1).

The wire format comes from an adapter chosen by GEMINI_API_STYLE (gemini_adapters.py); this module owns
transport and production behavior: retries with jittered backoff and Retry-After, upstream-error
classification, a circuit breaker, bounded concurrency per model, an idempotency key per call, timeouts,
an inline-size guard, the daily budget and gateway quota, and one llm_calls record per call. Capabilities the
probe has not confirmed (gemini_capabilities.json) fall back to a plain call or raise CapabilityUnavailable.

By default every call is written to `llm_calls` through S1's `db_ledger` on the stack database and priced from
pipeline_config `models.prices` (StackLedger). `ledger=None` turns recording off (unit tests); an explicit
`prices` mapping replaces the configured prices.
"""

import asyncio
import contextlib
import json
import logging
import os
import random
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from backend.common.telemetry import METRICS
from backend.config import FORBIDDEN_NAMES, ConfigError, Group, Settings, get_settings
from backend.llm_engine.gemini_adapters import (
    ADAPTERS,
    Adapter,
    Parsed,
    StreamState,
    drops_temperature,
    error_message,
    parse_structured,
)
from backend.llm_engine.gemini_types import (
    BudgetExhausted,
    CallContext,
    Capabilities,
    Capability,
    DailyTokenBudget,
    GatewayError,
    GatewayUnavailable,
    GeminiError,
    GenerateRequest,
    GenerateResult,
    Image,
    LlmCallRecord,
    Message,
    ModelPrice,
    Pdf,
    RequestTooLarge,
    SchemaArg,
    StreamDone,
    StreamEvent,
    Text,
    TextDelta,
    Usage,
)

log = logging.getLogger(__name__)

MAX_RETRY_AFTER_S = 300.0
MAX_INLINE_BYTES = 20 * 1024 * 1024
ESTIMATED_TOKENS = {"char": 0.25, "image": 1120, "pdf": 560}
IDEMPOTENCY_HEADER = "Idempotency-Key"


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        return max((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return None


def backoff_delay(
    attempt: int, retry_after: str | None, *, base_s: float = 1.0, cap_s: float = 60.0
) -> float:
    """Retry-After when the gateway sends one, else ~1 s doubling to 60 s with jitter (Google's guidance)."""
    honored = _retry_after_seconds(retry_after)
    if honored is not None:
        return min(honored, MAX_RETRY_AFTER_S)
    return min(cap_s, base_s * 2**attempt) * random.uniform(0.5, 1.0)  # noqa: S311


def estimate_usage(req: GenerateRequest, output_text: str, total: int | None = None) -> Usage:
    """Rough token counts when the gateway reports none (or only a total); marked estimated."""
    chars = sum(len(p.text) for m in req.messages for p in m.parts if isinstance(p, Text))
    media = sum(
        ESTIMATED_TOKENS["image"] if isinstance(p, Image) else ESTIMATED_TOKENS["pdf"]
        for m in req.messages
        for p in m.parts
        if isinstance(p, Image | Pdf)
    )
    input_tokens = int(chars * ESTIMATED_TOKENS["char"]) + media
    output_tokens = int(len(output_text) * ESTIMATED_TOKENS["char"])
    if total is not None:
        output_tokens = max(total - input_tokens, output_tokens)
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, estimated=True)


class CircuitBreaker:
    """Opens after `threshold` consecutive retryable failures and fails fast for `reset_after_s`; then one
    trial call goes through. Callers treat GatewayUnavailable as an outage (file 07 §12: extractive mode)."""

    def __init__(
        self, threshold: int = 5, reset_after_s: float = 30.0, clock: Callable[[], float] = time.monotonic
    ):
        self.threshold, self.reset_after_s, self._clock = threshold, reset_after_s, clock
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if self._clock() - self._opened_at < self.reset_after_s:
                raise GatewayUnavailable("gateway circuit open after repeated failures; retry later")
            self._opened_at = self._clock()

    def success(self) -> None:
        with self._lock:
            self._failures, self._opened_at = 0, None

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold:
                self._opened_at = self._clock()


class _ModelLimits:
    def __init__(self, limit: int):
        self.limit = limit
        self._sync: dict[str, threading.BoundedSemaphore] = {}
        self._async: dict[str, asyncio.Semaphore] = {}
        self._lock = threading.Lock()

    def sync(self, model: str) -> threading.BoundedSemaphore:
        with self._lock:
            return self._sync.setdefault(model, threading.BoundedSemaphore(self.limit))

    def async_(self, model: str) -> asyncio.Semaphore:
        with self._lock:
            return self._async.setdefault(model, asyncio.Semaphore(self.limit))


@dataclass
class _Call:
    req: GenerateRequest
    body: dict[str, Any]
    path: str
    context: CallContext
    started: float
    idempotency_key: str


PRICE_REFRESH_S = 300.0


class StackLedger:
    """The default llm_calls hook: rows through S1's `db_ledger`, prices from pipeline_config `models.prices`.

    Prices are re-read at most every `refresh_s`, so an operator's price change reaches running processes
    without a restart. A failed read keeps the last prices (empty at first, so `cost_estimate` stays null).
    """

    def __init__(
        self,
        read_prices: Callable[[], dict[str, ModelPrice]],
        write: Callable[[LlmCallRecord], None],
        refresh_s: float = PRICE_REFRESH_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._read_prices, self._write, self._refresh_s, self._clock = read_prices, write, refresh_s, clock
        self._prices: dict[str, ModelPrice] = {}
        self._read_at: float | None = None
        self._lock = threading.Lock()

    @classmethod
    def for_settings(cls, settings: Settings) -> "StackLedger":
        from sqlalchemy.orm import Session

        from backend.postgres.ledger import db_ledger
        from backend.postgres.pipeline_config import model_prices
        from backend.postgres.session import engine_from_settings

        engine = None

        def connected():
            nonlocal engine
            engine = engine or engine_from_settings(settings)
            return engine

        def read_prices() -> dict[str, ModelPrice]:
            with Session(connected()) as session:
                return model_prices(session)

        return cls(read_prices, lambda record: db_ledger(connected())(record))

    def prices(self) -> dict[str, ModelPrice]:
        with self._lock:
            now = self._clock()
            if self._read_at is None or now - self._read_at >= self._refresh_s:
                self._read_at = now
                try:
                    self._prices = self._read_prices()
                except Exception:
                    log.warning("models.prices unavailable; keeping %d known prices", len(self._prices))
            return self._prices

    def __call__(self, record: LlmCallRecord) -> None:
        self._write(record)


_STACK_LEDGER: Any = object()


class GeminiClient:
    """Async and sync access to Gemini through the gateway. One instance per process."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        capabilities: Capabilities | None = None,
        ledger: Callable[[LlmCallRecord], None] | None = _STACK_LEDGER,
        budget: DailyTokenBudget | None = None,
        prices: dict[str, ModelPrice] | None = None,
        timeout: httpx.Timeout | None = None,
        stream_idle_s: float = 60.0,
        max_attempts: int = 5,
        max_concurrency_per_model: int = 8,
        breaker: CircuitBreaker | None = None,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
        sleep: Callable[[float], Any] | None = None,
    ):
        for name in FORBIDDEN_NAMES:
            if name in os.environ:
                raise ConfigError(
                    f"{name} is set; the Gemini client refuses to start (docs/architecture/09 §H.1)"
                )
        settings = (settings or get_settings()).require(Group.GEMINI)
        self.adapter: Adapter = ADAPTERS[settings.gemini_api_style]
        self._base_url = str(settings.gemini_gateway_url).rstrip("/")
        self._headers = self.adapter.headers(settings.gemini_gateway_key.get_secret_value())
        self._default_thinking = settings.gemini_thinking_level
        self._default_include_thoughts = settings.gemini_include_thoughts
        self.capabilities = capabilities or Capabilities.load()
        if ledger is _STACK_LEDGER:
            ledger = StackLedger.for_settings(settings)
        self._ledger, self._budget, self._prices = ledger, budget, prices
        self._timeout = timeout or httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=10.0)
        self._stream_timeout = httpx.Timeout(connect=10.0, read=stream_idle_s, write=60.0, pool=10.0)
        self._max_attempts = max_attempts
        self._limits = _ModelLimits(max_concurrency_per_model)
        self.breaker = breaker or CircuitBreaker()
        self._transport, self._sleep = transport, sleep
        self._async_http: httpx.AsyncClient | None = None
        self._sync_http: httpx.Client | None = None
        self.quota_remaining: int | None = None

    def __repr__(self) -> str:
        return f"GeminiClient(style={self.adapter.style}, capabilities={sorted(self.capabilities.enabled)})"

    def _client_kwargs(self, sync: bool) -> dict[str, Any]:
        wanted = httpx.BaseTransport if sync else httpx.AsyncBaseTransport
        transport = self._transport if isinstance(self._transport, wanted) else None
        return {
            "base_url": self._base_url,
            "headers": self._headers,
            "timeout": self._timeout,
            "transport": transport,
        }

    @property
    def _async(self) -> httpx.AsyncClient:
        if self._async_http is None:
            self._async_http = httpx.AsyncClient(**self._client_kwargs(sync=False))
        return self._async_http

    @property
    def _sync(self) -> httpx.Client:
        if self._sync_http is None:
            self._sync_http = httpx.Client(**self._client_kwargs(sync=True))
        return self._sync_http

    async def aclose(self) -> None:
        if self._async_http is not None:
            await self._async_http.aclose()
            self._async_http = None

    def close(self) -> None:
        if self._sync_http is not None:
            self._sync_http.close()
            self._sync_http = None

    async def _async_sleep(self, delay: float) -> None:
        if self._sleep is None:
            await asyncio.sleep(delay)
        elif asyncio.iscoroutine(pending := self._sleep(delay)):
            await pending

    def _prepare(
        self,
        model: str,
        messages: list[Message],
        context: CallContext,
        schema: SchemaArg,
        stream: bool,
        **options,
    ) -> _Call:
        try:
            if self._budget is not None:
                self._budget.check()
            if self.quota_remaining is not None and self.quota_remaining <= 0:
                raise BudgetExhausted("the gateway reports its daily quota as used up")
        except BudgetExhausted:
            METRICS.llm_budget_exhausted_total.add(1, {"model": model})
            raise
        include_thoughts = options.pop("include_thoughts", None)
        req = GenerateRequest(
            model=model,
            messages=tuple(messages),
            schema=schema,
            tools=tuple(options.pop("tools", None) or ()),
            safety_settings=tuple(options.pop("safety_settings", None) or ()),
            thinking=options.pop("thinking", None) or self._default_thinking,
            include_thoughts=self._default_include_thoughts if include_thoughts is None else include_thoughts,
            **options,
        )
        inline = sum(len(p.data) for m in req.messages for p in m.parts if isinstance(p, Image | Pdf))
        if inline > MAX_INLINE_BYTES:
            raise RequestTooLarge(
                f"{inline} bytes of inline media exceed {MAX_INLINE_BYTES}; send page windows"
            )
        if req.temperature is not None and drops_temperature(model):
            log.info("temperature not sent to %s (ignored by Gemini 3.6+)", model)
        body = self.adapter.build(req, self.capabilities, stream)
        return _Call(
            req, body, self.adapter.path(model, stream), context, time.monotonic(), str(uuid.uuid4())
        )

    def _price_list(self) -> dict[str, ModelPrice]:
        if self._prices is not None:
            return self._prices
        return self._ledger.prices() if isinstance(self._ledger, StackLedger) else {}

    def _record(self, call: _Call, usage: Usage, request_id: str | None, error: GeminiError | None) -> int:
        latency_ms = int((time.monotonic() - call.started) * 1000)
        if self._budget is not None:
            self._budget.record(usage.total_tokens)
        price = self._price_list().get(call.req.model)
        record = LlmCallRecord(
            at=datetime.now(UTC),
            model=call.req.model,
            purpose=call.context.purpose,
            prompt_version=call.context.prompt_version,
            doc_id=call.context.doc_id,
            node_anchor=call.context.node_anchor,
            trace_id=call.context.trace_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            latency_ms=latency_ms,
            cost_estimate=price.cost(usage) if price else None,
            status="error" if error else "ok",
            error=str(error) if error else None,
            request_id=request_id or call.idempotency_key,
            usage_estimated=usage.estimated,
        )
        labels = {"model": record.model, "purpose": record.purpose}
        METRICS.llm_calls_total.add(1, {**labels, "status": record.status})
        for kind, tokens in (
            ("input", usage.input_tokens),
            ("output", usage.output_tokens),
            ("cached", usage.cached_tokens),
        ):
            if tokens:
                METRICS.llm_tokens_total.add(tokens, {**labels, "kind": kind})
        if record.cost_estimate:
            METRICS.llm_cost_total.add(record.cost_estimate, {"model": record.model})
        if self._ledger is not None:
            try:
                self._ledger(record)
            except Exception:
                log.exception("llm_calls ledger hook failed for purpose=%s", call.context.purpose)
        return latency_ms

    def _error(self, response: httpx.Response) -> GatewayError:
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        message = error_message(body, response.text)
        if response.status_code in (401, 403) and "key" in message.lower():
            message = f"key rejected: {message}"
        return GatewayError(
            f"gateway returned HTTP {response.status_code}: {message}",
            status_code=response.status_code,
            retryable=self.adapter.retryable(response.status_code, body),
        )

    def _after_failure(
        self, call: _Call, attempt: int, error: GatewayError, retry_after: str | None
    ) -> float:
        if error.retryable:
            self.breaker.failure()
        if not error.retryable or attempt == self._max_attempts - 1 or self.breaker.is_open:
            self._record(call, Usage(), None, error)
            raise error
        delay = backoff_delay(attempt, retry_after)
        log.warning("gateway call failed (%s); retry %d in %.1fs", error.status_code, attempt + 1, delay)
        return delay

    def _start(self, call: _Call) -> None:
        try:
            self.breaker.before_call()
        except GatewayUnavailable as exc:
            self._record(call, Usage(), None, exc)
            raise

    def _outcome(
        self, response: httpx.Response | Exception
    ) -> tuple[httpx.Response | None, GatewayError | None, str | None]:
        if isinstance(response, Exception):
            return None, GatewayError(f"gateway unreachable: {type(response).__name__}", retryable=True), None
        if response.is_success:
            self.breaker.success()
            return response, None, None
        return None, self._error(response), response.headers.get("retry-after")

    async def _apost(self, call: _Call) -> httpx.Response:
        for attempt in range(self._max_attempts):
            self._start(call)
            try:
                raw: httpx.Response | Exception = await self._async.post(
                    call.path, json=call.body, headers={IDEMPOTENCY_HEADER: call.idempotency_key}
                )
            except httpx.TransportError as exc:
                raw = exc
            response, error, retry_after = self._outcome(raw)
            if response is not None:
                return response
            await self._async_sleep(self._after_failure(call, attempt, error, retry_after))
        raise AssertionError("unreachable")

    def _post(self, call: _Call) -> httpx.Response:
        for attempt in range(self._max_attempts):
            self._start(call)
            try:
                raw: httpx.Response | Exception = self._sync.post(
                    call.path, json=call.body, headers={IDEMPOTENCY_HEADER: call.idempotency_key}
                )
            except httpx.TransportError as exc:
                raw = exc
            response, error, retry_after = self._outcome(raw)
            if response is not None:
                return response
            (self._sleep or time.sleep)(self._after_failure(call, attempt, error, retry_after))
        raise AssertionError("unreachable")

    async def _open_stream(self, call: _Call) -> httpx.Response:
        for attempt in range(self._max_attempts):
            self._start(call)
            request = self._async.build_request(
                "POST",
                call.path,
                json=call.body,
                headers={IDEMPOTENCY_HEADER: call.idempotency_key},
                timeout=self._stream_timeout,
            )
            try:
                raw: httpx.Response | Exception = await self._async.send(request, stream=True)
                if not raw.is_success:
                    with contextlib.suppress(httpx.HTTPError):
                        await raw.aread()
                    await raw.aclose()
            except httpx.TransportError as exc:
                raw = exc
            response, error, retry_after = self._outcome(raw)
            if response is not None:
                return response
            await self._async_sleep(self._after_failure(call, attempt, error, retry_after))
        raise AssertionError("unreachable")

    def _result(self, call: _Call, parsed: Parsed, header_request_id: str | None) -> GenerateResult:
        request_id = parsed.request_id or header_request_id
        usage = parsed.usage or estimate_usage(call.req, parsed.text)
        if parsed.quota and parsed.quota.get("remaining") is not None:
            self.quota_remaining = int(parsed.quota["remaining"])
        try:
            structured = None
            if call.req.schema is not None and not parsed.tool_calls:
                structured = parse_structured(parsed.text, call.req.schema, parsed.structured)
        except GeminiError as exc:
            self._record(call, usage, request_id, exc)
            raise
        latency_ms = self._record(call, usage, request_id, None)
        return GenerateResult(
            text=parsed.text,
            parsed=structured,
            tool_calls=parsed.tool_calls,
            usage=usage,
            model=parsed.model or call.req.model,
            finish_reason=parsed.finish_reason,
            request_id=request_id or call.idempotency_key,
            latency_ms=latency_ms,
            thoughts=parsed.thoughts,
            quota=parsed.quota,
            grounding=parsed.grounding,
        )

    def _finish(self, call: _Call, response: httpx.Response) -> GenerateResult:
        try:
            parsed = self.adapter.parse(response.json())
        except (GeminiError, ValueError) as exc:
            error = (
                exc if isinstance(exc, GeminiError) else GeminiError(f"unreadable gateway response: {exc}")
            )
            self._record(call, Usage(), response.headers.get("x-request-id"), error)
            raise error from None
        return self._result(call, parsed, response.headers.get("x-request-id"))

    async def generate(
        self,
        *,
        model: str,
        messages: list[Message],
        context: CallContext,
        schema: SchemaArg = None,
        **options: Any,
    ) -> GenerateResult:
        """Options: tools, tool_choice, thinking, include_thoughts, media_resolution, temperature,
        max_output_tokens, cached_content, safety_settings (none sent by default; extraction capabilities
        pass gemini_types.EXTRACTION_SAFETY when their config flag is on), google_search (only with an
        already-sanitized query: the model writes the Google queries from the whole prompt; they come
        back in result.grounding.queries)."""
        call = self._prepare(model, messages, context, schema, False, **options)
        async with self._limits.async_(model):
            response = await self._apost(call)
        return self._finish(call, response)

    def generate_sync(
        self,
        *,
        model: str,
        messages: list[Message],
        context: CallContext,
        schema: SchemaArg = None,
        **options: Any,
    ) -> GenerateResult:
        call = self._prepare(model, messages, context, schema, False, **options)
        with self._limits.sync(model):
            response = self._post(call)
        return self._finish(call, response)

    async def stream(
        self, *, model: str, messages: list[Message], context: CallContext, **options: Any
    ) -> AsyncIterator[StreamEvent]:
        """Text deltas, then one StreamDone. Without the streaming capability: one delta from a plain call."""
        if not self.capabilities.has(Capability.STREAMING):
            result = await self.generate(model=model, messages=messages, context=context, **options)
            yield TextDelta(result.text)
            yield StreamDone(result)
            return
        call = self._prepare(model, messages, context, None, True, **options)
        state = StreamState.new()
        async with self._limits.async_(model):
            response = await self._open_stream(call)
            try:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    piece = self.adapter.chunk(json.loads(data), state)
                    if piece:
                        yield TextDelta(piece)
                    if state.done:
                        break
            except (httpx.TransportError, json.JSONDecodeError) as exc:
                error = GatewayError(f"stream interrupted: {type(exc).__name__}", retryable=True)
                self._record(call, state.usage or Usage(), state.request_id, error)
                raise error from None
            finally:
                await response.aclose()
        text = "".join(state.text)
        usage = state.usage
        if usage is None or usage.estimated:
            usage = estimate_usage(call.req, text, usage.output_tokens if usage else None)
        parsed = Parsed(
            text=text,
            tool_calls=self.adapter.finish_stream(state),
            usage=usage,
            finish_reason=state.finish_reason,
            request_id=state.request_id,
            model=state.model,
            quota=state.quota,
        )
        yield StreamDone(self._result(call, parsed, response.headers.get("x-request-id")))
