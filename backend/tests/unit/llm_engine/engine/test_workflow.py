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
from backend.llm_engine.engine.verifier import check_numeric_claim
from backend.llm_engine.enrichment.entities import AliasIndex
from backend.llm_engine.gemini_types import GatewayError, GenerateResult, Usage

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


def deps(client, traces):
    return wf.EngineDeps(
        gemini=client,
        session_factory=contextlib.nullcontext,
        embed_query=lambda q: [0.0],
        rerank=None,
        alias_index=lambda session: AliasIndex(),
        viewer_url=lambda doc_id, anchor: f"/docs/{doc_id}/viewer?anchor={anchor}",
        save_trace=traces.append,
    )


def run(client, question, traces=None):
    traces = [] if traces is None else traces

    async def go():
        workflow = wf.AnswerWorkflow(deps(client, traces), timeout=30)
        handler = workflow.run(question=question, trace_id=str(uuid.uuid4()), groups=["dcl-engineers"])
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
        chitchat=["Gut, danke! Fragen Sie mich gern zu Tests oder Dokumenten."],
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
