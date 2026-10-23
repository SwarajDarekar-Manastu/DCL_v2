"""Open WebUI Actions (Show trace, Report issue) against S2's trace routes, on source and bundle."""

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastapi.responses import HTMLResponse

from frontend.openwebui import actions_manastu
from frontend.openwebui.build_functions import bundle

ROOT = Path(__file__).resolve().parents[4]
BUNDLED = ROOT / "frontend/openwebui/bundled/manastu_actions.py"
TRACE_ID = "0b6d9f0e-1111-4222-8333-444455556666"
TRACE = {
    "trace_id": TRACE_ID,
    "chat_id": "chat-1",
    "message_id": "msg-1",
    "question": "Steady-state pressure of TP07 T04?",
    "query_analysis": {},
    "tool_calls": [
        {"tool": "query_telemetry", "duration_ms": 310, "status": "ok", "arguments": {"run": "TP07_T04"}}
    ],
    "retrieved": [
        {
            "rank": 1,
            "score": 0.91,
            "title": "Test Report 37 <script>x</script>",
            "anchor": "page:8:3f2a9c1b7d4e5f60",
            "url_viewer": "https://console.test/docs/d/viewer?anchor=page%3A8%3A",
        }
    ],
    "external_queries": [],
    "claims": [
        {"text": "steady-state mean 12.4 bar(a)", "kind": "numeric", "verdict": "entailed"},
        {"text": "peak 13.1 bar(a)", "kind": "numeric", "verdict": "not_supported"},
        {"text": "the run was nominal", "kind": "factual", "verdict": "entailed"},
    ],
    "citations": [
        {"anchor": {"doc_id": "6f1c2a3e-0000-4000-8000-000000000001", "page_no": 8}, "label": "TR37 p. 8"},
        {
            "anchor": {"doc_id": "6f1c2a3e-0000-4000-8000-000000000001", "page_no": 8},
            "label": "TR37 p. 8 again",
        },
    ],
    "verifier_result": {"claims": 1, "entailed": 1},
    "answer_markdown": "12.4 bar(a) [1]",
    "latency_ms": 6100,
    "created_at": "2026-10-22T09:00:00Z",
}


@pytest.fixture(params=["source", "bundle"])
def module(request):
    if request.param == "source":
        return actions_manastu
    spec = importlib.util.spec_from_file_location("manastu_actions_bundle", BUNDLED)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def make(module, routes):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = routes[(request.method, request.url.path)]
        return httpx.Response(status, json=body)

    action = module.Action()
    action.valves = action.Valves(ENGINE_URL="http://engine.test", ENGINE_SHARED_SECRET="s3cret")
    action.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def groups(user_id):
        return ("dcl-reviewers",)

    action._groups_of = groups
    return action, seen


def run(action, sub_id, reply=None):
    events, calls = [], []

    async def emitter(event):
        events.append(event)

    async def caller(event):
        calls.append(event)
        return reply

    result = asyncio.run(
        action.action(
            {"model": "manastu_engine.main", "chat_id": "chat-1", "id": "msg-1", "session_id": "s"},
            __user__={"id": "u-1", "email": "asha@manastuspace.com"},
            __event_emitter__=emitter,
            __event_call__=caller,
            __id__=sub_id,
        )
    )
    return result, events, calls


def test_declares_three_actions(module):
    assert [a["id"] for a in module.Action.actions] == ["show_trace", "add_to_benchmark", "report_issue"]


def test_show_trace_returns_an_inline_embed_with_escaped_values(module):
    action, seen = make(module, {("GET", "/v1/traces"): (200, TRACE)})
    result, events, _ = run(action, "show_trace")
    assert isinstance(result, HTMLResponse)
    assert result.headers["content-disposition"] == "inline"
    page = result.body.decode()
    assert "query_telemetry" in page and "310" in page and "entailed" in page and "not_supported" in page
    assert "<script>x</script>" not in page and "&lt;script&gt;x&lt;/script&gt;" in page
    assert 'href="https://console.test/docs/d/viewer?anchor=page%3A8%3A"' in page
    assert "iframe:height" in page
    request = seen[0]
    assert dict(request.url.params) == {"chat_id": "chat-1", "message_id": "msg-1"}
    assert request.headers["x-dcl-user-groups"] == "dcl-reviewers"
    assert events == []


@pytest.mark.parametrize(
    ("status", "message"), [(404, "This answer has no engine trace."), (501, "Traces are not available yet.")]
)
def test_missing_trace_is_a_notification(module, status, message):
    action, _ = make(module, {("GET", "/v1/traces"): (status, {"detail": "x"})})
    result, events, _ = run(action, "show_trace")
    assert result is None
    assert events == [{"type": "notification", "data": {"type": "warning", "content": message}}]


def test_report_issue_posts_the_chosen_kind(module):
    routes = {
        ("GET", "/v1/traces"): (200, TRACE),
        ("POST", f"/v1/traces/{TRACE_ID}/feedback"): (202, None),
    }
    action, seen = make(module, routes)
    result, events, calls = run(action, "report_issue", reply="4: the chamber pressure is psia, not psig")
    assert result is None
    assert calls[0]["type"] == "input" and "4. Wrong unit or extraction" in calls[0]["data"]["message"]
    assert json.loads(seen[1].content) == {
        "kind": "wrong_unit",
        "comment": "the chamber pressure is psia, not psig",
        "citation_id": None,
    }
    assert "x-dcl-signature" in seen[1].headers
    assert events[-1]["data"]["type"] == "success"


