"""The Answer Engine workflow end to end with a fake Gemini client and patched tools (no database, no GPU)."""

import asyncio
import contextlib
import re
import uuid

import pytest
from pydantic import TypeAdapter

pytest.importorskip("workflows", reason="llama-index-workflows is not installed")

from backend.api.engine import AnswerEvent
from backend.llm_engine.engine import workflow as wf
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult
from backend.llm_engine.engine.tools import external as external_tools
from backend.llm_engine.engine.tools.external import ExternalPolicy
from backend.llm_engine.engine.verifier import check_numeric_claim
from backend.llm_engine.enrichment.entities import AliasIndex
from backend.llm_engine.gemini_types import GatewayError, GenerateResult, Grounding, GroundingSource, Usage

REPORT = uuid.UUID("00000000-0000-4000-8000-000000000037")
PASSAGE = "In TP07 run T04 the chamber pressure reached 12.4 bar at 3.2 s after ignition."
EVENTS = TypeAdapter(AnswerEvent)


class Client:
    """Async fake of GeminiClient.generate; replies per prompt purpose, an exception reply is raised."""

    def __init__(self, **replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.purposes = []

    async def generate(self, *, model, messages, context, schema=None, **options):
        purpose = context.purpose.split(".")[1]
        self.purposes.append(purpose)
        reply = self.replies[purpose].pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, GenerateResult):
            return reply
        return GenerateResult(
            text=reply if isinstance(reply, str) else "",
            parsed=schema.model_validate(reply) if schema is not None else None,
            tool_calls=(),
            usage=Usage(1, 1),
            model=model,
            finish_reason="stop",
            request_id="r",
            latency_ms=1,
        )


def report_hit() -> ToolResult:
    source = Source(
        doc_id=REPORT,
        anchor="page:8:" + "a" * 64,
        title="Test Report 37",
        label="Test Report 37, p. 8",
        provenance=Provenance.INTERNAL_REPORT,
        language="en",
    )
    return ToolResult(
        tool="search_documents",
        result={"hits": [{"parent_text": PASSAGE}]},
        provenance=[source],
        display=PASSAGE,
    )


def no_hits() -> ToolResult:
    return ToolResult(tool="search_documents", result={"hits": []}, display="0 passages for 'TP99 pressure'")


@pytest.fixture
def searches(monkeypatch):
    calls = []

    def install(result):
        def fake_search(session, args, *, embed_query, rerank):
            calls.append(args)
            return result()

        monkeypatch.setattr(wf, "search_documents", fake_search)
        return calls

    return install


def deps(client, traces, policy=None, **extra):
    return wf.EngineDeps(
        **extra,
        external_policy=lambda session: policy or ExternalPolicy(enabled=False),
        gemini=client,
        session_factory=contextlib.nullcontext,
        embed_query=lambda q: [0.0],
        rerank=None,
        alias_index=lambda session: AliasIndex(),
        viewer_url=lambda doc_id, anchor: f"/docs/{doc_id}/viewer?anchor={anchor}",
        save_trace=traces.append,
    )


def run(client, question, traces=None, *, groups=("dcl-engineers",), policy=None, extra=None, **start):
    traces = [] if traces is None else traces

    async def go():
        workflow = wf.AnswerWorkflow(deps(client, traces, policy, **(extra or {})), timeout=30)
        handler = workflow.run(question=question, trace_id=str(uuid.uuid4()), groups=list(groups), **start)
        events = [payload async for payload in wf.ordered(handler.stream_events())]
        return events, await handler

    events, done = asyncio.run(go())
    for payload in events:  # every frame satisfies the wire contract of backend/api/engine.py
        EVENTS.validate_python(payload)
    return events, done, traces


def of(events, kind):
    return [e for e in events if e["type"] == kind]


FACT = {"intents": ["fact_lookup"], "test_plan_ids": ["TP7"], "test_run_ids": ["Run 4"], "language": "en"}
SYNTH = {
    "answer_markdown": "The chamber pressure in TP07 T04 reached 12.4 bar [1].",
    "claims": [
        {
            "text": "The chamber pressure in TP07 T04 reached 12.4 bar",
            "kind": "numeric",
            "evidence_ids": ["E1"],
        }
    ],
    "followups": ["Compare with T05?"],
}


