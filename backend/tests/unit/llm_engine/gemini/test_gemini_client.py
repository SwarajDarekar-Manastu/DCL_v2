import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from backend import config
from backend.config import ConfigError, Settings, ThinkingLevel
from backend.llm_engine import gemini_client as gc
from backend.llm_engine.gemini_client import GeminiClient, backoff_delay
from backend.llm_engine.gemini_types import (
    BudgetExhausted,
    CallContext,
    Capabilities,
    Capability,
    CapabilityUnavailable,
    DailyTokenBudget,
    GatewayError,
    Image,
    Message,
    ModelPrice,
    Pdf,
    StreamDone,
    StructuredOutputError,
    TextDelta,
    ToolSpec,
)

RESPONSES = Path(__file__).parent / "responses"
KEY = "gw-key-never-in-logs-0123456789"
URL = "https://gateway.manastu.test/v1"
MODEL = "gemini-3.8-flash"
CTX = CallContext(purpose="unit_test", prompt_version="t1", doc_id="doc-1", trace_id="trace-1")


class Answer(BaseModel):
    city: str
    population_millions: float


TOOL = ToolSpec(
    "get_run_peak", "Peak chamber pressure", {"type": "object", "properties": {"run_id": {"type": "string"}}}
)


def fixture(name: str) -> dict:
    return json.loads((RESPONSES / name).read_text())


def make_settings(drop: tuple[str, ...] = (), **overrides) -> Settings:
    values = {
        "GEMINI_BACKEND": "gateway",
        "GEMINI_GATEWAY_URL": URL,
        "GEMINI_GATEWAY_KEY": KEY,
        "GEMINI_API_STYLE": "openai",
        **overrides,
    }
    return Settings(_env_file=None, **{k: v for k, v in values.items() if k not in drop})


class Gateway:
    """Mock gateway: records every request and replays queued responses."""

    def __init__(self, *responses: httpx.Response):
        self.queue = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.queue[0], Exception):
            raise self.queue.pop(0)
        return self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def ok(name: str = "plain.json", **headers) -> httpx.Response:
    return httpx.Response(200, json=fixture(name), headers=headers)


def sse(name: str) -> httpx.Response:
    return httpx.Response(
        200, text=(RESPONSES / name).read_text(), headers={"content-type": "text/event-stream"}
    )


@pytest.fixture(autouse=True)
def no_google_key(monkeypatch):
    for name in config.FORBIDDEN_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def records():
    return []


def client_for(gateway, records=None, caps=None, sleeps=None, **kwargs) -> GeminiClient:
    return GeminiClient(
        make_settings(**kwargs.pop("settings", {})),
        capabilities=caps if caps is not None else Capabilities.all(),
        ledger=records.append if records is not None else None,
        transport=httpx.MockTransport(gateway),
        sleep=(sleeps.append if sleeps is not None else (lambda _: None)),
        **kwargs,
    )


async def test_plain_call_shape_result_and_ledger(records):
    gateway = Gateway(ok())
    client = client_for(gateway, records)
    result = await client.generate(model=MODEL, messages=[Message.user("Reply OK")], context=CTX)

    request = gateway.requests[0]
    assert str(request.url) == f"{URL}/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert gateway.bodies[0] == {"model": MODEL, "messages": [{"role": "user", "content": "Reply OK"}]}
    assert result.text == "OK"
    assert result.request_id == "chatcmpl-plain-1"
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cached_tokens) == (
        120,
        30,
        20,
    )
    assert result.usage.thinking_tokens == 12
    [record] = records
    assert (record.status, record.purpose, record.doc_id, record.trace_id) == (
        "ok",
        "unit_test",
        "doc-1",
        "trace-1",
    )
    assert (record.input_tokens, record.output_tokens, record.cached_tokens) == (120, 30, 20)
    assert record.request_id == "chatcmpl-plain-1"
    assert record.cost_estimate is None
    assert KEY not in repr(client)


def test_sync_call_works(records):
    result = client_for(Gateway(ok()), records).generate_sync(
        model=MODEL, messages=[Message.user("x")], context=CTX
    )
    assert result.text == "OK"
    assert len(records) == 1