@pytest.mark.parametrize("reply", [None, False, "", {"error": "timed out"}])
def test_cancelled_report_sends_nothing(module, reply):
    action, seen = make(module, {("GET", "/v1/traces"): (200, TRACE)})
    run(action, "report_issue", reply=reply)
    assert [r.method for r in seen] == ["GET"]


def test_report_without_a_reason_number_is_refused(module):
    action, seen = make(module, {("GET", "/v1/traces"): (200, TRACE)})
    _, events, _ = run(action, "report_issue", reply="the number looks wrong")
    assert [r.method for r in seen] == ["GET"]
    assert "number of the reason" in events[-1]["data"]["content"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 off by ten", ("wrong_number", "off by ten")),
        ("  5. German page mistranslated", ("wrong_translation", "German page mistranslated")),
        ("3", ("missing_document", None)),
        ("12 nope", None),
        ("6 nope", None),
    ],
)
def test_parse_report(text, expected):
    assert actions_manastu.parse_report(text) == expected


def test_report_naming_a_source_sends_its_citation(module):
    routes = {
        ("GET", "/v1/traces"): (200, TRACE),
        ("POST", f"/v1/traces/{TRACE_ID}/feedback"): (202, None),
    }
    action, seen = make(module, routes)
    _, _, calls = run(action, "report_issue", reply="4 [2] the chamber pressure is psia, not psig")
    assert "add its number in brackets" in calls[0]["data"]["message"]
    assert json.loads(seen[1].content) == {
        "kind": "wrong_unit",
        "comment": "[2] the chamber pressure is psia, not psig",
        "citation_id": "2",
    }


@pytest.mark.parametrize(
    ("comment", "expected"),
    [("the unit in [3] is psia", "3"), ("[1] and [2]", "1"), ("no source named", None), (None, None)],
)
def test_cited_source(comment, expected):
    assert actions_manastu.cited_source(comment) == expected


def test_draft_reads_the_page_from_a_serialized_anchor():
    trace = {
        "trace_id": TRACE_ID,
        "question": "Max firing duration in TP-23?",
        "claims": [],
        "citations": [
            {"doc_id": "3f68c08a-6494-4323-bcca-90385ac0297b", "anchor": "page:1:1d1d401de82dbc5d"},
            {"doc_id": "3f68c08a-6494-4323-bcca-90385ac0297b", "anchor": "page:9:6c7e93f8afcfaac4"},
            {"doc_id": "9a1b0000-0000-4000-8000-000000000001", "anchor": "line:40:abcd"},
        ],
    }
    cited = actions_manastu.draft_from_trace(trace, "from-chat")["spec"]["expected_citations"]
    assert [(c["doc_id"][:8], c["page"]) for c in cited] == [
        ("3f68c08a", 1),
        ("3f68c08a", 9),
        ("9a1b0000", None),
    ]
    assert [actions_manastu.page_of(a) for a in ("page:12:ab", "page::", "t:83500:ab", None)] == [
        12,
        None,
        None,
        None,
    ]


def test_bundle_is_current():
    assert BUNDLED.read_text() == bundle("actions_manastu.py")


def test_draft_prefill_is_what_the_benchmark_api_accepts():
    from backend.benchmark.catalog import DraftFromChat

    draft = actions_manastu.draft_from_trace(TRACE, "from-chat")
    parsed = DraftFromChat.model_validate(draft)
    assert parsed.category == "TELEMETRY_MATH" and parsed.question == TRACE["question"]
    assert [(n.value, n.unit) for n in parsed.spec.expected_numeric] == [
        (12.4, "bar(a)")
    ]  # only verified numbers
    assert [(str(c.doc_id), c.page) for c in parsed.spec.expected_citations] == [
        ("6f1c2a3e-0000-4000-8000-000000000001", 8)
    ]
    assert parsed.spec.expected_tools.tools == ["query_telemetry"]
    assert str(parsed.source_trace_id) == TRACE_ID


def test_add_to_benchmark_posts_a_draft(module):
    routes = {
        ("GET", "/v1/traces"): (200, TRACE),
        ("POST", "/benchmark/drafts"): (201, {"case_id": "chat-1a2b3c4d5e6f", "status": "draft"}),
    }
    action, seen = make(module, routes)
    result, events, calls = run(action, "add_to_benchmark", reply="golden-chat")
    assert result is None and calls[0]["type"] == "input"
    body = json.loads(seen[1].content)
    assert body["suite"] == "golden-chat" and body["source_trace_id"] == TRACE_ID
    assert "x-dcl-signature" in seen[1].headers
    assert events[-1]["data"] == {
        "type": "success",
        "content": "Draft case chat-1a2b3c4d5e6f added to golden-chat; approve it in the Console.",
    }


@pytest.mark.parametrize("reply", [None, False, {"error": "timed out"}])
def test_cancelled_draft_sends_nothing(module, reply):
    action, seen = make(module, {("GET", "/v1/traces"): (200, TRACE)})
    run(action, "add_to_benchmark", reply=reply)
    assert [r.method for r in seen] == ["GET"]


def test_empty_suite_defaults_and_refusal_is_reported(module):
    routes = {
        ("GET", "/v1/traces"): (200, TRACE),
        ("POST", "/benchmark/drafts"): (422, {"detail": "question: String should have at least 1 character"}),
    }
    action, seen = make(module, routes)
    _, events, _ = run(action, "add_to_benchmark", reply="  ")
    assert json.loads(seen[1].content)["suite"] == "from-chat"
    assert events[-1]["data"]["type"] == "error" and "could not be created" in events[-1]["data"]["content"]