def test_fact_question_streams_steps_tokens_citations_and_done(searches):
    calls = searches(report_hit)
    client = Client(
        query_analysis=[FACT],
        synthesis=[SYNTH],
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]}],
    )
    events, done, traces = run(client, "What chamber pressure did TP7 run 4 reach?")
    assert [e["type"] for e in events][-1] == "done"
    steps = of(events, "step")
    assert {s["name"] for s in steps} >= {"query_analysis", "tool", "synthesis", "verification"}
    assert any(s.get("tool") == "search_documents" and s["done"] for s in steps)
    assert calls[0].filters.test_plan_ids == ["TP07"]
    text = "".join(e["text"] for e in of(events, "token"))
    assert text == done["answer_markdown"] == SYNTH["answer_markdown"]
    # every number the answer states string-matches a tool result (citation markers excluded)
    assert check_numeric_claim(re.sub(r"\[\d+\]", "", text), [PASSAGE]) == []
    [citation] = of(events, "citation")
    assert citation["doc_id"] == str(REPORT) and citation["page_no"] == 8
    assert citation["url_viewer"].startswith(f"/docs/{REPORT}/viewer")
    assert done["mode"] == "answered" and done["verifier"] == {
        "claims": 1,
        "entailed": 1,
        "contradicted": 0,
        "not_supported": 0,
    }
    assert done["followups"] == ["Compare with T05?"]
    [trace] = traces
    assert trace["mode"] == "answered" and trace["retrieved"][0]["anchor"].startswith("page:8:")
    assert trace["query_analysis"]["test_plan_ids"] == ["TP07"]


def test_chitchat_answers_without_tools_or_citations(searches):
    calls = searches(report_hit)
    client = Client(
        query_analysis=[{"intents": ["chitchat_or_out_of_scope"], "language": "de"}],
        chitchat=[
            {"kind": "small_talk", "reply": "Gut, danke! Fragen Sie mich gern zu Tests oder Dokumenten."}
        ],
    )
    events, done, _ = run(client, "Wie geht's?")
    assert calls == [] and of(events, "citation") == []
    assert not any(s["name"] == "tool" for s in of(events, "step"))
    assert done["mode"] == "chitchat" and done["answer_markdown"].startswith("Gut, danke")
    assert client.purposes == ["query_analysis", "chitchat"]


def test_clarification_ends_the_run(searches):
    calls = searches(report_hit)
    clarify = {
        "intents": ["telemetry_metric"],
        "clarification": {"needed": True, "question": "Which test plan?", "options": ["TP07", "TP08"]},
    }
    events, done, _ = run(Client(query_analysis=[clarify]), "What was the peak pressure?")
    assert calls == []
    assert done["mode"] == "clarification" and "Which test plan?" in done["answer_markdown"]
    assert "- TP08" in done["answer_markdown"]


def test_no_evidence_gives_the_insufficient_evidence_template(searches):
    searches(no_hits)
    client = Client(query_analysis=[{**FACT, "test_plan_ids": ["TP99"]}])
    events, done, traces = run(client, "TP99 pressure?")
    assert done["mode"] == "insufficient_evidence"
    assert "What was searched" in done["answer_markdown"] and "0 passages" in done["answer_markdown"]
    assert "synthesis" not in client.purposes and of(events, "citation") == []
    assert traces[0]["mode"] == "insufficient_evidence"


def test_gemini_outage_during_synthesis_degrades_to_extractive(searches):
    searches(report_hit)
    client = Client(query_analysis=[FACT], synthesis=[GatewayError("gateway down", status_code=503)])
    events, done, _ = run(client, "What chamber pressure did TP7 run 4 reach?")
    assert done["mode"] == "extractive"
    assert PASSAGE in done["answer_markdown"] and "Test Report 37, p. 8" in done["answer_markdown"]
    assert len(of(events, "citation")) == 1
    assert any("synthesis unavailable" in c for c in done["caveats"])