def test_refuses_to_start_with_google_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        GeminiClient(make_settings(), capabilities=Capabilities())


@pytest.mark.parametrize("dropped", ["GEMINI_BACKEND", "GEMINI_GATEWAY_URL", "GEMINI_GATEWAY_KEY"])
def test_refuses_to_start_without_gemini_settings(dropped):
    settings = make_settings(drop=(dropped,))
    with pytest.raises(ConfigError, match=dropped):
        GeminiClient(settings, capabilities=Capabilities())


async def test_structured_output_uses_json_schema_when_supported():
    gateway = Gateway(ok("structured.json"))
    result = await client_for(gateway).generate(
        model=MODEL, messages=[Message.user("q")], context=CTX, schema=Answer
    )
    assert gateway.bodies[0]["response_format"]["type"] == "json_schema"
    assert gateway.bodies[0]["response_format"]["json_schema"]["name"] == "Answer"
    assert result.parsed == Answer(city="Tokyo", population_millions=37.1)


async def test_structured_output_falls_back_to_schema_in_prompt_when_disabled():
    gateway = Gateway(ok("structured_fenced.json"))
    client = client_for(gateway, caps=Capabilities())
    result = await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX, schema=Answer)
    body = gateway.bodies[0]
    assert "response_format" not in body
    assert body["messages"][0]["role"] == "system"
    assert '"population_millions"' in body["messages"][0]["content"]
    assert result.parsed == Answer(city="Tokyo", population_millions=37.1)


async def test_dict_schema_returns_plain_json():
    gateway = Gateway(ok("structured.json"))
    schema = {"title": "answer", "type": "object"}
    result = await client_for(gateway).generate(
        model=MODEL, messages=[Message.user("q")], context=CTX, schema=schema
    )
    assert result.parsed == {"city": "Tokyo", "population_millions": 37.1}


async def test_schema_mismatch_raises_and_is_logged_as_error(records):
    client = client_for(Gateway(ok("structured_invalid.json")), records)
    with pytest.raises(StructuredOutputError) as exc:
        await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX, schema=Answer)
    assert exc.value.raw_text == '{"city": "Tokyo"}'
    assert [r.status for r in records] == ["error"]
    assert records[0].input_tokens == 120


async def test_function_calling_round_trip():
    gateway = Gateway(ok("tool_call.json"), ok())
    client = client_for(gateway)
    first = await client.generate(
        model=MODEL, messages=[Message.user("peak?")], context=CTX, tools=[TOOL], tool_choice="required"
    )
    assert gateway.bodies[0]["tools"][0]["function"]["name"] == "get_run_peak"
    assert gateway.bodies[0]["tool_choice"] == "required"
    [call] = first.tool_calls
    assert (call.id, call.name, call.arguments) == ("call_1", "get_run_peak", {"run_id": "HT-042"})
    await client.generate(
        model=MODEL,
        messages=[
            Message.user("peak?"),
            Message.assistant(tool_calls=first.tool_calls),
            Message.tool_result("call_1", "31.2 bar"),
        ],
        context=CTX,
        tools=[TOOL],
    )
    sent = gateway.bodies[1]["messages"]
    assert sent[1]["tool_calls"][0]["function"] == {
        "name": "get_run_peak",
        "arguments": '{"run_id": "HT-042"}',
    }
    assert sent[2] == {"role": "tool", "content": "31.2 bar", "tool_call_id": "call_1"}


@pytest.mark.parametrize(
    ("capability", "kwargs", "parts"),
    [
        (Capability.FUNCTION_CALLING, {"tools": [TOOL]}, ("q",)),
        (Capability.IMAGE_INPUT, {}, ("q", Image(b"\x89PNG"))),
        (Capability.PDF_INPUT, {}, ("q", Pdf(b"%PDF-1.4"))),
    ],
)
async def test_disabled_capabilities_without_fallback_raise_before_any_request(capability, kwargs, parts):
    gateway = Gateway(ok())
    caps = Capabilities(enabled=frozenset(Capability) - {capability})
    with pytest.raises(CapabilityUnavailable) as exc:
        await client_for(gateway, caps=caps).generate(
            model=MODEL, messages=[Message.user(*parts)], context=CTX, **kwargs
        )
    assert exc.value.capability is capability
    assert gateway.requests == []


