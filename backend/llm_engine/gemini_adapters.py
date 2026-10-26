"""Wire formats of the gateway client (docs/architecture/09 §H.1). Selected by GEMINI_API_STYLE.

- ManastuGatewayAdapter (default, `manastu`): the Manastu gateway, a custom API around the google-genai SDK.
  `X-API-Key`; `POST /generate` and `POST /stream`; snake_case `contents` + `config`; the response is the SDK
  response JSON with `parsed`, `response_id`, `usage_metadata` and `quota`; upstream errors are HTTP 502.
- GeminiNativeAdapter (`gemini`): the same content model with camelCase keys on generateContent paths.
- OpenAICompatAdapter (`openai`): OpenAI-shaped chat completions.

Adapters are pure: they build bodies and parse payloads; transport, retries and accounting live in the client.
"""

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.config import ApiStyle
from backend.llm_engine.gemini_types import (
    Capabilities,
    Capability,
    CapabilityUnavailable,
    GeminiError,
    GenerateRequest,
    Grounding,
    GroundingSource,
    Image,
    Message,
    SchemaArg,
    StructuredOutputError,
    Text,
    ToolCall,
    Usage,
)

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
RETRYABLE_UPSTREAM = frozenset({408, 429, 500, 503, 504})
ERROR_BODY_LIMIT = 300
CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
THOUGHT_TAG = re.compile(r"<thought>(.*?)</thought>", re.DOTALL)
UPSTREAM_CODE = re.compile(r"\b([45]\d\d) [A-Z_]+\b")
MODEL_VERSION = re.compile(r"gemini-(\d+)(?:\.(\d+))?")
CALLING_MODE = {"auto": "AUTO", "required": "ANY", "none": "NONE"}


@dataclass(frozen=True)
class Parsed:
    text: str
    tool_calls: tuple[ToolCall, ...]
    usage: Usage | None
    finish_reason: str | None
    request_id: str | None
    model: str | None
    thoughts: str | None = None
    structured: Any = None
    quota: dict[str, Any] | None = None
    grounding: Grounding | None = None


@dataclass
class StreamState:
    text: list[str]
    tool_calls: list[ToolCall]
    tool_fragments: dict[int, dict[str, Any]]
    usage: Usage | None = None
    finish_reason: str | None = None
    request_id: str | None = None
    model: str | None = None
    quota: dict[str, Any] | None = None
    done: bool = False

    @classmethod
    def new(cls) -> "StreamState":
        return cls(text=[], tool_calls=[], tool_fragments={})


def data_uri(mime_type: str, data: bytes) -> str:
    return f"data:{mime_type};base64,{b64(data)}"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def json_schema(schema: SchemaArg) -> tuple[str, dict[str, Any]]:
    if isinstance(schema, dict):
        return str(schema.get("title", "response")), schema
    return schema.__name__, schema.model_json_schema()


def schema_instruction(schema: SchemaArg) -> Message:
    return Message.system(
        "Respond with one JSON object only, no prose and no code fences, that validates against this "
        f"JSON Schema:\n{json.dumps(json_schema(schema)[1])}"
    )


def parse_structured(text: str, schema: SchemaArg, gateway_parsed: Any = None) -> Any:
    if schema is None:
        return None
    try:
        if gateway_parsed is not None:
            return gateway_parsed if isinstance(schema, dict) else schema.model_validate(gateway_parsed)
        match = CODE_FENCE.match(text)
        payload = match.group(1) if match else text
        return json.loads(payload) if isinstance(schema, dict) else schema.model_validate_json(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise StructuredOutputError(
            f"response does not match the schema: {type(exc).__name__}: {_what_broke(exc)}", raw_text=text
        ) from None


def _what_broke(exc: json.JSONDecodeError | ValidationError) -> str:
    """The first three broken fields of a reply, or where its JSON stops parsing."""
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'reply'}: {error['msg']}"
            for error in exc.errors()[:3]
        )
    return f"{exc.msg} at character {exc.pos}"


def drops_temperature(model: str) -> bool:
    """Gemini 3.6+ and 4 ignore temperature and will reject it (Google troubleshooting guide, 2026)."""
    match = MODEL_VERSION.search(model)
    return bool(match) and (int(match.group(1)), int(match.group(2) or 0)) >= (3, 6)


