"""The only module that talks to the Manastu Gemini gateway (docs/architecture/01 §7, §7.1; 09 §H.1).

Wire shape: OpenAI-compatible chat completions at `{GEMINI_GATEWAY_URL}/chat/completions`. Plain text chat is
the baseline. Every other capability is enabled only when the probe recorded it as supported in
gemini_capabilities.json; a disabled capability falls back to a plain call or raises CapabilityUnavailable.
"""

import asyncio
import base64
import inspect
import json
import logging
import os
import random
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ValidationError

from backend.config import FORBIDDEN_NAMES, ConfigError, Group, Settings, ThinkingLevel, get_settings

log = logging.getLogger(__name__)

CAPABILITIES_FILE = Path(__file__).with_name("gemini_capabilities.json")
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
MAX_RETRY_AFTER_S = 300.0
ERROR_BODY_LIMIT = 300


class Capability(StrEnum):
    STRUCTURED_OUTPUT = "structured_output"
    FUNCTION_CALLING = "function_calling"
    THINKING_LEVEL = "thinking_level"
    INCLUDE_THOUGHTS = "include_thoughts"
    IMAGE_INPUT = "image_input"
    PDF_INPUT = "pdf_input"
    MEDIA_RESOLUTION = "media_resolution"
    STREAMING = "streaming"
    STREAM_USAGE = "stream_usage"
    CONTEXT_CACHE = "context_cache"
    BATCH = "batch"


class CapabilityStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Capabilities:
    enabled: frozenset[Capability] = frozenset()
    probed_at: str | None = None

    @classmethod
    def all(cls) -> "Capabilities":
        return cls(enabled=frozenset(Capability))

    @classmethod
    def load(cls, path: Path = CAPABILITIES_FILE) -> "Capabilities":
        data = json.loads(path.read_text())
        enabled = frozenset(
            Capability(name)
            for name, entry in data.get("capabilities", {}).items()
            if name in Capability.__members__.values() and entry.get("status") == CapabilityStatus.SUPPORTED
        )
        return cls(enabled=enabled, probed_at=data.get("probed_at"))

    def has(self, capability: Capability) -> bool:
        return capability in self.enabled


class GeminiError(RuntimeError):
    pass