async def test_image_and_pdf_parts_use_data_uris_and_detail():
    gateway = Gateway(ok())
    message = Message.user("read", Image(b"img", "image/jpeg"), Pdf(b"pdf", "run.pdf"))
    await client_for(gateway).generate(model=MODEL, messages=[message], context=CTX, media_resolution="high")
    content = gateway.bodies[0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "read"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,aW1n", "detail": "high"},
    }
    assert content[2] == {
        "type": "file",
        "file": {"filename": "run.pdf", "file_data": "data:application/pdf;base64,cGRm"},
    }


async def test_thinking_level_default_from_settings_and_per_call_override():
    gateway = Gateway(ok())
    client = client_for(gateway, settings={"GEMINI_THINKING_LEVEL": "low"})
    await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX)
    await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX, thinking=ThinkingLevel.HIGH)
    assert [b["reasoning_effort"] for b in gateway.bodies] == ["low", "high"]


async def test_options_of_disabled_capabilities_are_omitted_as_plain_call_fallback():
    gateway = Gateway(ok())
    client = client_for(gateway, caps=Capabilities(), settings={"GEMINI_THINKING_LEVEL": "high"})
    await client.generate(
        model=MODEL,
        messages=[Message.user("q")],
        context=CTX,
        include_thoughts=True,
        cached_content="cachedContents/abc",
        temperature=0.0,
        max_output_tokens=64,
    )
    assert gateway.bodies[0] == {
        "model": MODEL,
        "messages": [{"role": "user", "content": "q"}],
        "temperature": 0.0,
        "max_tokens": 64,
    }


async def test_thoughts_and_cache_are_sent_when_enabled_and_thoughts_split_from_text():
    gateway = Gateway(ok("thoughts.json"))
    result = await client_for(gateway).generate(
        model=MODEL,
        messages=[Message.user("q")],
        context=CTX,
        include_thoughts=True,
        cached_content="cachedContents/abc",
    )
    assert gateway.bodies[0]["extra_body"] == {
        "google": {"thinking_config": {"include_thoughts": True}, "cached_content": "cachedContents/abc"}
    }
    assert result.text == "yes"
    assert result.thoughts == "1000003 is not divisible by small primes."


async def test_429_honors_retry_after_then_succeeds(records):
    sleeps = []
    gateway = Gateway(
        httpx.Response(429, json={"error": {"message": "quota"}}, headers={"Retry-After": "7"}), ok()
    )
    result = await client_for(gateway, records, sleeps=sleeps).generate(
        model=MODEL, messages=[Message.user("q")], context=CTX
    )
    assert result.text == "OK"
    assert sleeps == [7.0]
    assert len(gateway.requests) == 2
    assert [r.status for r in records] == ["ok"]


async def test_5xx_and_transport_errors_are_retried_with_backoff():
    sleeps = []
    gateway = Gateway(httpx.ConnectError("down"), httpx.Response(503), httpx.Response(502), ok())
    result = await client_for(gateway, sleeps=sleeps).generate(
        model=MODEL, messages=[Message.user("q")], context=CTX
    )
    assert result.text == "OK"
    assert len(sleeps) == 3
    assert all(0 < s <= 60 for s in sleeps)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_client_errors_are_not_retried_and_logged_once(records, status):
    gateway = Gateway(httpx.Response(status, json=fixture("error_400.json")))
    with pytest.raises(GatewayError) as exc:
        await client_for(gateway, records).generate(model=MODEL, messages=[Message.user("q")], context=CTX)
    assert exc.value.status_code == status
    assert exc.value.retryable is False
    assert len(gateway.requests) == 1
    assert [r.status for r in records] == ["error"]
    assert "response_format" in records[0].error


async def test_retries_stop_after_max_attempts(records):
    gateway = Gateway(httpx.Response(503))
    with pytest.raises(GatewayError, match="503"):
        await client_for(gateway, records, max_attempts=3).generate(
            model=MODEL, messages=[Message.user("q")], context=CTX
        )
    assert len(gateway.requests) == 3
    assert len(records) == 1


