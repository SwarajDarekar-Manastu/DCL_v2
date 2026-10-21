"""Types, capability flags and errors of the Gemini gateway client (see gemini_client.py)."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

CAPABILITIES_FILE = Path(__file__).with_name("gemini_capabilities.json")


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
