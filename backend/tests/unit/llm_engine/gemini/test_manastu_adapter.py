"""Client against responses recorded from the real Manastu gateway, 2026-10-22 (ids, signatures redacted)."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from backend import config
from backend.config import Settings, ThinkingLevel
from backend.llm_engine.gemini_adapters import ADAPTERS, GeminiNativeAdapter, drops_temperature
from backend.llm_engine.gemini_client import CircuitBreaker, GeminiClient
from backend.llm_engine.gemini_types import (
    BudgetExhausted,
    CallContext,
    Capabilities,
    Capability,
    GatewayError,
    GatewayUnavailable,
    GenerateRequest,
    Image,
    Message,
    Pdf,
    RequestTooLarge,
    StreamDone,
    TextDelta,
    ToolCall,
    ToolSpec,
)

RECORDED = Path(__file__).parent / "responses" / "manastu"
KEY = "manastu-key-$with&shell*chars"
URL = "https://gateway.manastu.test"
MODEL = "gemini-3.8-flash"
CTX = CallContext(purpose="unit_test", trace_id="t-1")
TOOL = ToolSpec(
    "get_run_peak",
    "Peak chamber pressure of a test run.",
    {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]},
)


class Answer(BaseModel):
    city: str
    population_millions: float


def recorded(name: str) -> httpx.Response:
    data = json.loads((RECORDED / f"{name}.json").read_text())
    return httpx.Response(data["status"], json=data["body"])


def sse() -> httpx.Response:
    return httpx.Response(
        200, text=(RECORDED / "stream.sse").read_text(), headers={"content-type": "text/event-stream"}
    )


class Gateway:
    def __init__(self, *responses):
        self.queue, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def bodies(self):
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture(autouse=True)
def no_google_key(monkeypatch):
    for name in config.FORBIDDEN_NAMES:
        monkeypatch.delenv(name, raising=False)


def client(gateway, records=None, caps=None, style="manastu", **kwargs) -> GeminiClient:
    settings = Settings(
        _env_file=None,
        GEMINI_BACKEND="gateway",
        GEMINI_GATEWAY_URL=URL,
        GEMINI_GATEWAY_KEY=KEY,
        GEMINI_API_STYLE=style,
        **kwargs.pop("settings", {}),
    )
    return GeminiClient(
        settings,
        capabilities=caps or Capabilities.all(),
        ledger=records.append if records is not None else None,
        transport=httpx.MockTransport(gateway),
        sleep=lambda _: None,
        **kwargs,
    )


async def test_plain_call_wire_shape_and_recorded_result():
    records = []
    gw = Gateway(recorded("plain"))
    result = await client(gw, records).generate(
        model=MODEL,
        messages=[Message.user("Reply with the single word OK.")],
        context=CTX,
        thinking=ThinkingLevel.LOW,
    )
    request = gw.requests[0]
    assert str(request.url) == f"{URL}/generate"
    assert request.headers["x-api-key"] == KEY
    assert "authorization" not in request.headers
    assert request.headers["idempotency-key"]
    assert gw.bodies[0] == {
        "model": MODEL,
        "contents": [{"role": "user", "parts": [{"text": "Reply with the single word OK."}]}],
        "config": {"thinking_config": {"thinking_level": "low"}},
    }
    assert result.text.strip() == "OK"
    assert result.request_id == "resp-fixture"
    assert result.model == "gemini-3.8-flash"
    assert result.usage.input_tokens > 0 and not result.usage.estimated
    assert result.quota == {"limit": 1000000, "remaining": 990000, "used_today": 10000}
    assert records[0].request_id == "resp-fixture" and records[0].usage_estimated is False


async def test_structured_output_uses_response_json_schema_and_gateway_parsed():
    gw = Gateway(recorded("structured"))
    result = await client(gw).generate(model=MODEL, messages=[Message.user("q")], context=CTX, schema=Answer)
    config_sent = gw.bodies[0]["config"]
    assert config_sent["response_mime_type"] == "application/json"
    assert config_sent["response_json_schema"]["required"] == ["city", "population_millions"]
    assert result.parsed.city == "Tokyo"


async def test_tool_call_round_trip_echoes_thought_signature_and_names_the_function():
    gw = Gateway(recorded("tool_call"), recorded("tool_result_answer"))
    c = client(gw)
    first = await c.generate(
        model=MODEL, messages=[Message.user("peak?")], context=CTX, tools=[TOOL], tool_choice="required"
    )
    [call] = first.tool_calls
    assert (call.name, call.arguments, call.thought_signature) == (
        "get_run_peak",
        {"run_id": "HT-042"},
        "sig-redacted",
    )
    assert gw.bodies[0]["config"]["tool_config"] == {"function_calling_config": {"mode": "ANY"}}
    assert gw.bodies[0]["config"]["tools"][0]["function_declarations"][0]["name"] == "get_run_peak"
    answer = await c.generate(
        model=MODEL,
        messages=[
            Message.user("peak?"),
            Message.assistant(tool_calls=first.tool_calls),
            Message.tool_result(call.id, '{"peak_bar": 31.2}', name=call.name),
        ],
        context=CTX,
        tools=[TOOL],
    )
    sent = gw.bodies[1]["contents"]
    assert sent[1] == {
        "role": "model",
        "parts": [
            {
                "function_call": {"name": "get_run_peak", "args": {"run_id": "HT-042"}, "id": call.id},
                "thought_signature": "sig-redacted",
            }
        ],
    }
    assert sent[2]["parts"][0]["function_response"] == {
        "name": "get_run_peak",
        "response": {"peak_bar": 31.2},
        "id": call.id,
    }
    assert "31.2" in answer.text


async def test_tool_result_without_function_name_is_refused():
    with pytest.raises(Exception, match="function name"):
        await client(Gateway(recorded("plain"))).generate(
            model=MODEL,
            messages=[Message.user("q"), Message.tool_result("c1", "x")],
            context=CTX,
        )


async def test_thoughts_are_split_from_the_answer_and_counted_as_output():
    result = await client(Gateway(recorded("thoughts"))).generate(
        model=MODEL,
        messages=[Message.user("q")],
        context=CTX,
        thinking=ThinkingLevel.HIGH,
        include_thoughts=True,
    )
    assert result.text == "Yes"
    assert result.thoughts.startswith("**My Thought Process")
    assert result.usage.thinking_tokens > 1000
    assert result.usage.output_tokens > result.usage.thinking_tokens


async def test_images_and_pdfs_are_inline_data_with_per_part_media_resolution():
    gw = Gateway(recorded("image_low"))
    msg = Message.user("read", Image(b"png", media_resolution="low"), Pdf(b"%PDF", media_resolution="medium"))
    await client(gw).generate(model=MODEL, messages=[msg], context=CTX, media_resolution="high")
    parts = gw.bodies[0]["contents"][0]["parts"]
    assert parts[1] == {
        "inline_data": {"mime_type": "image/png", "data": "cG5n"},
        "media_resolution": {"level": "media_resolution_low"},
    }
    assert parts[2] == {
        "inline_data": {"mime_type": "application/pdf", "data": "JVBERg=="},
        "media_resolution": {"level": "media_resolution_medium"},
    }


async def test_system_messages_become_system_instruction():
    gw = Gateway(recorded("plain"))
    await client(gw).generate(
        model=MODEL, messages=[Message.system("Be terse."), Message.user("q")], context=CTX
    )
    assert gw.bodies[0]["config"]["system_instruction"] == {"parts": [{"text": "Be terse."}]}
    assert [c["role"] for c in gw.bodies[0]["contents"]] == ["user"]


async def test_temperature_is_not_sent_to_gemini_3_6_and_later():
    gw = Gateway(recorded("plain"))
    c = client(gw)
    await c.generate(model="gemini-3.8-flash", messages=[Message.user("q")], context=CTX, temperature=0.0)
    await c.generate(model="gemini-2.5-flash", messages=[Message.user("q")], context=CTX, temperature=0.0)
    assert "temperature" not in gw.bodies[0].get("config", {})
    assert gw.bodies[1]["config"]["temperature"] == 0.0
    assert drops_temperature("gemini-4-argon") and not drops_temperature("gemini-3.5-flash")


async def test_upstream_client_error_inside_502_is_not_retried():
    records = []
    gw = Gateway(recorded("upstream_400"))
    with pytest.raises(GatewayError) as exc:
        await client(gw, records).generate(
            model=MODEL, messages=[Message.user("x")], context=CTX, thinking="minimal"
        )
    assert exc.value.status_code == 502 and exc.value.retryable is False
    assert "Thinking level is unsupported" in str(exc.value)
    assert len(gw.requests) == 1 and records[0].status == "error"


async def test_upstream_unavailable_inside_502_is_retried():
    unavailable = httpx.Response(
        502, json={"error": "upstream Gemini error", "detail": "ServerError: 503 UNAVAILABLE. overloaded"}
    )
    gw = Gateway(unavailable, recorded("plain"))
    result = await client(gw).generate(model=MODEL, messages=[Message.user("x")], context=CTX)
    assert result.text.strip() == "OK" and len(gw.requests) == 2


async def test_forbidden_model_and_rejected_key_are_reported_distinctly():
    with pytest.raises(GatewayError, match="not permitted for this key") as exc:
        await client(Gateway(recorded("model_forbidden"))).generate(
            model="no-such-model", messages=[Message.user("x")], context=CTX
        )
    assert exc.value.retryable is False
    rejected = httpx.Response(401, json={"error": "invalid or missing X-API-Key"})
    with pytest.raises(GatewayError, match="key rejected"):
        await client(Gateway(rejected)).generate(model=MODEL, messages=[Message.user("x")], context=CTX)


async def test_idempotency_key_is_stable_across_retries_and_unique_per_call():
    gw = Gateway(httpx.Response(503), recorded("plain"))
    c = client(gw)
    await c.generate(model=MODEL, messages=[Message.user("x")], context=CTX)
    await c.generate(model=MODEL, messages=[Message.user("x")], context=CTX)
    keys = [r.headers["idempotency-key"] for r in gw.requests]
    assert keys[0] == keys[1] and keys[1] != keys[2]


async def test_circuit_breaker_opens_fails_fast_and_recovers():
    now = [0.0]
    breaker = CircuitBreaker(threshold=2, reset_after_s=30, clock=lambda: now[0])
    gw = Gateway(httpx.Response(503))
    c = client(gw, breaker=breaker, max_attempts=5)
    with pytest.raises(GatewayError):
        await c.generate(model=MODEL, messages=[Message.user("x")], context=CTX)
    assert len(gw.requests) == 2 and breaker.is_open
    with pytest.raises(GatewayUnavailable):
        await c.generate(model=MODEL, messages=[Message.user("x")], context=CTX)
    assert len(gw.requests) == 2
    now[0] = 31.0
    gw.queue = [recorded("plain")]
    assert (await c.generate(model=MODEL, messages=[Message.user("x")], context=CTX)).text.strip() == "OK"
    assert not breaker.is_open


def test_inline_media_above_20_mb_is_refused_before_sending():
    gw = Gateway(recorded("plain"))
    with pytest.raises(RequestTooLarge):
        client(gw).generate_sync(
            model=MODEL, messages=[Message.user("x", Pdf(b"0" * (20 * 1024 * 1024 + 1)))], context=CTX
        )
    assert gw.requests == []


async def test_gateway_quota_exhaustion_stops_new_calls():
    spent = json.loads((RECORDED / "plain.json").read_text())["body"]
    spent["quota"] = {"limit": 10, "remaining": 0, "used_today": 10}
    gw = Gateway(httpx.Response(200, json=spent))
    c = client(gw)
    await c.generate(model=MODEL, messages=[Message.user("x")], context=CTX)
    with pytest.raises(BudgetExhausted, match="quota"):
        await c.generate(model=MODEL, messages=[Message.user("x")], context=CTX)
    assert len(gw.requests) == 1


async def test_recorded_stream_yields_deltas_and_estimated_usage_from_the_total():
    records = []
    gw = Gateway(sse())
    events = [
        e
        async for e in client(gw, records).stream(model=MODEL, messages=[Message.user("count")], context=CTX)
    ]
    assert str(gw.requests[0].url) == f"{URL}/stream"
    deltas = [e.text for e in events if isinstance(e, TextDelta)]
    assert "".join(deltas) == "1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12"
    done = events[-1]
    assert isinstance(done, StreamDone)
    assert done.result.finish_reason == "STOP"
    assert done.result.usage.estimated is True
    assert done.result.usage.total_tokens >= 49 - 1
    assert done.result.quota["remaining"] == 990000
    assert records[0].usage_estimated is True


def test_sync_generate_against_recorded_response():
    assert (
        client(Gateway(recorded("plain")))
        .generate_sync(model=MODEL, messages=[Message.user("x")], context=CTX)
        .text.strip()
        == "OK"
    )


def test_default_style_is_manastu():
    settings = Settings(
        _env_file=None, GEMINI_BACKEND="gateway", GEMINI_GATEWAY_URL=URL, GEMINI_GATEWAY_KEY=KEY
    )
    c = GeminiClient(settings, capabilities=Capabilities())
    assert c.adapter is ADAPTERS["manastu"]


def native_request(**kwargs) -> GenerateRequest:
    return GenerateRequest(
        model=MODEL,
        messages=(Message.system("sys"), Message.user("hi", Image(b"x", media_resolution="high"))),
        **kwargs,
    )


def test_native_adapter_camelcases_keys_but_not_user_schemas():
    body = GeminiNativeAdapter().build(
        native_request(
            schema={"title": "t", "properties": {"snake_case_field": {}}}, thinking="low", tools=(TOOL,)
        ),
        Capabilities.all(),
        False,
    )
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert body["generationConfig"]["responseJsonSchema"]["properties"] == {"snake_case_field": {}}
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert body["tools"][0]["functionDeclarations"][0]["parameters"]["required"] == ["run_id"]
    part = body["contents"][0]["parts"][1]
    assert part["inlineData"]["mimeType"] == "image/png"
    assert part["mediaResolution"] == {"level": "MEDIA_RESOLUTION_HIGH"}
    assert GeminiNativeAdapter().path(MODEL, True) == f"/v1beta/models/{MODEL}:streamGenerateContent?alt=sse"


def test_native_adapter_parses_camelcase_responses():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"functionCall": {"name": "f", "args": {"snake_key": 1}}, "thoughtSignature": "s"}
                    ]
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2, "thoughtsTokenCount": 3},
        "responseId": "r1",
        "modelVersion": "gemini-3.8-flash",
    }
    parsed = GeminiNativeAdapter().parse(payload)
    assert parsed.tool_calls == (
        ToolCall(id="", name="f", arguments={"snake_key": 1}, thought_signature="s"),
    )
    assert (parsed.usage.input_tokens, parsed.usage.output_tokens, parsed.usage.thinking_tokens) == (5, 5, 3)
    assert parsed.request_id == "r1"


@pytest.mark.parametrize("capability", [Capability.IMAGE_INPUT, Capability.FUNCTION_CALLING])
def test_disabled_capabilities_raise_before_sending(capability):
    gw = Gateway(recorded("plain"))
    caps = Capabilities(enabled=frozenset(Capability) - {capability})
    with pytest.raises(Exception, match=str(capability)):
        client(gw, caps=caps).generate_sync(
            model=MODEL, messages=[Message.user("x", Image(b"x"))], context=CTX, tools=[TOOL]
        )
    assert gw.requests == []