def test_sync_path_retries_too():
    sleeps = []
    gateway = Gateway(httpx.Response(429, headers={"Retry-After": "2"}), ok())
    result = client_for(gateway, sleeps=sleeps).generate_sync(
        model=MODEL, messages=[Message.user("q")], context=CTX
    )
    assert result.text == "OK"
    assert sleeps == [2.0]


def test_backoff_delay_honors_http_date_and_caps():
    assert backoff_delay(0, "Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
    assert backoff_delay(0, "100000") == gc.MAX_RETRY_AFTER_S
    assert backoff_delay(10, None) <= 60.0
    assert 0.5 <= backoff_delay(0, None) <= 1.0


async def test_budget_cap_stops_new_calls_before_any_request(records):
    gateway = Gateway(ok())
    budget = DailyTokenBudget(limit_tokens=200)
    client = client_for(gateway, records, budget=budget)
    await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX)
    assert budget.used() == 150
    await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX)
    with pytest.raises(BudgetExhausted):
        await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX)
    assert len(gateway.requests) == 2
    assert len(records) == 2


def test_budget_from_external_usage_and_day_rollover():
    assert DailyTokenBudget(limit_tokens=None).check() is None
    external = DailyTokenBudget(limit_tokens=1000, usage_today=lambda: 1000)
    with pytest.raises(BudgetExhausted):
        external.check()
    day = [date(2026, 10, 21)]
    local = DailyTokenBudget(limit_tokens=100, today=lambda: day[0])
    local.record(100)
    with pytest.raises(BudgetExhausted):
        local.check()
    day[0] = date(2026, 10, 22)
    local.check()
    assert local.used() == 0


async def test_cost_estimate_uses_model_price(records):
    prices = {MODEL: ModelPrice(input_per_mtok=1.0, output_per_mtok=4.0, cached_per_mtok=0.25)}
    await client_for(Gateway(ok()), records, prices=prices).generate(
        model=MODEL, messages=[Message.user("q")], context=CTX
    )
    assert records[0].cost_estimate == pytest.approx((100 * 1.0 + 20 * 0.25 + 30 * 4.0) / 1_000_000)


PRICE = ModelPrice(input_per_mtok=1.0, output_per_mtok=4.0, cached_per_mtok=0.25)
OK_COST = (100 * 1.0 + 20 * 0.25 + 30 * 4.0) / 1_000_000


async def test_default_ledger_writes_every_call_priced_from_models_prices(monkeypatch):
    written = []
    stack = gc.StackLedger(read_prices=lambda: {MODEL: PRICE}, write=written.append)
    monkeypatch.setattr(gc.StackLedger, "for_settings", classmethod(lambda cls, settings: stack))
    client = GeminiClient(
        make_settings(), capabilities=Capabilities.all(), transport=httpx.MockTransport(Gateway(ok()))
    )
    await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX)
    [record] = written
    assert (record.purpose, record.status, record.input_tokens, record.output_tokens) == (
        "unit_test",
        "ok",
        120,
        30,
    )
    assert record.cost_estimate == pytest.approx(OK_COST)


async def test_explicit_prices_win_over_the_configured_ones(monkeypatch):
    written = []
    stack = gc.StackLedger(read_prices=lambda: {MODEL: PRICE}, write=written.append)
    monkeypatch.setattr(gc.StackLedger, "for_settings", classmethod(lambda cls, settings: stack))
    client = GeminiClient(
        make_settings(),
        capabilities=Capabilities.all(),
        prices={},
        transport=httpx.MockTransport(Gateway(ok())),
    )
    await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX)
    assert written[0].cost_estimate is None


def test_stack_ledger_rereads_prices_after_the_refresh_and_keeps_them_when_the_read_fails():
    now, reads = [0.0], []
    answers = [{MODEL: PRICE}, RuntimeError("db down"), {}]

    def read():
        reads.append(now[0])
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    ledger = gc.StackLedger(read_prices=read, write=lambda _: None, refresh_s=300, clock=lambda: now[0])
    assert ledger.prices() == {MODEL: PRICE}
    now[0] = 299
    assert ledger.prices() == {MODEL: PRICE}
    now[0] = 300
    assert ledger.prices() == {MODEL: PRICE}
    now[0] = 600
    assert ledger.prices() == {}
    assert reads == [0.0, 300, 600]