def test_physics_question_runs_the_calculator_with_extracted_arguments(searches):
    calls = searches(report_hit)
    client = Client(
        query_analysis=[{"intents": ["physics_calc"]}],
        physics_args=[
            {"operation": "mass_flow_from_thrust", "parameters": {"thrust": "5 N", "isp": "225 s"}}
        ],
        synthesis=[
            {
                "answer_markdown": "The mass flow is 2.266 g/s [1].",
                "claims": [{"text": "The mass flow is 2.266 g/s", "kind": "numeric", "evidence_ids": ["E1"]}],
            }
        ],
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "calculated"}]}],
    )
    events, done, traces = run(client, "Mass flow for 5 N at Isp 225 s?")
    assert calls == []
    assert [c["tool"] for c in traces[0]["tool_calls"]] == ["physics_calculator"]
    assert done["mode"] == "answered", done
    assert of(events, "citation")[0]["provenance"] == "calculation"


# ------------------------------------------------------------------ T6 external search under the policy

ALLOWED = ExternalPolicy(enabled=True, allowed_groups=("dcl-external",), proprietary_terms=("BlueFlame",))
WEB_TEXT = "Monolithic catalyst beds typically need 2 to 5 W of preheat."


def grounded_reply() -> GenerateResult:
    sources = (
        GroundingSource("nasa.gov", "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x"),
    )
    return GenerateResult(
        WEB_TEXT,
        None,
        (),
        Usage(1, 1),
        "m",
        "stop",
        "r",
        1,
        grounding=Grounding(("catalyst preheat power",), sources),
    )


@pytest.fixture
def offline(monkeypatch):
    async def resolve(url):
        return "https://ntrs.nasa.gov/x"

    async def no_arxiv(query):
        return []

    monkeypatch.setattr(external_tools, "resolve_redirect", resolve)
    monkeypatch.setattr(external_tools, "arxiv", no_arxiv)


def external_client(intents, synthesis=None, needs=None):
    needs = (
        needs
        if needs is not None
        else [{"purpose": "general_physics", "query_intent": "BlueFlame catalyst preheat power"}]
    )
    return Client(
        query_analysis=[{"intents": intents, "external_requested": "fact_lookup" in intents}],
        external_intent=[{"needs": needs}],
        external_search=[grounded_reply()] * 3,
        physics_args=[{"operation": "unit_convert", "parameters": {}}],
        synthesis=[
            synthesis
            or {
                "answer_markdown": "Monolith beds need 2 to 5 W of preheat (web) [E2].",
                "claims": [
                    {
                        "text": "Monolith beds need 2 to 5 W of preheat",
                        "kind": "numeric",
                        "evidence_ids": ["E2"],
                    }
                ],
            }
        ],
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]}],
    )


def test_an_explicit_request_goes_external_with_only_the_sanitized_need(searches, offline):
    searches(report_hit)
    client = external_client(["fact_lookup"])
    events, done, traces = run(
        client,
        "Search the web: how much preheat does a BlueFlame monolith need?",
        groups=["dcl-external"],
        policy=ALLOWED,
    )
    assert done["mode"] == "answered"
    assert client.purposes.count("external_search") == 1
    [query] = traces[0]["external_queries"]
    assert query["provider"] == "google_search" and "BlueFlame" not in query["sanitized"]
    assert query["google_queries"] == ["catalyst preheat power"]
    web = [c for c in of(events, "citation") if c["provenance"] == "web"]
    assert web and web[0]["doc_id"] is None
    assert any(s.get("tool") == "external_search" for s in of(events, "step"))


def test_a_user_outside_the_allowed_groups_never_goes_external(searches, offline):
    searches(report_hit)
    client = external_client(["fact_lookup"], synthesis=SYNTH)
    _, done, traces = run(
        client, "Search the web for catalyst preheat", groups=["dcl-engineers"], policy=ALLOWED
    )
    assert "external_intent" not in client.purposes and "external_search" not in client.purposes
    assert traces[0]["external_queries"] == []
    assert any("not enabled for your groups" in c for c in done["caveats"])