class GatewayError(GeminiError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class CapabilityUnavailable(GeminiError):
    def __init__(self, capability: Capability):
        super().__init__(f"the gateway capability '{capability}' is not enabled (gemini_capabilities.json)")
        self.capability = capability


class BudgetExhausted(GeminiError):
    """Raised before a call once the daily token budget is used; callers retry later so queues wait."""


class StructuredOutputError(GeminiError):
    def __init__(self, message: str, *, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Image:
    data: bytes
    mime_type: str = "image/png"


@dataclass(frozen=True)
class Pdf:
    data: bytes
    filename: str = "document.pdf"


Part = Text | Image | Pdf


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    parts: tuple[Part, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    @classmethod
    def system(cls, text: str) -> "Message":
        return cls("system", (Text(text),))

    @classmethod
    def user(cls, *parts: Part | str) -> "Message":
        return cls("user", tuple(Text(p) if isinstance(p, str) else p for p in parts))

    @classmethod
    def assistant(cls, text: str = "", tool_calls: tuple[ToolCall, ...] = ()) -> "Message":
        return cls("assistant", (Text(text),) if text else (), tool_calls)

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str) -> "Message":
        return cls("tool", (Text(content),), tool_call_id=tool_call_id)


@dataclass(frozen=True)
class CallContext:
    purpose: str
    prompt_version: str | None = None
    doc_id: str | None = None
    node_anchor: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thinking_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class GenerateResult:
    text: str
    parsed: Any
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    model: str
    finish_reason: str | None
    request_id: str | None
    latency_ms: int
    thoughts: str | None = None


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class StreamDone:
    result: GenerateResult


StreamEvent = TextDelta | StreamDone


@dataclass(frozen=True)
class LlmCallRecord:
    """One row of llm_calls (docs/architecture/05 §4.6); status is 'ok' or 'error'."""

    at: datetime
    model: str
    purpose: str
    prompt_version: str | None
    doc_id: str | None
    node_anchor: str | None
    trace_id: str | None
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    latency_ms: int
    cost_estimate: float | None
    status: Literal["ok", "error"]
    error: str | None
    request_id: str | None


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    cached_per_mtok: float = 0.0

    def cost(self, usage: Usage) -> float:
        uncached = max(usage.input_tokens - usage.cached_tokens, 0)
        return (
            uncached * self.input_per_mtok
            + usage.cached_tokens * self.cached_per_mtok
            + usage.output_tokens * self.output_per_mtok
        ) / 1_000_000


@dataclass
class DailyTokenBudget:
    """Daily cap from pipeline_config `cloud.daily_token_budget`.

    `usage_today` returns tokens already used today (the llm_calls aggregate once that table exists); without
    it the budget counts the tokens of this process since UTC midnight.
    """

    limit_tokens: int | None
    usage_today: Callable[[], int] | None = None
    today: Callable[[], date] = field(default=lambda: datetime.now(UTC).date())
    _day: date | None = field(default=None, init=False)
    _used: int = field(default=0, init=False)

    def used(self) -> int:
        if self.usage_today is not None:
            return self.usage_today()
        if self._day != self.today():
            self._day, self._used = self.today(), 0
        return self._used

    def check(self) -> None:
        if self.limit_tokens is not None and self.used() >= self.limit_tokens:
            raise BudgetExhausted(f"daily Gemini token budget of {self.limit_tokens} tokens is used up")

    def record(self, tokens: int) -> None:
        if self.usage_today is None:
            self.used()
            self._used += tokens


SchemaArg = type[BaseModel] | dict[str, Any] | None


def _data_uri(mime_type: str, data: bytes) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def _content(parts: tuple[Part, ...], caps: Capabilities, media_resolution: str | None) -> str | list:
    if all(isinstance(p, Text) for p in parts):
        return "".join(p.text for p in parts)
    content: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, Text):
            content.append({"type": "text", "text": part.text})
        elif isinstance(part, Image):
            if not caps.has(Capability.IMAGE_INPUT):
                raise CapabilityUnavailable(Capability.IMAGE_INPUT)
            image_url: dict[str, Any] = {"url": _data_uri(part.mime_type, part.data)}
            if media_resolution and caps.has(Capability.MEDIA_RESOLUTION):
                image_url["detail"] = media_resolution
            content.append({"type": "image_url", "image_url": image_url})
        else:
            if not caps.has(Capability.PDF_INPUT):
                raise CapabilityUnavailable(Capability.PDF_INPUT)
            content.append(
                {
                    "type": "file",
                    "file": {"filename": part.filename, "file_data": _data_uri("application/pdf", part.data)},
                }
            )
    return content


def _wire_message(message: Message, caps: Capabilities, media_resolution: str | None) -> dict[str, Any]:
    wire: dict[str, Any] = {"role": message.role, "content": _content(message.parts, caps, media_resolution)}
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        wire["tool_call_id"] = message.tool_call_id
    return wire


def _json_schema(schema: SchemaArg) -> tuple[str, dict[str, Any]]:
    if isinstance(schema, dict):
        return str(schema.get("title", "response")), schema
    return schema.__name__, schema.model_json_schema()


def build_request(
    *,
    model: str,
    messages: list[Message],
    caps: Capabilities,
    schema: SchemaArg = None,
    tools: list[ToolSpec] | None = None,
    tool_choice: Literal["auto", "required", "none"] | None = None,
    thinking: ThinkingLevel | None = None,
    include_thoughts: bool = False,
    media_resolution: Literal["low", "medium", "high"] | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    cached_content: str | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    messages = list(messages)
    body: dict[str, Any] = {"model": model}
    if schema is not None:
        name, json_schema = _json_schema(schema)
        if caps.has(Capability.STRUCTURED_OUTPUT):
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": name, "schema": json_schema},
            }
        else:
            instruction = (
                "Respond with one JSON object only, no prose and no code fences, that validates against this "
                f"JSON Schema:\n{json.dumps(json_schema)}"
            )
            messages.insert(0, Message.system(instruction))
    body["messages"] = [_wire_message(m, caps, media_resolution) for m in messages]
    if tools:
        if not caps.has(Capability.FUNCTION_CALLING):
            raise CapabilityUnavailable(Capability.FUNCTION_CALLING)
        body["tools"] = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
            }
            for t in tools
        ]
        if tool_choice:
            body["tool_choice"] = tool_choice
    if thinking is not None and caps.has(Capability.THINKING_LEVEL):
        body["reasoning_effort"] = str(thinking)
    google: dict[str, Any] = {}
    if include_thoughts and caps.has(Capability.INCLUDE_THOUGHTS):
        google["thinking_config"] = {"include_thoughts": True}
    if cached_content and caps.has(Capability.CONTEXT_CACHE):
        google["cached_content"] = cached_content
    if google:
        body["extra_body"] = {"google": google}
    if temperature is not None:
        body["temperature"] = temperature
    if max_output_tokens is not None:
        body["max_tokens"] = max_output_tokens
    if stream:
        body["stream"] = True
        if caps.has(Capability.STREAM_USAGE):
            body["stream_options"] = {"include_usage": True}
    return body


