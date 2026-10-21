"""The Open WebUI Pipe against S2's /v1/answer contract, replayed through a mock HTTP transport.

Every Pipe test runs twice: on the source module and on the installable bundle in dist/.
"""

import asyncio
import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.api import engine
from frontend.openwebui import api_endpoint, pipe_manastu_engine
from frontend.openwebui.build_functions import bundle

ROOT = Path(__file__).resolve().parents[4]
EXAMPLE = ROOT / "backend/tests/unit/llm_engine/engine/example_answer_stream.sse"
DIST = ROOT / "frontend/openwebui/dist/manastu_engine.py"
SECRET = "test-shared-secret"
TRACE = "0b6d9f0e-1111-4222-8333-444455556666"


def load_dist():
    spec = importlib.util.spec_from_file_location("manastu_engine_dist", DIST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["source", "dist"])
def pipe_module(request):
    return pipe_manastu_engine if request.param == "source" else load_dist()


class Recorder:
    def __init__(self, responses):
        self.responses = responses  # path → (status, body, content type)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body, ctype = self.responses[request.url.path]
        return httpx.Response(status, content=body.encode(), headers={"content-type": ctype})


def make_pipe(module, responses, **valves):
    pipe = module.Pipe()
    pipe.valves = pipe.Valves(
        ENGINE_URL="http://engine.test",
        ENGINE_SHARED_SECRET=SECRET,
        CONSOLE_URL="https://console.test",
        **valves,
    )
    recorder = Recorder(responses)
    pipe.http_client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))

    async def groups(user_id):
        return ("dcl-external-search", "dcl-reviewers")

    pipe._groups_of = groups
    return pipe, recorder


def run(pipe, body=None, task=None, user_valves=None, confirm_reply=True):
    yielded, events, calls = [], [], []

    async def emitter(event):
        events.append(event)

    async def caller(event):
        calls.append(event)
        return confirm_reply

    async def go():
        user = {"id": "u-1", "email": "asha@manastuspace.com", "name": "Asha"}
        if user_valves is not None:
            user["valves"] = user_valves
        async for item in pipe.pipe(
            body or {"messages": [{"role": "user", "content": "Steady-state pressure of TP07 T04?"}]},
            __user__=user,
            __event_emitter__=emitter,
            __event_call__=caller,
            __metadata__={"chat_id": "chat-1", "message_id": "msg-1"},
            __task__=task,
        ):
            yielded.append(item)

    asyncio.run(go())
    return yielded, events, calls


def sse(*events) -> str:
    return "".join(engine.to_sse(e) for e in events)


ANSWER = {"/v1/answer": (200, EXAMPLE.read_text(), "text/event-stream")}


def test_example_stream_maps_to_open_webui_events(pipe_module):
    pipe, recorder = make_pipe(pipe_module, ANSWER)
    yielded, events, _ = run(pipe)

    assert all(isinstance(item, str) for item in yielded)  # text only: never a tool_calls delta
    assert "".join(yielded) == "TP07 run T04: steady-state mean 12.4 bar(a) over +1.0 to +9.8 s [1]."

    statuses = [e["data"] for e in events if e["type"] == "status"]
    assert statuses[0] == {"description": "Understanding the question", "done": False}
    assert statuses[-1] == {"description": "Answer verified", "done": True}

    sources = [e["data"] for e in events if e["type"] == "source"]
    assert len(sources) == 1
    source = sources[0]
    assert source["source"]["name"] == "Test Report 37"
    assert source["source"]["url"].startswith(
        "https://console.manastu.test/docs/6f1c2a3e-0000-4000-8000-000000000001/viewer?anchor="
    )
    assert source["document"] == ["steady state 12.5 bar"]
    assert source["metadata"][0]["name"] == "[1] Test Report 37, p. 8 (internal report)"

    embeds = [e["data"]["embeds"][0] for e in events if e["type"] == "embeds"]
    assert (
        len(embeds) == 1
        and 'src="https://minio.manastu.test/dcl-assets/plots/tp07_t04.png?sig=x"' in embeds[0]
    )
    assert "iframe:height" in embeds[0]
    assert {"type": "chat:message:follow_ups", "data": {"follow_ups": ["Compare with T05?"]}} in events

    sent = recorder.requests[0]
    body = json.loads(sent.content)
    assert body["messages"] == [{"role": "user", "content": "Steady-state pressure of TP07 T04?"}]
    assert (body["chat_id"], body["message_id"], body["attachments"]) == ("chat-1", "msg-1", [])
    assert sent.headers["x-dcl-user-groups"] == "dcl-external-search,dcl-reviewers"