def test_benchmark_mock_and_the_kill_switch(searches, offline):
    searches(report_hit)
    client = external_client(["fact_lookup"], synthesis=SYNTH)
    _, _, traces = run(
        client,
        "Search the web for catalyst preheat",
        groups=["dcl-external"],
        policy=ALLOWED,
        external_mode="mock",
    )
    assert "external_search" not in client.purposes
    assert traces[0]["external_queries"][0]["provider"] == "mock"
    off = ExternalPolicy(enabled=False, allowed_groups=("dcl-external",))
    client = external_client(["fact_lookup"], synthesis=SYNTH)
    run(client, "Search the web for catalyst preheat", groups=["dcl-external"], policy=off)
    assert "external_intent" not in client.purposes


def test_design_synthesis_goes_external_only_for_a_gap(searches, offline):
    calls = searches(report_hit)  # internal evidence exists: no web
    client = external_client(["design_synthesis"], synthesis=SYNTH)
    run(client, "Design a 5 N thruster", groups=["dcl-external"], policy=ALLOWED)
    assert calls and "external_intent" not in client.purposes
    searches(no_hits)  # nothing internal or in the library: the gap goes to the web
    client = external_client(
        ["design_synthesis"],
        synthesis={
            # E1, E2: the two empty internal searches; E3: the calculator's note; E4: the web result
            "answer_markdown": "Published monolith beds need 2 to 5 W of preheat (web) [E4].",
            "claims": [
                {
                    "text": "Published monolith beds need 2 to 5 W of preheat",
                    "kind": "numeric",
                    "evidence_ids": ["E4"],
                }
            ],
        },
    )
    _, done, traces = run(client, "Design a 5 N thruster", groups=["dcl-external"], policy=ALLOWED)
    assert client.purposes.count("external_search") == 1 and done["mode"] == "answered"


def test_at_most_three_external_queries(searches, offline):
    searches(report_hit)
    needs = [
        {"purpose": "general_physics", "query_intent": f"catalyst preheat power class {n}"} for n in range(5)
    ]
    client = external_client(["fact_lookup"], needs=needs)  # five needs: three are searched
    _, _, traces = run(client, "Search the web for catalyst preheat", groups=["dcl-external"], policy=ALLOWED)
    assert len(traces[0]["external_queries"]) == 3


PHOTO = "Catalyst screen deformed after T04, discoloured ring."


def photo_result() -> ToolResult:
    source = Source(
        doc_id=REPORT,
        anchor="page:1:" + "b" * 64,
        title="TP07 post-test photos",
        label="TP07 post-test photos, p. 1",
        provenance=Provenance.INTERNAL_REPORT,
    )
    shown = {
        "doc_id": str(REPORT),
        "title": "TP07 post-test photos",
        "anchor": source.anchor,
        "node_type": "photo",
        "reading": PHOTO,
        "breadcrumb": "TP07 › post-test",
        "asset_uri": "s3://dcl-assets/photos/a_web.jpg",
        "url_web": "https://minio.test/a_web.jpg",
        "url_thumb": "https://minio.test/a_thumb.jpg",
    }
    return ToolResult(
        tool="inspect_visuals",
        result={"visuals": [shown], "hits": [{"parent_text": PHOTO}]},
        provenance=[source],
        display=PHOTO,
    )


