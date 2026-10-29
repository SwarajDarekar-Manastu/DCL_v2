import uuid

import pytest

from backend.dispatcher.contract import Flag, Mention
from backend.indexing.index_document import HaltedDocument, index_document
from backend.llm_engine.enrichment.entities import index_from_seed, load_seed
from backend.llm_engine.gemini_types import GenerateResult, StructuredOutputError, Usage
from backend.postgres.enums import DocKind, FlagSeverity, FlagType, MentionSource, NodeType, Route

DOC_ID = uuid.UUID("6f1c2a3e-0000-4000-8000-0000000000aa")
RESULTS = (
    "Hot fire 3 of TP37 used injector INJ-14 with HTP 90%. The chamber pressure reached 12.4 bar. "
    + " ".join(f"Filler sentence {i} about the campaign logistics and planning." for i in range(60))
    + " Transducer PT-101 read the C-103 nozzle temperature at 900 K."
)


class Gemini:
    """Enriches by keyword, like a model that only reports what the parent says."""

    def __init__(self, fail_on: str | None = None):
        self.calls = 0
        self.fail_on = fail_on

    def generate_sync(self, *, model, messages, context, schema, **options):
        self.calls += 1
        text = messages[-1].parts[0].text
        if self.fail_on and self.fail_on in text:
            raise StructuredOutputError("bad reply", raw_text="{}")
        entities, facts = [], []
        for etype, surface in [
            ("component", "INJ-14"),
            ("propellant", "HTP"),
            ("material", "C-103"),
            ("sensor_tag", "PT-101"),
        ]:
            if surface in text:
                entities.append({"type": etype, "surface": surface, "normalized_hint_en": surface})
        if "12.4 bar" in text:
            facts.append(
                {
                    "quantity": "pressure",
                    "quantity_label": "chamber pressure",
                    "value": "12.4",
                    "unit": "bar",
                    "context": "chamber pressure",
                    "span": "The chamber pressure reached 12.4 bar.",
                }
            )
        if "900 K" in text:
            facts.append(
                {
                    "quantity": "temperature",
                    "quantity_label": "nozzle temperature",
                    "value": "900",
                    "unit": "K",
                    "context": "nozzle temperature",
                    "span": "Transducer PT-101 read the C-103 nozzle temperature at 900 K.",
                }
            )
        parsed = schema.model_validate(
            {
                "summary": "TP37 hot fire 3 reached 12.4 bar.",
                "section_kind": "results",
                "entities": entities,
                "numeric_facts": facts,
                "test_ids_mentioned": ["TP37"] if "TP37" in text else [],
                "questions_answered": ["What chamber pressure did TP37 reach?"],
            }
        )
        return GenerateResult(
            text="",
            parsed=parsed,
            tool_calls=(),
            usage=Usage(1, 1),
            model=model,
            finish_reason="stop",
            request_id="r",
            latency_ms=1,
        )


class Embedder:
    def __init__(self):
        self.calls = 0
        self.texts = []

    def __call__(self, texts, titles):
        self.calls += 1
        self.texts.extend(texts)
        return [[1.0] + [0.0] * 767 for _ in texts]


@pytest.fixture
def run(kit):
    seed = load_seed()

    def go(doc=None, *, gemini=None, reuse=None, cloud_allowed=True, embedder=None):
        doc = doc or kit.document(
            kit.node(
                "intro", "Scope of the test campaign.", 0, breadcrumb="Test Report 37 › 1 Scope", page_no=1
            ),
            kit.node("res", RESULTS, 1, page_no=8),
        )
        return index_document(
            doc,
            doc_id=DOC_ID,
            gemini=gemini or Gemini(),
            embed_documents=embedder or Embedder(),
            embed_images=None,
            asset_bytes=None,
            alias_index=index_from_seed(seed),
            reuse_vectors=lambda hashes: {h: reuse[h] for h in hashes if h in reuse} if reuse else {},
            sanity_ranges=[],
            cloud_allowed=cloud_allowed,
            count_tokens=kit.words,
        )

    return go


def test_a_document_with_a_hard_flag_is_refused(kit, run):
    doc = kit.document(kit.node("a", "text", 0, page_no=1)).model_copy(
        update={"flags": [Flag(flag_type=FlagType.PARSE_FAILURE, severity=FlagSeverity.HARD)]}
    )
    with pytest.raises(HaltedDocument):
        run(doc)


def test_one_enrichment_call_per_parent(run):
    gemini = Gemini()
    plan = run(gemini=gemini)
    parents = [n for n in plan.nodes if n.node_type is NodeType.PARENT]
    assert gemini.calls == len(parents) == plan.metrics["enrichment_calls"] == 2


def test_unchanged_embed_texts_reuse_their_vectors(run):
    first_embedder = Embedder()
    first = run(embedder=first_embedder)
    embedded = [n for n in first.nodes if n.embed]
    # every embedded piece, plus the file's card (indexing/card.py)
    assert first.metrics["vectors_computed"] == len(embedded) == len(first_embedder.texts) - 1
    reuse = {n.embed_text_hash: n.embedding for n in embedded}
    again_embedder = Embedder()
    again = run(embedder=again_embedder, reuse=reuse)
    assert (again.metrics["vectors_reused"], again.metrics["vectors_computed"], again_embedder.calls) == (
        len(embedded),
        0,
        1,  # only the card
    )
    assert all(n.embedding for n in again.nodes if n.embed)


