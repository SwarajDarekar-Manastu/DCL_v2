import uuid

import pytest

from backend.llm_engine.enrichment.entities import canonical_key, index_from_seed, load_seed, normalize
from backend.llm_engine.enrichment.extract import EntityExtract
from backend.postgres.enums import AliasCreatedBy, EntityType

DOC = uuid.UUID("6f1c2a3e-0000-4000-8000-000000000001")


@pytest.fixture(scope="module")
def seed():
    return load_seed()


@pytest.mark.parametrize(
    ("surface", "key"),
    [
        ("C 103", "c-103"),
        ("C103", "c-103"),
        ("c‑103.", "c-103"),
        ("PT 101", "pt-101"),
        ("  Wasser  stoff ", "wasser stoff"),
    ],
)
def test_canonical_key(surface, key):
    assert canonical_key(surface) == key


def resolve(index, *extracts, languages=None, text="x"):
    pairs = [("n1", e) for e in extracts]
    return normalize(pairs, {"n1": text}, index, doc_id=DOC, languages=languages or {})


@pytest.mark.parametrize("surface", ["C103", "C 103", "c-103", "C-103 Niobium"])
def test_spelling_variants_resolve_to_the_seeded_c103(seed, surface):
    decisions = resolve(index_from_seed(seed), EntityExtract(type="material", surface=surface))
    assert decisions.new_entities == []
    assert decisions.mentions[0].entity == ("material", "c-103")


def test_german_surface_resolves_to_htp_through_the_seed(seed):
    decisions = resolve(index_from_seed(seed), EntityExtract(type="propellant", surface="Wasserstoffperoxid"))
    assert decisions.mentions[0].entity == ("propellant", "htp")
    assert decisions.new_aliases == []


def test_unknown_surface_with_a_known_hint_gets_a_new_alias(seed):
    extract = EntityExtract(type="propellant", surface="Peroxyd", normalized_hint_en="HTP")
    decisions = resolve(index_from_seed(seed), extract)
    assert decisions.new_entities == []
    (alias,) = decisions.new_aliases
    assert (alias.alias, alias.entity, alias.created_by) == (
        "Peroxyd",
        ("propellant", "htp"),
        AliasCreatedBy.SYSTEM_EXACT,
    )


def test_close_spelling_matches_fuzzily_and_records_the_score(seed):
    decisions = resolve(index_from_seed(seed), EntityExtract(type="material", surface="C-103 niobium alloys"))
    (alias,) = decisions.new_aliases
    assert alias.created_by == AliasCreatedBy.SYSTEM_FUZZY and alias.fuzzy_score >= 92
    assert alias.entity == ("material", "c-103")


def test_new_entity_in_german_text_takes_the_english_hint_as_canonical(seed):
    extract = EntityExtract(type="component", surface="Heizwendel", normalized_hint_en="heater coil")
    decisions = resolve(index_from_seed(seed), extract, languages={"n1": "de"})
    (new,) = decisions.new_entities
    assert (new.canonical_name, new.canonical_key, new.first_seen_doc_id) == (
        "heater coil",
        "heater coil",
        DOC,
    )
    (alias,) = decisions.new_aliases
    assert (alias.alias, alias.entity) == ("Heizwendel", ("component", "heater coil"))


def test_a_new_entity_is_reused_by_later_mentions_in_the_same_document(seed):
    a = EntityExtract(type="component", surface="PHP coil")
    b = EntityExtract(type="component", surface="php coil")
    decisions = resolve(index_from_seed(seed), a, b, text="The PHP coil heated; the php coil failed.")
    assert len(decisions.new_entities) == 1 and len(decisions.new_aliases) == 1
    assert decisions.mentions[0].entity == decisions.mentions[1].entity
    assert (decisions.mentions[0].span_start, decisions.mentions[0].span_end) == (4, 12)


def test_types_never_mix(seed):
    decisions = resolve(index_from_seed(seed), EntityExtract(type=EntityType.VENDOR, surface="C-103"))
    assert len(decisions.new_entities) == 1