def test_visual_lookup_runs_t3_looks_again_and_streams_a_photo_strip(searches, monkeypatch):
    searches(report_hit)
    t3_calls, fetched = [], []

    def fake_visuals(session, args, *, embed_query, rerank, presign):
        t3_calls.append(args)
        return photo_result()

    monkeypatch.setattr(wf.visual_tools, "inspect_visuals", fake_visuals)
    client = Client(
        query_analysis=[{"intents": ["visual_lookup"], "test_plan_ids": ["TP7"], "language": "en"}],
        relook=[
            {
                "answer": "Yes, the ring is buckled.",
                "images": [{"image": 1, "observation": "buckled", "visible": "yes"}],
            }
        ],
        synthesis=[
            {
                "answer_markdown": "The post-test photos show the catalyst screen deformed [1].",
                "claims": [
                    {"text": "the catalyst screen is deformed", "kind": "factual", "evidence_ids": ["E1"]}
                ],
            }
        ],
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]}],
    )
    events, done, traces = run(
        client,
        "Show me the catalyst screen photos of TP7",
        extra={"fetch_asset": lambda uri: fetched.append(uri) or b"jpeg"},
    )
    assert t3_calls[0].test_plan_ids == ["TP07"] and t3_calls[0].relook_question
    assert fetched == ["s3://dcl-assets/photos/a_web.jpg"] and "relook" in client.purposes
    [strip] = of(events, "embed")
    assert strip["kind"] == "photo_strip" and "https://minio.test/a_thumb.jpg" in strip["html"]
    assert done["mode"] == "answered"
    assert any(s.get("tool") == "inspect_visuals" and s["done"] for s in of(events, "step"))


MEASURED = "Run TP07_T04 · chamber_pressure → p_chamber_1_bar_g (barg, gauge): peak_50ms 12.38 barg"


def test_telemetry_question_runs_t2_with_extracted_arguments(searches, monkeypatch):
    searches(report_hit)
    t2_calls = []

    def fake_telemetry(session, args, *, connect, put_asset, presign):
        t2_calls.append(args)
        source = Source(
            doc_id=REPORT, label="Run TP07_T04 (measured telemetry)", provenance=Provenance.MEASURED
        )
        return ToolResult(tool="query_telemetry", result={"runs": []}, provenance=[source], display=MEASURED)

    monkeypatch.setattr(wf.telemetry_tools, "query_telemetry", fake_telemetry)
    monkeypatch.setattr(wf, "catalog_lookup", lambda session, args: no_hits())
    client = Client(
        query_analysis=[
            {"intents": ["telemetry_metric"], "test_plan_ids": ["TP7"], "test_run_ids": ["Run 4"]}
        ],
        telemetry_args=[{"channels": ["chamber_pressure"], "metrics": ["peak_50ms"]}],
        synthesis=[
            {
                "answer_markdown": "The 50 ms peak chamber pressure was 12.38 barg [1].",
                "claims": [
                    {"text": "peak 12.38 barg", "kind": "numeric", "evidence_ids": ["E1"]},
                ],
            }
        ],
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "measured"}]}],
    )
    events, done, traces = run(client, "What was the 50 ms peak chamber pressure in TP7 run 4?")
    [args] = t2_calls
    assert (args.test_plan_id, args.test_run_ids, args.channels) == ("TP07", ["T04"], ["chamber_pressure"])
    assert args.metrics == ["peak_50ms"] and args.window_kind == "run"
    assert traces[0]["tool_calls"][0]["tool"] == "query_telemetry"
    assert done["mode"] == "answered" and done["caveats"] == []
    assert of(events, "citation")[0]["provenance"] == "measured"


def test_telemetry_question_without_a_quantity_skips_t2(searches, monkeypatch):
    searches(report_hit)
    monkeypatch.setattr(wf, "catalog_lookup", lambda session, args: no_hits())
    monkeypatch.setattr(wf.telemetry_tools, "query_telemetry", pytest.fail)
    client = Client(
        query_analysis=[{"intents": ["telemetry_metric"], "test_plan_ids": ["TP7"]}],
        telemetry_args=[{"channels": []}],
        synthesis=[SYNTH],
        repair=[{"claims": [{"index": 0, "text": None}]}],  # the claim cites E1, the empty catalog result
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]}] * 2,
    )
    _, done, traces = run(client, "Which runs of TP7 had a sensor fault?")
    assert "query_telemetry" not in [c["tool"] for c in traces[0]["tool_calls"]]


def test_plot_embeds_fit_the_wire_contract():
    from backend.api.engine import EmbedEvent

    result = ToolResult(
        tool="query_telemetry",
        result={"runs": [], "plots": [{"url": "https://minio.test/p.png", "alt": "Run TP07_T04: thrust_n"}]},
        display="x",
    )
    [embed] = wf.plot_embeds([result])
    event = TypeAdapter(EmbedEvent).validate_python(embed)
    assert event.kind == "plot" and event.url == "https://minio.test/p.png" and event.html is None