THOUGHT_TAG = re.compile(r"<thought>(.*?)</thought>", re.DOTALL)
CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if isinstance(item, dict))
    return ""


def _split_thoughts(text: str, reasoning: str | None) -> tuple[str, str | None]:
    found = THOUGHT_TAG.findall(text)
    thoughts = "\n".join([*([reasoning] if reasoning else []), *found]) or None
    return THOUGHT_TAG.sub("", text).strip() if found else text, thoughts


def _usage(raw: dict[str, Any] | None) -> Usage:
    raw = raw or {}
    return Usage(
        input_tokens=int(raw.get("prompt_tokens") or 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cached_tokens=int((raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
        thinking_tokens=int((raw.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
    )


def _tool_calls(raw: list[dict[str, Any]] | None) -> tuple[ToolCall, ...]:
    calls = []
    for item in raw or []:
        function = item.get("function") or {}
        arguments = function.get("arguments") or "{}"
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except json.JSONDecodeError as exc:
            raise GeminiError(
                f"tool call '{function.get('name')}' returned arguments that are not JSON"
            ) from exc
        calls.append(
            ToolCall(id=str(item.get("id") or ""), name=str(function.get("name") or ""), arguments=parsed)
        )
    return tuple(calls)


def parse_structured(text: str, schema: SchemaArg) -> Any:
    if schema is None:
        return None
    match = CODE_FENCE.match(text)
    payload = match.group(1) if match else text
    try:
        if isinstance(schema, dict):
            return json.loads(payload)
        return schema.model_validate_json(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise StructuredOutputError(
            f"response does not match the schema: {type(exc).__name__}", raw_text=text
        ) from None


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
    honored = _retry_after_seconds(retry_after)
    if honored is not None:
        return min(honored, MAX_RETRY_AFTER_S)
    return min(cap_s, base_s * 2**attempt) * random.uniform(0.5, 1.0)  # noqa: S311


def _gateway_error(response: httpx.Response) -> GatewayError:
    try:
        detail = response.json().get("error", {})
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
    except (ValueError, AttributeError):
        message = response.text
    message = (message or "").strip()[:ERROR_BODY_LIMIT]
    return GatewayError(
        f"gateway returned HTTP {response.status_code}: {message}",
        status_code=response.status_code,
        retryable=response.status_code in RETRYABLE_STATUS,
    )


def _transport_error(exc: httpx.TransportError) -> GatewayError:
    return GatewayError(f"gateway unreachable: {type(exc).__name__}", retryable=True)


@dataclass
class _Call:
    body: dict[str, Any]
    model: str
    schema: SchemaArg
    context: CallContext
    started: float


class GeminiClient:
    """Async and sync access to Gemini through the gateway. One instance per process is enough."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        capabilities: Capabilities | None = None,
        ledger: Callable[[LlmCallRecord], None] | None = None,
        budget: DailyTokenBudget | None = None,
        prices: dict[str, ModelPrice] | None = None,
        timeout: httpx.Timeout | None = None,
        max_attempts: int = 5,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
        sleep: Callable[[float], Any] | None = None,
    ):
        for name in FORBIDDEN_NAMES:
            if name in os.environ:
                raise ConfigError(
                    f"{name} is set; the Gemini client refuses to start (docs/architecture/09 §H.1)"
                )
        settings = (settings or get_settings()).require(Group.GEMINI)
        self._base_url = str(settings.gemini_gateway_url).rstrip("/")
        self._headers = {"Authorization": f"Bearer {settings.gemini_gateway_key.get_secret_value()}"}
        self._default_thinking = settings.gemini_thinking_level
        self._default_include_thoughts = settings.gemini_include_thoughts
        self.capabilities = capabilities or Capabilities.load()
        self._ledger = ledger
        self._budget = budget
        self._prices = prices or {}
        self._timeout = timeout or httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=10.0)
        self._max_attempts = max_attempts
        self._transport = transport
        self._sleep = sleep
        self._async_http: httpx.AsyncClient | None = None
        self._sync_http: httpx.Client | None = None

    def __repr__(self) -> str:
        return f"GeminiClient(capabilities={sorted(self.capabilities.enabled)})"

    @property
    def _async(self) -> httpx.AsyncClient:
        if self._async_http is None:
            transport = self._transport if isinstance(self._transport, httpx.AsyncBaseTransport) else None
            self._async_http = httpx.AsyncClient(
                base_url=self._base_url, headers=self._headers, timeout=self._timeout, transport=transport
            )
        return self._async_http

    @property
    def _sync(self) -> httpx.Client:
        if self._sync_http is None:
            transport = self._transport if isinstance(self._transport, httpx.BaseTransport) else None
            self._sync_http = httpx.Client(
                base_url=self._base_url, headers=self._headers, timeout=self._timeout, transport=transport
            )
        return self._sync_http

    async def _async_sleep(self, delay: float) -> None:
        if self._sleep is None:
            await asyncio.sleep(delay)
        elif inspect.isawaitable(pending := self._sleep(delay)):
            await pending

    async def aclose(self) -> None:
        if self._async_http is not None:
            await self._async_http.aclose()
            self._async_http = None

    def close(self) -> None:
        if self._sync_http is not None:
            self._sync_http.close()
            self._sync_http = None

    def _prepare(
        self, model: str, messages: list[Message], context: CallContext, schema: SchemaArg, **options
    ):
        if self._budget is not None:
            self._budget.check()
        thinking = options.pop("thinking", None) or self._default_thinking
        include_thoughts = options.pop("include_thoughts", None)
        if include_thoughts is None:
            include_thoughts = self._default_include_thoughts
        body = build_request(
            model=model,
            messages=messages,
            caps=self.capabilities,
            schema=schema,
            thinking=thinking,
            include_thoughts=include_thoughts,
            **options,
        )
        return _Call(body=body, model=model, schema=schema, context=context, started=time.monotonic())

    def _record(self, call: _Call, usage: Usage, request_id: str | None, error: GeminiError | None) -> int:
        latency_ms = int((time.monotonic() - call.started) * 1000)
        if self._budget is not None:
            self._budget.record(usage.total_tokens)
        price = self._prices.get(call.model)
        record = LlmCallRecord(
            at=datetime.now(UTC),
            model=call.model,
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
            request_id=request_id,
        )
        if self._ledger is not None:
            try:
                self._ledger(record)
            except Exception:
                log.exception("llm_calls ledger hook failed for purpose=%s", call.context.purpose)
        return latency_ms

    def _finish(self, call: _Call, payload: dict[str, Any], header_request_id: str | None) -> GenerateResult:
        request_id = payload.get("id") or header_request_id
        usage = _usage(payload.get("usage"))
        try:
            choices = payload.get("choices") or []
            if not choices:
                raise GeminiError("gateway response has no choices")
            message = choices[0].get("message") or {}
            text, thoughts = _split_thoughts(
                _text_of(message.get("content")), message.get("reasoning_content")
            )
            tool_calls = _tool_calls(message.get("tool_calls"))
            parsed = (
                parse_structured(text, call.schema) if call.schema is not None and not tool_calls else None
            )
        except GeminiError as exc:
            self._record(call, usage, request_id, exc)
            raise
        latency_ms = self._record(call, usage, request_id, None)
        return GenerateResult(
            text=text,
            parsed=parsed,
            tool_calls=tool_calls,
            usage=usage,
            model=str(payload.get("model") or call.model),
            finish_reason=choices[0].get("finish_reason"),
            request_id=request_id,
            latency_ms=latency_ms,
            thoughts=thoughts,
        )

    def _retry_delay_or_raise(
        self, call: _Call, attempt: int, error: GatewayError, retry_after: str | None
    ) -> float:
        if not error.retryable or attempt == self._max_attempts - 1:
            self._record(call, Usage(), None, error)
            raise error
        delay = backoff_delay(attempt, retry_after)
        log.warning("gateway call failed (%s); retry %d in %.1fs", error.status_code, attempt + 1, delay)
        return delay

    async def _apost(self, call: _Call) -> httpx.Response:
        for attempt in range(self._max_attempts):
            try:
                response = await self._async.post("/chat/completions", json=call.body)
            except httpx.TransportError as exc:
                error, retry_after = _transport_error(exc), None
            else:
                if response.is_success:
                    return response
                error, retry_after = _gateway_error(response), response.headers.get("retry-after")
            await self._async_sleep(self._retry_delay_or_raise(call, attempt, error, retry_after))
        raise AssertionError("unreachable")

    def _post(self, call: _Call) -> httpx.Response:
        for attempt in range(self._max_attempts):
            try:
                response = self._sync.post("/chat/completions", json=call.body)
            except httpx.TransportError as exc:
                error, retry_after = _transport_error(exc), None
            else:
                if response.is_success:
                    return response
                error, retry_after = _gateway_error(response), response.headers.get("retry-after")
            (self._sleep or time.sleep)(self._retry_delay_or_raise(call, attempt, error, retry_after))
        raise AssertionError("unreachable")

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
        max_output_tokens, cached_content (see build_request)."""
        call = self._prepare(model, messages, context, schema, **options)
        response = await self._apost(call)
        return self._finish(call, response.json(), response.headers.get("x-request-id"))

    def generate_sync(
        self,
        *,
        model: str,
        messages: list[Message],
        context: CallContext,
        schema: SchemaArg = None,
        **options: Any,
    ) -> GenerateResult:
        call = self._prepare(model, messages, context, schema, **options)
        response = self._post(call)
        return self._finish(call, response.json(), response.headers.get("x-request-id"))

    async def stream(
        self,
        *,
        model: str,
        messages: list[Message],
        context: CallContext,
        **options: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Text deltas, then one StreamDone. Without the streaming capability: one delta from a plain call."""
        if not self.capabilities.has(Capability.STREAMING):
            result = await self.generate(model=model, messages=messages, context=context, **options)
            yield TextDelta(result.text)
            yield StreamDone(result)
            return
        call = self._prepare(model, messages, context, None, stream=True, **options)
        payload = await self._astream_payload(call)
        async for event in payload:
            yield event

    async def _astream_payload(self, call: _Call) -> AsyncIterator[StreamEvent]:
        for attempt in range(self._max_attempts):
            request = self._async.build_request("POST", "/chat/completions", json=call.body)
            try:
                response = await self._async.send(request, stream=True)
            except httpx.TransportError as exc:
                error, retry_after = _transport_error(exc), None
            else:
                if response.is_success:
                    return self._read_stream(call, response)
                await response.aread()
                await response.aclose()
                error, retry_after = _gateway_error(response), response.headers.get("retry-after")
            await self._async_sleep(self._retry_delay_or_raise(call, attempt, error, retry_after))
        raise AssertionError("unreachable")

    async def _read_stream(self, call: _Call, response: httpx.Response) -> AsyncIterator[StreamEvent]:
        text: list[str] = []
        tool_parts: dict[int, dict[str, Any]] = {}
        usage_raw: dict[str, Any] | None = None
        request_id = response.headers.get("x-request-id")
        model = call.model
        finish_reason = None
        try:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                request_id = chunk.get("id") or request_id
                model = chunk.get("model") or model
                usage_raw = chunk.get("usage") or usage_raw
                for choice in chunk.get("choices") or []:
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") or {}
                    piece = _text_of(delta.get("content"))
                    if piece:
                        text.append(piece)
                        yield TextDelta(piece)
                    for tool_delta in delta.get("tool_calls") or []:
                        slot = tool_parts.setdefault(
                            tool_delta.get("index", 0), {"id": "", "function": {"name": "", "arguments": ""}}
                        )
                        slot["id"] = tool_delta.get("id") or slot["id"]
                        function = tool_delta.get("function") or {}
                        slot["function"]["name"] += function.get("name") or ""
                        slot["function"]["arguments"] += function.get("arguments") or ""
        except (httpx.TransportError, json.JSONDecodeError) as exc:
            error = GatewayError(f"stream interrupted: {type(exc).__name__}", retryable=True)
            self._record(call, _usage(usage_raw), request_id, error)
            raise error from None
        finally:
            await response.aclose()
        payload = {
            "id": request_id,
            "model": model,
            "usage": usage_raw,
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {
                        "content": "".join(text),
                        "tool_calls": [tool_parts[i] for i in sorted(tool_parts)],
                    },
                }
            ],
        }
        yield StreamDone(self._finish(call, payload, request_id))
