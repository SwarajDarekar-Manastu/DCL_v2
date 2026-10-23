"""On-the-fly translation: one call for the missing passages, cached by content hash, never without cloud."""

import pytest

from backend.llm_engine.enrichment.translate import TranslationRefused, translate_passages
from backend.llm_engine.gemini_types import GenerateResult, Usage


class Cache:
    def __init__(self):
        self.objects = {}

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, data):
        self.objects[key] = data


class Client:
    def __init__(self):
        self.calls = []

    def generate_sync(self, *, model, messages, context, schema, **options):
        self.calls.append((messages, context, options))
        user = messages[1].parts[0].text
        count = user.count("<<<")
        parsed = schema.model_validate({"translations": [f"EN {i}" for i in range(1, count + 1)]})
        return GenerateResult("", parsed, (), Usage(1, 1), model, "stop", "r", 1)


GERMAN = ["Der Kammerdruck betrug 12,4 bar.", "Nennschub 10 N."]


def test_missing_passages_go_in_one_call_and_come_back_from_the_cache():
    cache, client = Cache(), Client()
    first = translate_passages(client, cache, GERMAN, source_language="de", cloud_allowed=True, doc_id="d")
    assert [t.text for t in first] == ["EN 1", "EN 2"] and not any(t.cached for t in first)
    [(messages, context, options)] = client.calls
    assert "German" in messages[1].parts[0].text and "12,4 bar" in messages[1].parts[0].text
    assert "English" in messages[0].parts[0].text and context.purpose == "enrichment.translate"
    again = translate_passages(client, cache, GERMAN, source_language="de", cloud_allowed=False)
    assert [t.text for t in again] == ["EN 1", "EN 2"] and all(t.cached for t in again)
    assert len(client.calls) == 1  # cached: no second call, so no cloud permission needed either


def test_no_cloud_no_call_and_english_passes_through():
    with pytest.raises(TranslationRefused):
        translate_passages(Client(), Cache(), GERMAN, source_language="de", cloud_allowed=False)
    client = Client()
    same = translate_passages(
        client, Cache(), ["Chamber pressure 12.4 bar."], source_language="en", cloud_allowed=True
    )
    assert same[0].text == "Chamber pressure 12.4 bar." and client.calls == []