def test_entities_and_facts_land_on_the_child_that_contains_them(run):
    plan = run()
    by_ref = {n.ref: n for n in plan.nodes}
    pt101 = next(m for m in plan.entities.mentions if m.surface == "PT-101" and m.source == MentionSource.LLM)
    assert by_ref[pt101.node_ref].node_type is NodeType.CHILD and "PT-101" in by_ref[pt101.node_ref].content
    nozzle = next(f for f in plan.facts if f.quantity == "temperature")
    holder = by_ref[nozzle.node_ref]
    assert holder.node_type is NodeType.CHILD and "900 K" in holder.content
    assert (nozzle.value_si, nozzle.unit_si) == (900.0, "kelvin")


def test_seeded_entities_resolve_and_new_ones_are_created(run):
    plan = run()
    refs = {m.surface: m.entity for m in plan.entities.mentions}
    assert refs["C-103"] == ("material", "c-103") and refs["HTP"] == ("propellant", "htp")
    assert {e.canonical_name for e in plan.entities.new_entities} >= {"INJ-14", "PT-101"}


def test_route_mentions_map_to_chunk_nodes_and_non_entity_kinds_are_skipped(kit, run):
    doc = kit.document(kit.node("res", RESULTS, 0, page_no=8)).model_copy(
        update={
            "mentions": [
                Mention(node_ref="res", kind="sensor_tag", surface="PT-101"),
                Mention(node_ref="res", kind="reference", surface="Smith 2021"),
            ]
        }
    )
    plan = run(doc)
    regex = [m for m in plan.entities.mentions if m.source == MentionSource.REGEX]
    assert [m.surface for m in regex] == ["PT-101"]
    holder = next(n for n in plan.nodes if n.ref == regex[0].node_ref)
    assert holder.node_type is NodeType.CHILD and "PT-101" in holder.content
    assert plan.metrics["route_mentions_skipped"] == 1


def test_question_proxies_for_every_enriched_kind(kit, run):
    plan = run()
    proxies = [n for n in plan.nodes if n.node_type is NodeType.QUESTION_PROXY]
    parent_refs = {n.ref for n in plan.nodes if n.node_type is NodeType.PARENT}
    assert proxies and {p.parent_ref for p in proxies} <= parent_refs
    assert all(p.embed and p.embedding for p in proxies)
    doc = kit.document(kit.node("res", RESULTS, 0, page_no=8))
    for kind in (DocKind.UNKNOWN, DocKind.RISK_ASSESSMENT):
        other = doc.model_copy(update={"document": doc.document.model_copy(update={"doc_kind": kind})})
        assert [n for n in run(other).nodes if n.node_type is NodeType.QUESTION_PROXY]


class SectionSummaries(Gemini):
    """Each section gets its own summary, as a model reading only that section would write."""

    def generate_sync(self, **kwargs):
        result = super().generate_sync(**kwargs)
        if "Scope of the test campaign" in kwargs["messages"][-1].parts[0].text:
            result.parsed.summary = "The campaign scope."
        return result


def test_every_piece_carries_its_own_sections_summary_and_the_files_category(run):
    plan = run(gemini=SectionSummaries())
    about = {
        n.parent_ref or n.ref: n.embed_text.split("---")[0]
        for n in plan.nodes
        if n.embed and n.node_type in (NodeType.CHILD, NodeType.PARENT)
    }
    assert sum("About: The campaign scope." in h for h in about.values()) == 1
    assert sum("About: TP37 hot fire 3 reached 12.4 bar." in h for h in about.values()) == 1
    assert all(h.startswith("Doc: Test Report 37 (test_report, results,") for h in about.values())


def test_document_aggregation_and_search_text(run):
    plan = run()
    enrichment = plan.document["enrichment"]
    assert enrichment["test_ids"] == ["TP37"]
    assert "C-103" in enrichment["materials"] and "HTP" in enrichment["propellants"]
    assert plan.document["search_text"].startswith(
        "Test Report 37\nKind: test_report · results · internal\nTest: plan TP37\n"
        "Summary: TP37 hot fire 3 reached 12.4 bar."
    )
    assert "Entities: INJ-14, HTP, C-103, PT-101" in plan.document["search_text"]
    assert "Contains: 1 Scope; 3 Results" in plan.document["search_text"]
    assert "TP37" in plan.document["card_codes"].split() and len(plan.document["card_embedding"]) > 0
    assert set(plan.document["entity_refs"]) >= {("material", "c-103"), ("propellant", "htp")}


def test_contextual_headers_name_the_entities(run):
    plan = run()
    child = next(n for n in plan.nodes if n.node_type is NodeType.CHILD and "PT-101" in n.content)
    assert "Entities: " in child.embed_text and "PT-101" in child.embed_text.split("---")[0]


def test_without_cloud_permission_no_gemini_call_happens(run):
    gemini = Gemini()
    plan = run(gemini=gemini, cloud_allowed=False)
    assert gemini.calls == 0
    assert plan.warnings == ["cloud processing not allowed for this root: no enrichment"]
    assert plan.entities.mentions == [] and plan.facts == []
    assert all(n.embedding for n in plan.nodes if n.embed)


def test_a_failed_enrichment_reply_skips_only_that_parent(run):
    plan = run(gemini=Gemini(fail_on="Scope of the test campaign"))
    assert plan.metrics["enrichment_calls"] == 1
    assert any("failed the schema" in w for w in plan.warnings)


def test_route_b_sends_nothing_to_a_model_even_for_text_parents(kit, run):
    gemini = Gemini()
    doc = kit.document(kit.node("readme", RESULTS, 0)).model_copy(update={"route": Route.B})
    plan = run(doc, gemini=gemini)
    assert [n for n in plan.nodes if n.node_type is NodeType.PARENT]
    assert (gemini.calls, plan.metrics["enrichment_calls"], plan.warnings) == (0, 0, [])
    assert all(n.embedding for n in plan.nodes if n.embed)