HTML_TITLE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def error_message(body: Any, fallback: str) -> str:
    if body is None and fallback.lstrip().startswith("<"):
        title = HTML_TITLE.search(fallback)
        fallback = f"HTML page: {title.group(1).strip()}" if title else "HTML page"
    if isinstance(body, dict):
        error = body.get("error")
        message = error.get("message") if isinstance(error, dict) else error
        detail = body.get("detail")
        text = " ".join(str(x) for x in (message, detail) if x)
    else:
        text = fallback
    return " ".join((text or fallback).split())[:ERROR_BODY_LIMIT]


class OpenAICompatAdapter:
    style = ApiStyle.OPENAI
    models_path = "/models"

    def headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def path(self, model: str, stream: bool) -> str:
        return "/chat/completions"

    def retryable(self, status: int, body: Any) -> bool:
        return status in RETRYABLE_STATUS

    def _content(self, parts, caps: Capabilities, req: GenerateRequest) -> str | list:
        if all(isinstance(p, Text) for p in parts):
            return "".join(p.text for p in parts)
        content: list[dict[str, Any]] = []
        for part in parts:
            if isinstance(part, Text):
                content.append({"type": "text", "text": part.text})
            elif isinstance(part, Image):
                _require(caps, Capability.IMAGE_INPUT)
                image_url: dict[str, Any] = {"url": data_uri(part.mime_type, part.data)}
                resolution = part.media_resolution or req.media_resolution
                if resolution and caps.has(Capability.MEDIA_RESOLUTION):
                    image_url["detail"] = resolution
                content.append({"type": "image_url", "image_url": image_url})
            else:
                _require(caps, Capability.PDF_INPUT)
                file = {"filename": part.filename, "file_data": data_uri("application/pdf", part.data)}
                content.append({"type": "file", "file": file})
        return content

    def build(self, req: GenerateRequest, caps: Capabilities, stream: bool) -> dict[str, Any]:
        if req.google_search:
            raise CapabilityUnavailable(Capability.GOOGLE_SEARCH)
        if req.safety_settings:
            raise GeminiError("safety_settings need the manastu or gemini API style")
        messages = list(req.messages)
        body: dict[str, Any] = {"model": req.model}
        if req.schema is not None:
            if caps.has(Capability.STRUCTURED_OUTPUT):
                name, schema = json_schema(req.schema)
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": name, "schema": schema},
                }
            else:
                messages.insert(0, schema_instruction(req.schema))
        wire = []
        for m in messages:
            item: dict[str, Any] = {"role": m.role, "content": self._content(m.parts, caps, req)}
            if m.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in m.tool_calls
                ]
            if m.tool_call_id:
                item["tool_call_id"] = m.tool_call_id
            wire.append(item)
        body["messages"] = wire
        if req.tools:
            _require(caps, Capability.FUNCTION_CALLING)
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in req.tools
            ]
            if req.tool_choice:
                body["tool_choice"] = req.tool_choice
        if req.thinking and caps.has(Capability.THINKING_LEVEL):
            body["reasoning_effort"] = str(req.thinking)
        google: dict[str, Any] = {}
        if req.include_thoughts and caps.has(Capability.INCLUDE_THOUGHTS):
            google["thinking_config"] = {"include_thoughts": True}
        if req.cached_content and caps.has(Capability.CONTEXT_CACHE):
            google["cached_content"] = req.cached_content
        if google:
            body["extra_body"] = {"google": google}
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.max_output_tokens is not None:
            body["max_tokens"] = req.max_output_tokens
        if stream:
            body["stream"] = True
            if caps.has(Capability.STREAM_USAGE):
                body["stream_options"] = {"include_usage": True}
        return body

    @staticmethod
    def _usage(raw: dict[str, Any] | None) -> Usage | None:
        if not raw:
            return None
        return Usage(
            input_tokens=int(raw.get("prompt_tokens") or 0),
            output_tokens=int(raw.get("completion_tokens") or 0),
            cached_tokens=int((raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            thinking_tokens=int((raw.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
        )

    @staticmethod
    def _tool_calls(raw: list[dict[str, Any]] | None) -> tuple[ToolCall, ...]:
        calls = []
        for item in raw or []:
            function = item.get("function") or {}
            arguments = function.get("arguments") or "{}"
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            except json.JSONDecodeError as exc:
                raise GeminiError(
                    f"tool call '{function.get('name')}' returned arguments that are not JSON"
                ) from exc
            calls.append(
                ToolCall(id=str(item.get("id") or ""), name=str(function.get("name") or ""), arguments=args)
            )
        return tuple(calls)

    def parse(self, payload: dict[str, Any]) -> Parsed:
        choices = payload.get("choices") or []
        if not choices:
            raise GeminiError("gateway response has no choices")
        message = choices[0].get("message") or {}
        raw_text = _text_of(message.get("content"))
        found = THOUGHT_TAG.findall(raw_text)
        reasoning = message.get("reasoning_content")
        thoughts = "\n".join([*([reasoning] if reasoning else []), *found]) or None
        return Parsed(
            text=THOUGHT_TAG.sub("", raw_text).strip() if found else raw_text,
            tool_calls=self._tool_calls(message.get("tool_calls")),
            usage=self._usage(payload.get("usage")),
            finish_reason=choices[0].get("finish_reason"),
            request_id=payload.get("id"),
            model=payload.get("model"),
            thoughts=thoughts,
        )

    def chunk(self, data: dict[str, Any], state: StreamState) -> str:
        state.request_id = data.get("id") or state.request_id
        state.model = data.get("model") or state.model
        state.usage = self._usage(data.get("usage")) or state.usage
        delta_text = ""
        for choice in data.get("choices") or []:
            state.finish_reason = choice.get("finish_reason") or state.finish_reason
            delta = choice.get("delta") or {}
            delta_text += _text_of(delta.get("content"))
            for frag in delta.get("tool_calls") or []:
                slot = state.tool_fragments.setdefault(
                    frag.get("index", 0), {"id": "", "function": {"name": "", "arguments": ""}}
                )
                slot["id"] = frag.get("id") or slot["id"]
                function = frag.get("function") or {}
                slot["function"]["name"] += function.get("name") or ""
                slot["function"]["arguments"] += function.get("arguments") or ""
        state.text.append(delta_text)
        return delta_text

    def finish_stream(self, state: StreamState) -> tuple[ToolCall, ...]:
        return self._tool_calls([state.tool_fragments[i] for i in sorted(state.tool_fragments)])


class ManastuGatewayAdapter:
    style = ApiStyle.MANASTU
    models_path = "/models"

    def headers(self, key: str) -> dict[str, str]:
        return {"X-API-Key": key}

    def path(self, model: str, stream: bool) -> str:
        return "/stream" if stream else "/generate"

    def retryable(self, status: int, body: Any) -> bool:
        if status == 502 and isinstance(body, dict):
            upstream = UPSTREAM_CODE.search(str(body.get("detail") or ""))
            if upstream:
                return int(upstream.group(1)) in RETRYABLE_UPSTREAM
        return status in RETRYABLE_STATUS

    def _part(self, part, caps: Capabilities, req: GenerateRequest) -> dict[str, Any]:
        if isinstance(part, Text):
            return {"text": part.text}
        if isinstance(part, Image):
            _require(caps, Capability.IMAGE_INPUT)
            wire: dict[str, Any] = {"inline_data": {"mime_type": part.mime_type, "data": b64(part.data)}}
        else:
            _require(caps, Capability.PDF_INPUT)
            wire = {"inline_data": {"mime_type": "application/pdf", "data": b64(part.data)}}
        resolution = part.media_resolution or req.media_resolution
        if resolution and caps.has(Capability.MEDIA_RESOLUTION):
            wire["media_resolution"] = {"level": f"media_resolution_{resolution}"}
        return wire

    def _content(self, m: Message, caps: Capabilities, req: GenerateRequest) -> dict[str, Any]:
        if m.role == "tool":
            if not m.tool_name:
                raise GeminiError(
                    "Gemini function responses need the function name: Message.tool_result(..., name=)"
                )
            text = "".join(p.text for p in m.parts if isinstance(p, Text))
            try:
                response = json.loads(text)
            except json.JSONDecodeError:
                response = None
            response = response if isinstance(response, dict) else {"result": text}
            fr: dict[str, Any] = {"name": m.tool_name, "response": response}
            if m.tool_call_id:
                fr["id"] = m.tool_call_id
            return {"role": "user", "parts": [{"function_response": fr}]}
        parts = [self._part(p, caps, req) for p in m.parts]
        for call in m.tool_calls:
            fc: dict[str, Any] = {"name": call.name, "args": call.arguments}
            if call.id:
                fc["id"] = call.id
            part: dict[str, Any] = {"function_call": fc}
            if call.thought_signature:
                part["thought_signature"] = call.thought_signature
            parts.append(part)
        return {"role": "model" if m.role == "assistant" else "user", "parts": parts}

    def gemini_body(self, req: GenerateRequest, caps: Capabilities) -> tuple[list, dict[str, Any]]:
        messages = list(req.messages)
        config: dict[str, Any] = {}
        if req.schema is not None:
            if caps.has(Capability.STRUCTURED_OUTPUT):
                config["response_mime_type"] = "application/json"
                config["response_json_schema"] = json_schema(req.schema)[1]
            else:
                messages.insert(0, schema_instruction(req.schema))
        system = [p.text for m in messages if m.role == "system" for p in m.parts if isinstance(p, Text)]
        if system:
            config["system_instruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        contents = [self._content(m, caps, req) for m in messages if m.role != "system"]
        tools: list[dict[str, Any]] = []
        if req.tools:
            _require(caps, Capability.FUNCTION_CALLING)
            declarations = [
                {"name": t.name, "description": t.description, "parameters": t.parameters} for t in req.tools
            ]
            tools.append({"function_declarations": declarations})
            if req.tool_choice:
                config["tool_config"] = {"function_calling_config": {"mode": CALLING_MODE[req.tool_choice]}}
        if req.google_search:
            _require(caps, Capability.GOOGLE_SEARCH)
            tools.append({"google_search": {}})
        if tools:
            config["tools"] = tools
        thinking: dict[str, Any] = {}
        if req.thinking and caps.has(Capability.THINKING_LEVEL):
            thinking["thinking_level"] = str(req.thinking)
        if req.include_thoughts and caps.has(Capability.INCLUDE_THOUGHTS):
            thinking["include_thoughts"] = True
        if thinking:
            config["thinking_config"] = thinking
        if req.temperature is not None and not drops_temperature(req.model):
            config["temperature"] = req.temperature
        if req.max_output_tokens is not None:
            config["max_output_tokens"] = req.max_output_tokens
        if req.cached_content and caps.has(Capability.CONTEXT_CACHE):
            config["cached_content"] = req.cached_content
        if req.safety_settings:
            config["safety_settings"] = [
                {"category": str(s.category), "threshold": str(s.threshold)} for s in req.safety_settings
            ]
        return contents, config

    def build(self, req: GenerateRequest, caps: Capabilities, stream: bool) -> dict[str, Any]:
        contents, config = self.gemini_body(req, caps)
        body: dict[str, Any] = {"model": req.model, "contents": contents}
        if config:
            body["config"] = config
        return body

    @staticmethod
    def _usage(raw: dict[str, Any] | None) -> Usage | None:
        if not raw:
            return None
        thoughts = int(raw.get("thoughts_token_count") or 0)
        return Usage(
            input_tokens=int(raw.get("prompt_token_count") or 0),
            output_tokens=int(raw.get("candidates_token_count") or 0) + thoughts,
            cached_tokens=int(raw.get("cached_content_token_count") or 0),
            thinking_tokens=thoughts,
        )

    @staticmethod
    def _parts(candidate: dict[str, Any]) -> tuple[str, str | None, tuple[ToolCall, ...]]:
        text, thoughts, calls = [], [], []
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("function_call"):
                fc = part["function_call"]
                calls.append(
                    ToolCall(
                        id=str(fc.get("id") or ""),
                        name=str(fc.get("name") or ""),
                        arguments=dict(fc.get("args") or {}),
                        thought_signature=part.get("thought_signature"),
                    )
                )
            elif part.get("text") is not None:
                (thoughts if part.get("thought") else text).append(part["text"])
        return "".join(text), "\n".join(thoughts) or None, tuple(calls)

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    def parse(self, payload: dict[str, Any]) -> Parsed:
        payload = self.normalize(payload)
        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("prompt_feedback") or {}).get("block_reason")
            raise GeminiError(f"no candidates returned (block_reason={reason})")
        text, thoughts, calls = self._parts(candidates[0])
        return Parsed(
            text=text,
            tool_calls=calls,
            usage=self._usage(payload.get("usage_metadata")),
            finish_reason=candidates[0].get("finish_reason"),
            request_id=payload.get("response_id"),
            model=payload.get("model_version"),
            thoughts=thoughts,
            structured=payload.get("parsed"),
            quota=payload.get("quota"),
            grounding=self._grounding(candidates[0].get("grounding_metadata")),
        )

    @staticmethod
    def _grounding(raw: dict[str, Any] | None) -> Grounding | None:
        if not raw:
            return None
        sources = tuple(
            GroundingSource(
                title=(chunk.get("web") or {}).get("title"), uri=(chunk.get("web") or {}).get("uri")
            )
            for chunk in raw.get("grounding_chunks") or []
        )
        return Grounding(queries=tuple(raw.get("web_search_queries") or ()), sources=sources)

    def chunk(self, data: dict[str, Any], state: StreamState) -> str:
        data = self.normalize(data)
        if data.get("done"):
            state.done = True
            state.quota = data.get("quota") or state.quota
            total = (data.get("usage") or {}).get("total")
            if total is not None and state.usage is None:
                state.usage = Usage(output_tokens=int(total), estimated=True)
            return ""
        state.request_id = data.get("response_id") or state.request_id
        state.model = data.get("model_version") or state.model
        state.usage = self._usage(data.get("usage_metadata")) or state.usage
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        state.finish_reason = candidates[0].get("finish_reason") or state.finish_reason
        text, _, calls = self._parts(candidates[0])
        state.tool_calls.extend(calls)
        state.text.append(text)
        return text

    def finish_stream(self, state: StreamState) -> tuple[ToolCall, ...]:
        return tuple(state.tool_calls)


OPAQUE_KEYS = frozenset({"response_json_schema", "parameters", "args", "response", "parsed"})
GENERATION_CONFIG_TOP_LEVEL = (
    "system_instruction",
    "tools",
    "tool_config",
    "cached_content",
    "safety_settings",
)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def rekey(value: Any, convert, opaque=OPAQUE_KEYS) -> Any:
    if isinstance(value, list):
        return [rekey(v, convert, opaque) for v in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            new_key = convert(key)
            plain = key in opaque or _snake(key) in opaque
            out[new_key] = item if plain else rekey(item, convert, opaque)
        return out
    return value


class GeminiNativeAdapter(ManastuGatewayAdapter):
    style = ApiStyle.GEMINI
    models_path = "/v1beta/models"

    def headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def path(self, model: str, stream: bool) -> str:
        return (
            f"/v1beta/models/{model}:streamGenerateContent?alt=sse"
            if stream
            else f"/v1beta/models/{model}:generateContent"
        )

    def retryable(self, status: int, body: Any) -> bool:
        return status in RETRYABLE_STATUS

    def build(self, req: GenerateRequest, caps: Capabilities, stream: bool) -> dict[str, Any]:
        contents, config = self.gemini_body(req, caps)
        body: dict[str, Any] = {"contents": contents}
        for key in GENERATION_CONFIG_TOP_LEVEL:
            if key in config:
                body[key] = config.pop(key)
        if config:
            body["generation_config"] = config
        body = rekey(body, _camel)
        for content in body["contents"]:
            for part in content["parts"]:
                if "mediaResolution" in part:
                    part["mediaResolution"]["level"] = part["mediaResolution"]["level"].upper()
        return body

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return rekey(payload, _snake)


ADAPTERS = {
    ApiStyle.MANASTU: ManastuGatewayAdapter(),
    ApiStyle.GEMINI: GeminiNativeAdapter(),
    ApiStyle.OPENAI: OpenAICompatAdapter(),
}
Adapter = ManastuGatewayAdapter | GeminiNativeAdapter | OpenAICompatAdapter


def _require(caps: Capabilities, capability: Capability) -> None:
    if not caps.has(capability):
        raise CapabilityUnavailable(capability)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if isinstance(item, dict))
    return ""
