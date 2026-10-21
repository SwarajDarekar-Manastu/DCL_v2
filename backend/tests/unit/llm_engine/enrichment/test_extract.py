import pytest

from backend.config import ThinkingLevel
from backend.llm_engine.enrichment.extract import ParentEnrichment, enrich_parent, ground
from backend.llm_engine.gemini_types import GenerateResult, Usage

TEXT = (
    "Hot fire 3 of TP37 used injector INJ-14 with HTP 90%. "
    "Der Kammerdruck stieg auf 12,4 bar. The test was nominal per ECSS-E-ST-35C."
)
RAW = {
    "summary": "Hot fire 3 of TP37 reached 12.4 bar chamber pressure.",
    "section_kind": "results",
    "entities": [
        {"type": "component", "surface": "INJ-14", "normalized_hint_en": "INJ-14"},
        {"type": "propellant", "surface": "HTP", "normalized_hint_en": "HTP"},
        {"type": "material", "surface": "C-103", "normalized_hint_en": "C-103"},
    ],
    "numeric_facts": [
        {
            "quantity": "pressure",
            "quantity_label": "chamber pressure",
            "value": "12,4",
            "unit": "bar",
            "context": "chamber pressure",
            "span": "Der Kammerdruck stieg auf 12,4 bar.",
        },
        {
            "quantity": "pressure",
            "quantity_label": "chamber pressure",
            "value": "12.4",
            "unit": "bar",
            "context": "normalized by the model",
            "span": "Der Kammerdruck stieg auf 12,4 bar.",
        },
        {
            "quantity": "force",
            "quantity_label": "thrust",
            "value": "5",
            "unit": "N",
            "context": "thrust",
            "span": "Thrust was 5 N.",
        },
    ],
    "test_ids_mentioned": ["TP37", "TP38"],
    "standards_mentioned": ["ECSS-E-ST-35C"],
    "status_markers": ["nominal"],
    "claims": [
        {"text": "The test was nominal.", "span": "The test was nominal per ECSS-E-ST-35C."},
        {"text": "The bed survived.", "span": "The bed survived."},
    ],
    "questions_answered": ["What chamber pressure did TP37 hot fire 3 reach?"],
}


def test_grounding_keeps_only_what_the_text_states_and_counts_the_drops():
    grounded, drops = ground(ParentEnrichment.model_validate(RAW), TEXT)
    assert [e.surface for e in grounded.entities] == ["INJ-14", "HTP"]
    assert [f.value for f in grounded.numeric_facts] == ["12,4"]
    assert [c.text for c in grounded.claims] == ["The test was nominal."]
    assert grounded.test_ids_mentioned == ["TP37"]
    assert grounded.standards_mentioned == ["ECSS-E-ST-35C"]
    assert (drops.entities, drops.numeric_facts, drops.claims, drops.identifiers) == (1, 2, 1, 1)
    assert drops.kept == 6
    assert drops.rate == pytest.approx(5 / 11)


def test_grounding_ignores_case_and_spacing():
    raw = ParentEnrichment.model_validate({**RAW, "entities": [{"type": "component", "surface": "inj-14"}]})
    grounded, _ = ground(raw, "Injector  INJ-14 was\nused.")
    assert len(grounded.entities) == 1


class Client:
    def __init__(self):
        self.calls = []

    def generate_sync(self, *, model, messages, context, schema, **options):
        self.calls.append(
            {"model": model, "messages": messages, "context": context, "schema": schema, **options}
        )
        return GenerateResult(
            text="",
            parsed=schema.model_validate(RAW),
            tool_calls=(),
            usage=Usage(1, 1),
            model=model,
            finish_reason="stop",
            request_id="r1",
            latency_ms=1,
        )


def test_one_call_per_parent_with_versioned_prompt_context_and_low_thinking():
    client = Client()
    out = enrich_parent(
        client,
        TEXT,
        context="Test Report 37 · test_report · internal",
        language="de",
        doc_id="doc-1",
        anchor="page:3:abcd1234abcd1234",
    )
    (call,) = client.calls
    assert call["model"] == "gemini-3.8-flash"
    assert (call["thinking"], call["temperature"]) == (ThinkingLevel.LOW, 0.0)
    assert (call["context"].purpose, call["context"].prompt_version) == ("enrichment.parent", "parent.v1")
    assert (call["context"].doc_id, call["context"].node_anchor) == ("doc-1", "page:3:abcd1234abcd1234")
    system, user = call["messages"]
    assert "Write every free-text field in English" in system.parts[0].text
    assert TEXT in user.parts[0].text and "Section language: de" in user.parts[0].text
    assert out.warnings == ["drop rate 45% above 10%"]