def test_engine_accepts_the_pipe_signature(monkeypatch):
    settings = SimpleNamespace(pipe_shared_secret=SecretStr(SECRET))
    settings.require = lambda *groups: settings
    monkeypatch.setattr(engine, "get_settings", lambda: settings)
    app = FastAPI()

    @app.post("/echo")
    async def echo(identity: engine.Identity):
        return identity

    config = SimpleNamespace(shared_secret=SECRET)
    identity = api_endpoint.Identity("u-1", "asha@manastuspace.com", ("dcl-reviewers", "dcl-admins"))
    body = b'{"messages": []}'
    headers = api_endpoint.identity_headers(config, identity, body)
    response = TestClient(app).post("/echo", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "user_id": "u-1",
        "email": "asha@manastuspace.com",
        "groups": ["dcl-reviewers", "dcl-admins"],
    }
    assert api_endpoint.sign_identity(SECRET, "1", "u", "e", "g", b"x") == engine.sign_identity(
        SECRET, "1", "u", "e", "g", b"x"
    )

    tampered = TestClient(app).post("/echo", content=b'{"messages": [1]}', headers=headers)
    assert tampered.status_code == 401


def confirmation_stream(with_trace: bool) -> str:
    event = engine.ConfirmationEvent(
        confirmation_id="c-1", title="Use unverified value?", message="PT-101 needs review"
    )
    frame = engine.to_sse(event)
    if with_trace:  # S2 adds trace_id to ConfirmationEvent (c1641d5); same wire shape
        data = json.loads(frame.split("data: ", 1)[1])
        frame = f"event: needs_confirmation\ndata: {json.dumps(data | {'trace_id': TRACE})}\n\n"
    done = engine.DoneEvent(
        trace_id=uuid.UUID(TRACE),
        mode="answered",
        answer_markdown="12.4 bar(a) ⚠ unverified extraction",
        caveats=["PT-101 value comes from an unverified extraction"],
        usage=engine.Usage(tokens_in=1, tokens_out=1),
        latency_ms=10,
    )
    return frame + engine.to_sse(done)


@pytest.mark.parametrize(
    ("reply", "accepted"), [(True, True), (False, False), ({"error": "timed out"}, False)]
)
def test_confirmation_is_forwarded_with_the_trace_id(pipe_module, reply, accepted):
    responses = {
        "/v1/answer": (200, confirmation_stream(with_trace=True), "text/event-stream"),
        f"/v1/answer/{TRACE}/confirm": (202, "", "application/json"),
    }
    pipe, recorder = make_pipe(pipe_module, responses)
    yielded, _, calls = run(pipe, confirm_reply=reply)
    assert calls == [
        {"type": "confirmation", "data": {"title": "Use unverified value?", "message": "PT-101 needs review"}}
    ]
    confirm_request = recorder.requests[1]
    assert json.loads(confirm_request.content) == {"confirmation_id": "c-1", "accepted": accepted}
    assert "x-dcl-signature" in confirm_request.headers
    # no tokens were streamed, so the final markdown is shown, plus the caveat not already in it
    assert (
        "".join(yielded)
        == "12.4 bar(a) ⚠ unverified extraction\n\n> ⚠ PT-101 value comes from an unverified extraction"
    )


