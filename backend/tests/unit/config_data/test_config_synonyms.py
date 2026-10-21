"""config/aerospace_synonyms.yaml loads, uses only the closed entity types, never maps one
alias to two entities, and keeps the manual's seed pairs together."""

import re
import unicodedata

import jsonschema
import pytest

# 04 §3.2: "the type list is closed; values are open".
ENTITY_TYPES = {"subsystem", "component", "material", "propellant", "catalyst", "sensor_tag",
                "part_number", "test_id", "standard_clause", "person_role", "organization",
                "vendor", "product", "tool_software", "equation", "failure_mode"}

ALIAS = {
    "type": "object",
    "required": ["surface", "lang"],
    "additionalProperties": False,
    "properties": {"surface": {"type": "string", "minLength": 1},
                   "lang": {"type": "string", "pattern": "^([a-z]{2,3}|und)$"}},
}
ENTRY_PROPS = {"canonical": {"type": "string", "minLength": 1},
               "note": {"type": "string"},
               "aliases": {"type": "array", "minItems": 1, "items": ALIAS},
               "sme_confirmed": {"type": "boolean"}}
SCHEMA = {
    "type": "object",
    "required": ["version", "entities", "quantity_terms"],
    "additionalProperties": False,
    "properties": {
        "version": {"const": 1},
        "entities": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["type", "canonical", "aliases", "sme_confirmed"],
            "additionalProperties": False,
            "properties": {"type": {"enum": sorted(ENTITY_TYPES)}, **ENTRY_PROPS}}},
        "quantity_terms": {"type": "array", "items": {
            "type": "object", "required": ["canonical", "aliases", "sme_confirmed"],
            "additionalProperties": False, "properties": ENTRY_PROPS}},
    },
}

@pytest.fixture(scope="module")
def data(load_config):
    return load_config("aerospace_synonyms.yaml")


@pytest.fixture(scope="module")
def resolve(data, canonical_key):
    def lookup(group, type_, surface):
        key = canonical_key(surface)
        hits = [e["canonical"] for e in data[group]
                if e.get("type") == type_ and key in {canonical_key(a["surface"]) for a in e["aliases"]}]
        assert len(hits) <= 1
        return hits[0] if hits else None
    return lookup


def test_schema(data):
    jsonschema.validate(data, SCHEMA)


@pytest.mark.parametrize("group", ["entities", "quantity_terms"])
def test_no_alias_points_to_two_entries_of_one_type(data, canonical_key, group):
    seen = {}
    for e in data[group]:
        for a in e["aliases"]:
            k = (e.get("type"), canonical_key(a["surface"]))
            assert seen.setdefault(k, e["canonical"]) == e["canonical"], f"{a['surface']!r} in two entries"


@pytest.mark.parametrize("group", ["entities", "quantity_terms"])
def test_canonical_resolves_to_itself(data, resolve, group):
    for e in data[group]:
        assert resolve(group, e.get("type"), e["canonical"]) == e["canonical"]


def test_canonicals_unique_per_type(data, canonical_key):
    keys = [(e["type"], canonical_key(e["canonical"])) for e in data["entities"]]
    assert len(keys) == len(set(keys))


def test_surfaces_are_nfc_and_trimmed(data):
    for group in ("entities", "quantity_terms"):
        for e in data[group]:
            for a in e["aliases"]:
                s = a["surface"]
                assert s == unicodedata.normalize("NFC", s) and s == s.strip()


def test_non_english_coverage(data):
    langs = {a["lang"] for g in ("entities", "quantity_terms") for e in data[g] for a in e["aliases"]}
    non_english = langs - {"en", "und"}
    assert {"de", "fr", "ja", "ru", "zh"} <= non_english


def test_lang_tag_matches_script(data):
    # A Cyrillic, kana or Han surface tagged as a Latin-script language is a data-entry slip.
    for g in ("entities", "quantity_terms"):
        for e in data[g]:
            for a in e["aliases"]:
                s, lang = a["surface"], a["lang"]
                if re.search(r"[Ѐ-ӿ]", s):
                    assert lang == "ru", s
                if re.search(r"[぀-ヿ]", s):
                    assert lang == "ja", s
                if lang in ("de", "fr", "es", "it", "en"):
                    assert not re.search(r"[Ѐ-ӿ぀-ヿ一-鿿]", s), s


@pytest.mark.parametrize(
    "type_, a, b",
    [("propellant", "HTP", "H2O2"), ("propellant", "HTP", "hydrogen peroxide"),
     ("propellant", "HTP", "Wasserstoffperoxid"), ("propellant", "ADN", "LMP-103S"),
     ("propellant", "HAN", "AF-M315E"), ("material", "C103", "C-103 Niobium"),
     ("material", "Niob C-103", "C-103")],
)
def test_manual_seed_pairs_resolve_to_one_entity(resolve, type_, a, b):
    # 04 §3.3 step 4 and the 00 glossary list these pairs.
    assert resolve("entities", type_, a) is not None
    assert resolve("entities", type_, a) == resolve("entities", type_, b)


@pytest.mark.parametrize("a, b", [("Isp", "specific impulse"), ("Pc", "chamber pressure")])
def test_manual_quantity_seed_pairs(resolve, a, b):
    assert resolve("quantity_terms", None, a) == resolve("quantity_terms", None, b) is not None


def test_dash_variants_canonicalize_together(resolve):
    assert resolve("entities", "material", "C–103") == "C-103"  # en dash