def test_a_mentioned_playbook_adds_its_intent(searches, monkeypatch):
    searches(report_hit)
    seen = []
    monkeypatch.setattr(
        wf.visual_tools,
        "inspect_visuals",
        lambda session, args, **kw: (
            seen.append(args) or ToolResult(tool="inspect_visuals", result={}, display="none")
        ),
    )
    client = Client(
        query_analysis=[FACT],
        synthesis=[SYNTH, SYNTH],
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]}] * 2,
    )
    _, _, traces = run(client, "What chamber pressure did TP7 run 4 reach?", playbook_hint="visual_lookup")
    assert seen and "visual_lookup" in traces[0]["query_analysis"]["raw"]["intents"]
    assert traces[0]["query_analysis"]["raw"]["intents"][0] == "fact_lookup"


def test_the_hint_must_be_an_intent():
    from pydantic import ValidationError

    from backend.api.engine import AnswerOptions

    assert AnswerOptions(playbook_hint="telemetry_metric").playbook_hint == "telemetry_metric"
    with pytest.raises(ValidationError):
        AnswerOptions(playbook_hint="drop_tables")


def test_benchmark_answers_take_the_chat_path_and_mock_makes_no_network_call(searches, monkeypatch):
    from backend.benchmark.runner import workflow_answer

    async def no_network(*args, **kwargs):
        raise AssertionError("benchmark mock mode must not reach the network")

    monkeypatch.setattr(external_tools, "resolve_redirect", no_network)
    monkeypatch.setattr(external_tools, "arxiv", no_network)
    searches(report_hit)
    client = external_client(["fact_lookup"], synthesis=SYNTH)
    logged = []
    answer = workflow_answer(deps(client, logged, ALLOWED))  # the benchmark caller is in the allowed group
    done, trace = asyncio.run(answer("Search the web for catalyst preheat", "", "mock"))
    assert done["mode"] == "answered" and trace is logged[0]  # captured and still logged like chat
    assert trace["external_queries"][0]["provider"] == "mock"
    assert "external_search" not in client.purposes  # no grounded Gemini search either


def test_an_out_of_scope_question_is_refused_on_the_insufficient_evidence_path(searches):
    calls = searches(report_hit)
    client = Client(
        query_analysis=[{"intents": ["chitchat_or_out_of_scope"], "language": "en"}],
        chitchat=[
            {"kind": "out_of_scope", "reply": "I cannot answer that: the weather is outside our material."}
        ],
    )
    events, done, _ = run(client, "What is the weather in Pune tomorrow?")
    assert calls == [] and of(events, "citation") == []
    assert done["mode"] == "insufficient_evidence" and "cannot answer" in done["answer_markdown"]


def test_a_halted_run_is_named_in_the_answer(searches, monkeypatch):
    searches(report_hit)
    warning = "run TP07_T01 (TP07_T01.dat) is halted for review (case-unit-7); its telemetry is not answered"

    def halted(session, args, **kw):
        return ToolResult(tool="query_telemetry", result={"runs": []}, warnings=[warning], display="none")

    monkeypatch.setattr(wf.telemetry_tools, "query_telemetry", halted)
    monkeypatch.setattr(wf, "catalog_lookup", lambda session, args: no_hits())
    client = Client(
        query_analysis=[FACT | {"intents": ["telemetry_metric"]}],
        telemetry_args=[{"channels": ["chamber_pressure"], "metrics": ["mean"]}],
        synthesis=[SYNTH],
        repair=[{"claims": [{"index": 0, "text": None}]}],  # E1 is the empty T2 result
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]}] * 2,
    )
    events, done, _ = run(client, "Mean chamber pressure of TP7 run 1?")
    assert done["answer_markdown"].endswith(f"> Note: {warning}")
    assert warning in done["caveats"]
    assert "".join(e["text"] for e in of(events, "token")) == done["answer_markdown"]
