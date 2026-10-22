"""T6 external_search: only the sanitized generic need leaves the network (file 07 §6)."""

import asyncio

import pytest

from backend.llm_engine.engine.tools import Provenance
from backend.llm_engine.engine.tools.external import (
    ExternalPolicy,
    ExternalSearchArgs,
    Found,
    external_search,
    parse_arxiv,
)
from backend.llm_engine.gemini_types import (
    Capability,
    CapabilityUnavailable,
    GenerateResult,
    Grounding,
    GroundingSource,
    Usage,
)

POLICY = ExternalPolicy(enabled=True, allowed_groups=("dcl-external",), proprietary_terms=("BlueFlame",))
REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"


class Grounded:
    """Captures every request; replies with a grounded summary, or raises the given error."""

    def __init__(self, error=None):
        self.requests, self.error = [], error

    async def generate(self, *, model, messages, context, schema=None, **options):
        self.requests.append({"messages": messages, "options": options, "purpose": context.purpose})
        if self.error:
            raise self.error
        grounding = Grounding(
            queries=("monolithic catalyst preheat power ADN thruster",),
            sources=(GroundingSource("nasa.gov", REDIRECT), GroundingSource("esa.int", None)),
        )
        return GenerateResult(
            "Monolithic catalysts need 2–5 W of preheat [nasa.gov].",
            None,
            (),
            Usage(1, 1),
            model,
            "stop",
            "r",
            1,
            grounding=grounding,
        )


async def resolved(url):
    return "https://ntrs.nasa.gov/paper" if url == REDIRECT else url


def run(client, args, policy=POLICY, papers=None):
    async def search_arxiv(query):
        search_arxiv.queries.append(query)
        return papers or []

    search_arxiv.queries = []
    result = asyncio.run(
        external_search(
            client, args, policy=policy, trace_id="t", resolve=resolved, search_arxiv=search_arxiv
        )
    )
    return result, search_arxiv.queries


def request_text(request) -> str:
    return "\n".join(part.text for m in request["messages"] for part in m.parts if hasattr(part, "text"))


def test_the_grounded_request_holds_only_the_sanitized_query():
    need = ExternalSearchArgs(
        purpose="general_physics",
        query_intent="BlueFlame catalyst preheat for TP07 T04 at 12.37 bar, Manastu INJ-14 monolith",
    )
    client = Grounded()
    result, _ = run(client, need)
    [request] = client.requests
    sent = request_text(request)
    for leaked in ("BlueFlame", "TP07", "T04", "12.37", "Manastu", "INJ-14"):
        assert leaked not in sent
    assert request["options"]["google_search"] is True
    assert len(request["messages"]) == 2  # the fixed instruction and the query; no history, no evidence
    record = result.result["external_queries"][0]
    assert record["provider"] == "google_search" and record["sanitized"] in sent
    assert record["google_queries"] == ["monolithic catalyst preheat power ADN thruster"]
    assert len(record["original_sha256"]) == 64 and "BlueFlame" not in str(result.result)


def test_results_are_web_sources_with_resolved_urls():
    result, _ = run(
        Grounded(), ExternalSearchArgs(purpose="cots_component", query_intent="space solenoid valve 300 bar")
    )
    assert [s.provenance for s in result.provenance] == [Provenance.WEB, Provenance.WEB]
    assert result.provenance[0].url == "https://ntrs.nasa.gov/paper" and result.provenance[1].url is None
    assert result.result["hits"][0]["parent_text"].startswith("Monolithic catalysts need 2–5 W")
    assert "[external]" in result.display and result.result["external_queries"][0]["result_count"] == 2


def test_a_refused_need_is_never_sent():
    client = Grounded()
    result, papers = run(client, ExternalSearchArgs(purpose="literature", query_intent="TP07 T04 INJ-14"))
    assert client.requests == [] and papers == []
    assert result.provenance == [] and "refused" in result.warnings[0]
    assert result.result["external_queries"][0]["refused"]


def test_literature_also_searches_arxiv():
    paper = Found(
        "ADN monopropellant thrusters", "http://arxiv.org/abs/1", "ADN ... (A, 2024).", Provenance.LITERATURE
    )
    result, queries = run(
        Grounded(),
        ExternalSearchArgs(purpose="literature", query_intent="ADN thruster catalyst"),
        papers=[paper],
    )
    assert queries and "ADN" in queries[0]
    assert Provenance.LITERATURE in [s.provenance for s in result.provenance]
    assert [q["provider"] for q in result.result["external_queries"]] == ["google_search", "arxiv"]


@pytest.mark.parametrize(("purpose", "arxiv_used"), [("literature", True), ("standard_text", False)])
def test_without_grounding_literature_falls_back_to_arxiv_and_others_say_so(purpose, arxiv_used):
    client = Grounded(error=CapabilityUnavailable(Capability.GOOGLE_SEARCH))
    paper = Found("p", "http://arxiv.org/abs/2", "text", Provenance.LITERATURE)
    result, queries = run(
        client,
        ExternalSearchArgs(purpose=purpose, query_intent="ECSS propulsion test requirements"),
        papers=[paper],
    )
    assert bool(queries) is arxiv_used
    assert any("grounding unavailable" in w for w in result.warnings)
    assert (len(result.provenance) == 1) is arxiv_used


def test_benchmark_mock_makes_no_call():
    client = Grounded()
    mock = ExternalPolicy(enabled=True, allowed_groups=("g",), mode="mock")
    result, queries = run(
        client, ExternalSearchArgs(purpose="literature", query_intent="ADN thruster catalyst"), policy=mock
    )
    assert client.requests == [] and queries == []
    assert result.result["external_queries"][0]["provider"] == "mock" and result.provenance


def test_policy_needs_switch_mode_and_group():
    assert POLICY.allows(["dcl-external"]) and not POLICY.allows(["dcl-engineers"])
    assert not ExternalPolicy(enabled=False, allowed_groups=("g",)).allows(["g"])
    assert not ExternalPolicy(allowed_groups=("g",), mode="off").allows(["g"])


def test_arxiv_atom_is_parsed_into_literature():
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.1</id>
    <title>Green  monopropellant
    thrusters</title><summary>We test ADN.</summary><published>2024-01-02T00:00:00Z</published>
    <author><name>A. One</name></author><author><name>B. Two</name></author></entry></feed>"""
    [paper] = parse_arxiv(atom)
    assert paper.title == "Green monopropellant thrusters" and paper.url == "http://arxiv.org/abs/2401.1"
    assert paper.snippet.startswith(
        "Green monopropellant thrusters (A. One, B. Two, 2024-01-02). We test ADN."
    )


def test_arxiv_retries_with_any_word_when_all_words_find_nothing():
    import httpx

    from backend.llm_engine.engine.tools.external import arxiv

    empty = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    one = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/9</id>'
        "<title>Catalyst beds</title><summary>s</summary></entry></feed>"
    )
    seen = []

    def handler(request):
        seen.append(request.url.params["search_query"])
        return httpx.Response(200, text=empty if " AND " in seen[-1] else one)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await arxiv("ADN catalyst preheat", http=http)

    [paper] = asyncio.run(go())
    assert seen == ["all:ADN AND all:catalyst AND all:preheat", "all:ADN OR all:catalyst OR all:preheat"]
    assert paper.title == "Catalyst beds"
