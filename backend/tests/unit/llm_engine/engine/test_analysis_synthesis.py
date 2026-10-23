import asyncio
import re
import uuid

import pytest

from backend.llm_engine.engine.analysis import Intent, QueryAnalysis, analyze, resolve
from backend.llm_engine.engine.synthesis import Claim, answer, evidence_items
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult
from backend.llm_engine.enrichment.entities import AliasIndex
from backend.llm_engine.gemini_types import GenerateResult, Usage

C103 = uuid.UUID("00000000-0000-4000-8000-000000000103")


def index():
    idx = AliasIndex()
    idx.add("material", "C-103", C103)
    idx.add("material", "C103", C103)
    return idx


class Client:
    """Async fake of GeminiClient.generate: replies come from a queue per prompt purpose."""

    def __init__(self, **replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.calls = []

    async def generate(self, *, model, messages, context, schema, **options):
        self.calls.append((context.purpose, messages[-1].parts[0].text, options))
        reply = self.replies[context.purpose.split(".")[1]].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return GenerateResult(
            text="",
            parsed=schema.model_validate(reply),
            tool_calls=(),
            usage=Usage(1, 1),
            model=model,
            finish_reason="stop",
            request_id="r",
            latency_ms=1,
        )


def test_resolution_normalizes_ids_entities_and_the_web_policy():
    raw = QueryAnalysis(
        intents=["telemetry_metric"],
        entities=[{"type": "material", "surface": "c 103"}],
        test_plan_ids=["TP7", "Test Plan 37"],
        test_run_ids=["Run 4", "T04"],
        hardware_items=["Injector 14"],
        external_requested=True,
        numeric_constraints=[
            {"quantity": "isp", "op": ">", "value": "230", "unit": "s"},
            {"quantity": "x", "op": "<", "value": "1", "unit": "zorks"},
        ],
    )
    analysis = resolve(raw, index(), user_groups=["dcl-engineers"], external_allowed_groups=["dcl-external"])
    assert analysis.entity_ids == [C103]
    assert analysis.test_plan_ids == ["TP07", "TP37"] and analysis.test_run_ids == ["T04"]
    assert analysis.hardware_items == ["INJ14"]
    assert analysis.external_allowed is False  # asked, but the user's groups are not allowed
    assert analysis.constraints[0]["dimension"] == "[time]" and analysis.warnings == [
        "unit 'zorks' of constraint x not recognized"
    ]
    allowed = resolve(raw, index(), user_groups=["dcl-external"], external_allowed_groups=["dcl-external"])
    assert allowed.external_allowed is True


def test_analyze_uses_the_versioned_prompt_and_low_thinking():
    client = Client(query_analysis=[{"intents": ["chitchat_or_out_of_scope"], "language": "en"}])
    analysis = asyncio.run(
        analyze(
            client,
            "How are you today?",
            history="",
            state={},
            index=index(),
            user_groups=[],
            external_allowed_groups=[],
        )
    )
    assert analysis.chitchat and analysis.raw.intents == [Intent.CHITCHAT]
    purpose, text, options = client.calls[0]
    assert purpose == "engine.query_analysis" and "Question: How are you today?" in text
    assert str(options["thinking"]) == "low"


SEARCH = ToolResult(
    tool="search_documents",
    result={
        "hits": [
            {"parent_text": "TP07 run T04 steady state 12.5 bar per table 3."},
            {"parent_text": "Moog valve rated 300 bar."},
        ]
    },
    provenance=[
        Source(
            doc_id=uuid.uuid4(),
            anchor="page:8:abcdef0123456789",
            title="Test Report 07",
            label="Test Report 07, p. 8",
            provenance=Provenance.INTERNAL_REPORT,
        ),
        Source(label="Moog datasheet, p. 2", provenance=Provenance.VENDOR_CLAIM, anchor="page:2:"),
    ],
    display="...",
)
TELEMETRY = ToolResult(
    tool="query_telemetry",
    result={},
    display="TP07_T04 steady_mean 12.4 bar(a) over +1.0 s to +9.8 s",
    provenance=[Source(label="run TP07_T04", provenance=Provenance.MEASURED)],
)


def test_evidence_items_split_search_hits():
    items = evidence_items([SEARCH, TELEMETRY])
    assert [(i.id, i.tool) for i in items] == [
        ("E1", "search_documents"),
        ("E2", "search_documents"),
        ("E3", "query_telemetry"),
    ]
    assert items[1].source.provenance is Provenance.VENDOR_CLAIM


def synthesis(claims, markdown):
    return {"answer_markdown": markdown, "claims": claims, "caveats": [], "followups": []}


def test_verified_answer_maps_evidence_ids_to_citations():
    good = [
        {
            "text": "Steady-state mean 12.4 bar(a) over +1.0 to +9.8 s.",
            "kind": "numeric",
            "evidence_ids": ["E3"],
        },
        {"text": "The report table lists 12.5 bar.", "kind": "numeric", "evidence_ids": ["E1"]},
    ]
    client = Client(
        synthesis=[
            synthesis(
                good,
                "Steady-state mean 12.4 bar(a) over +1.0 to +9.8 s. [E3] "
                "The report table lists 12.5 bar. [E1]",
            )
        ],
        verify=[
            {
                "verdicts": [
                    {"claim_index": 0, "verdict": "entailed", "reason": "stated"},
                    {"claim_index": 1, "verdict": "entailed", "reason": "stated"},
                ]
            }
        ],
    )
    out = asyncio.run(answer(client, "steady state Pc of TP07 T04?", {}, [SEARCH, TELEMETRY]))
    assert out.passes == 1 and out.numeric_mismatches == []
    assert [c.label for c in out.citations] == ["run TP07_T04", "Test Report 07, p. 8"]
    assert out.summary() == {"claims": 2, "entailed": 2, "contradicted": 0, "not_supported": 0}
    assert str(client.calls[0][2]["thinking"]) == "high"


def test_a_rounded_number_is_repaired_alone_and_removed_if_it_persists():
    rounded = [{"text": "Steady-state mean 12 bar(a).", "kind": "numeric", "evidence_ids": ["E3"]}]
    entailed = {"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "ok"}]}
    client = Client(
        synthesis=[synthesis(rounded, "Steady-state mean 12 bar(a). [E3]")],
        repair=[{"claims": [{"index": 0, "text": "Steady-state mean 12 bar(a).", "evidence_ids": ["E3"]}]}],
        verify=[entailed] * 2,
    )
    out = asyncio.run(answer(client, "q", {}, [TELEMETRY]))
    assert out.passes == 2
    repair_prompt = client.calls[2][1]
    assert [c[0] for c in client.calls] == [
        "engine.synthesis",
        "engine.verify",
        "engine.repair",
        "engine.verify",
    ]
    assert "Claim 0: Steady-state mean 12 bar(a)." in repair_prompt and "[E1] TP07_T04" in repair_prompt
    assert str(client.calls[2][2]["thinking"]) == "medium"
    assert out.claims == [] and "12 bar(a)" not in out.markdown
    assert any("could not be verified" in c for c in out.caveats)


def test_contradicted_claim_is_fixed_on_the_second_pass():
    wrong = [{"text": "The valve is rated 400 bar.", "kind": "factual", "evidence_ids": ["E2"]}]
    good = "The valve is rated 300 bar (vendor claim)."
    client = Client(
        synthesis=[synthesis(wrong, "The valve is rated 400 bar. [E2]")],
        repair=[{"claims": [{"index": 0, "text": good, "evidence_ids": ["E2"]}]}],
        verify=[
            {"verdicts": [{"claim_index": 0, "verdict": "contradicted", "reason": "says 300"}]},
            {"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]},
        ],
    )
    out = asyncio.run(answer(client, "q", {}, [SEARCH]))
    assert out.passes == 2 and out.markdown.startswith("The valve is rated 300 bar")
    assert out.citations[0].provenance is Provenance.VENDOR_CLAIM


@pytest.mark.parametrize("ids", [[], ["E9"]])
def test_claims_citing_nothing_real_produce_no_citations(ids):
    claims = [{"text": "Something general.", "kind": "factual", "evidence_ids": ids}]
    client = Client(
        synthesis=[synthesis(claims, "Something general.")],
        verify=[{"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "-"}]}],
    )
    out = asyncio.run(answer(client, "q", {}, [SEARCH]))
    assert out.citations == []


def test_markers_are_renumbered_to_the_citation_events_one_to_one():
    from backend.llm_engine.engine.synthesis import number_citations

    items = evidence_items([SEARCH, TELEMETRY])  # E1 report p.8, E2 Moog p.2, E3 run TP07_T04
    markdown = "Steady 12.4 bar(a) [E3]. The table lists 12.5 bar [E1, E3]. Rated 300 bar [E2]. Note [E7]."
    claims = [Claim(text="x", kind="factual", evidence_ids=["E2"])]
    text, sources = number_citations(markdown, claims, items)
    assert text == "Steady 12.4 bar(a) [1]. The table lists 12.5 bar [2, 1]. Rated 300 bar [3]. Note."
    assert [s.label for s in sources] == ["run TP07_T04", "Test Report 07, p. 8", "Moog datasheet, p. 2"]
    markers = {int(n) for group in re.findall(r"\[([\d, ]+)\]", text) for n in group.split(",")}
    assert markers == set(range(1, len(sources) + 1))  # every marker has an event and every event a marker


def test_a_failed_or_cut_repair_removes_the_claim_instead_of_failing_the_answer():
    from backend.llm_engine.gemini_types import StructuredOutputError

    rounded = [{"text": "Steady-state mean 12 bar(a).", "kind": "numeric", "evidence_ids": ["E3"]}]
    entailed = {"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "ok"}]}
    client = Client(
        synthesis=[synthesis(rounded, "Steady-state mean 12 bar(a). [E3]")],
        repair=[StructuredOutputError("cut at max_output_tokens", raw_text="{")],
        verify=[entailed],
    )
    out = asyncio.run(answer(client, "q", {}, [TELEMETRY]))
    assert out.claims == [] and "12 bar(a)" not in out.markdown
    assert client.calls[2][2]["max_output_tokens"] == 2048