def test_confirmation_without_trace_id_is_declined_not_sent(pipe_module):
    pipe, recorder = make_pipe(
        pipe_module, {"/v1/answer": (200, confirmation_stream(with_trace=False), "text/event-stream")}
    )
    _, events, _ = run(pipe)
    assert len(recorder.requests) == 1
    assert any(e["type"] == "notification" for e in events)


@pytest.mark.parametrize(
    ("response", "detail"),
    [
        (
            (501, '{"detail": "the answer workflow is not built yet"}', "application/json"),
            "The answer engine is not available yet.",
        ),
        (
            (401, '{"detail": "identity signature does not verify"}', "application/json"),
            "identity signature does not verify",
        ),
        ((502, "<html>bad gateway</html>", "text/html"), "engine answered HTTP 502"),
        (
            (
                200,
                sse(
                    engine.ErrorEvent(
                        code="budget_exhausted", message="Daily Gemini budget reached", retryable=False
                    )
                ),
                "text/event-stream",
            ),
            "Daily Gemini budget reached",
        ),
    ],
)
def test_errors_surface_as_open_webui_error_state(pipe_module, response, detail):
    pipe, _ = make_pipe(pipe_module, {"/v1/answer": response})
    yielded, _, _ = run(pipe)
    assert yielded[-1] == {"error": {"detail": detail}}


def test_unreachable_engine_and_missing_valves(pipe_module):
    pipe = pipe_module.Pipe()
    yielded, _, _ = run(pipe)
    missing = "Manastu engine is not configured: set the ENGINE_URL, ENGINE_SHARED_SECRET valve(s)"
    assert yielded == [{"error": {"detail": missing}}]

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    pipe, _ = make_pipe(pipe_module, {})
    pipe.http_client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    yielded, _, _ = run(pipe)
    assert yielded == [{"error": {"detail": "engine unreachable: ConnectError"}}]


def test_open_webui_tasks_never_reach_the_engine(pipe_module):
    pipe, recorder = make_pipe(pipe_module, ANSWER)
    run(pipe)  # a real answer first, so follow-ups are remembered for this chat
    calls_after_answer = len(recorder.requests)
    title, _, _ = run(pipe, task="title_generation")
    follow, _, _ = run(pipe, task="follow_up_generation")
    tags, _, _ = run(pipe, task="tags_generation")
    assert len(recorder.requests) == calls_after_answer
    assert json.loads(title[0]) == {"title": "Steady-state pressure of TP07 T04?"}
    assert json.loads(follow[0]) == {"follow_ups": ["Compare with T05?"]}
    assert json.loads(tags[0]) == {"tags": []}


def test_user_valves_and_debug_tool_blocks(pipe_module):
    pipe, recorder = make_pipe(pipe_module, ANSWER, DEFAULT_THINKING_LEVEL="low", SHOW_STATUS_EVENTS=False)
    valves = pipe.UserValves(strict_numbers=True, show_debug_trace=True)
    yielded, events, _ = run(pipe, user_valves=valves)
    options = json.loads(recorder.requests[0].content)["options"]
    assert options == {
        "thinking_level": "low",
        "strict_numbers": True,
        "show_debug_trace": True,
        "max_embeds": 6,
    }
    assert not any(e["type"] == "status" for e in events)
    assert yielded[0].strip().startswith('<details type="tool_calls" done="true" name="query_telemetry">')
    assert "Running DuckDB on TP07_T04 · 310 ms" in yielded[0]


def test_multimodal_and_tool_messages_become_text_only():
    messages = [
        {"role": "system", "content": "Be precise."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is this?"},
                {"type": "image_url", "image_url": {"url": "x"}},
            ],
        },
        {"role": "tool", "content": "ignored"},
        {"role": "assistant", "content": ""},
    ]
    assert pipe_manastu_engine.engine_messages(messages) == [
        {"role": "system", "content": "Be precise."},
        {"role": "user", "content": "What is this?"},
    ]


def test_dist_bundle_is_current():
    assert DIST.read_text() == bundle("pipe_manastu_engine.py")