async def test_failing_ledger_does_not_break_the_call():
    def broken(_):
        raise RuntimeError("db down")

    client = GeminiClient(
        make_settings(),
        capabilities=Capabilities.all(),
        ledger=broken,
        transport=httpx.MockTransport(Gateway(ok())),
    )
    assert (await client.generate(model=MODEL, messages=[Message.user("q")], context=CTX)).text == "OK"


async def test_secret_key_never_in_errors_or_records(records):
    gateway = Gateway(httpx.Response(401, json={"error": {"message": "bad key"}}))
    with pytest.raises(GatewayError) as exc:
        await client_for(gateway, records).generate(model=MODEL, messages=[Message.user("q")], context=CTX)
    assert KEY not in str(exc.value)
    assert KEY not in repr(records)


async def test_stream_yields_deltas_then_done_with_usage(records):
    gateway = Gateway(sse("stream_text.sse"))
    events = [
        e
        async for e in client_for(gateway, records).stream(
            model=MODEL, messages=[Message.user("count")], context=CTX
        )
    ]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["1, 2, 3", ", 4, 5"]
    done = events[-1]
    assert isinstance(done, StreamDone)
    assert done.result.text == "1, 2, 3, 4, 5"
    assert done.result.usage.input_tokens == 120
    assert done.result.finish_reason == "stop"
    assert gateway.bodies[0]["stream"] is True
    assert gateway.bodies[0]["stream_options"] == {"include_usage": True}
    assert [r.status for r in records] == ["ok"]


async def test_stream_accumulates_tool_call_fragments():
    gateway = Gateway(sse("stream_tool_call.sse"))
    events = [
        e
        async for e in client_for(gateway).stream(
            model=MODEL, messages=[Message.user("q")], context=CTX, tools=[TOOL]
        )
    ]
    [call] = events[-1].result.tool_calls
    assert (call.id, call.name, call.arguments) == ("call_9", "get_run_peak", {"run_id": "HT-042"})


async def test_stream_retries_before_first_byte():
    sleeps = []
    gateway = Gateway(httpx.Response(503), sse("stream_text.sse"))
    events = [
        e
        async for e in client_for(gateway, sleeps=sleeps).stream(
            model=MODEL, messages=[Message.user("q")], context=CTX
        )
    ]
    assert events[-1].result.text == "1, 2, 3, 4, 5"
    assert len(sleeps) == 1


async def test_stream_without_capability_falls_back_to_one_plain_call():
    gateway = Gateway(ok())
    caps = Capabilities(enabled=frozenset(Capability) - {Capability.STREAMING})
    events = [
        e
        async for e in client_for(gateway, caps=caps).stream(
            model=MODEL, messages=[Message.user("q")], context=CTX
        )
    ]
    assert [type(e) for e in events] == [TextDelta, StreamDone]
    assert "stream" not in gateway.bodies[0]


def test_committed_capabilities_file_comes_from_a_real_probe_and_enables_only_supported():
    from backend.llm_engine.gemini_types import CAPABILITIES_FILE

    document = json.loads(CAPABILITIES_FILE.read_text())
    caps = Capabilities.load()
    assert caps.probed_at == document["probed_at"] is not None
    supported = {name for name, entry in document["capabilities"].items() if entry["status"] == "supported"}
    assert {str(c) for c in caps.enabled} == supported


def test_capabilities_load_enables_only_supported(tmp_path):
    path = tmp_path / "caps.json"
    path.write_text(
        json.dumps(
            {
                "probed_at": "2026-10-21T10:00:00+00:00",
                "capabilities": {
                    "structured_output": {"status": "supported"},
                    "function_calling": {"status": "unsupported"},
                    "thinking_level": {"status": "inconclusive"},
                    "not_a_capability": {"status": "supported"},
                },
            }
        )
    )
    caps = Capabilities.load(path)
    assert caps.enabled == {Capability.STRUCTURED_OUTPUT}
    assert caps.probed_at == "2026-10-21T10:00:00+00:00"
