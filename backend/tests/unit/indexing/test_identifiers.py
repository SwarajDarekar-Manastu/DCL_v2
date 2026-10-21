import json
from pathlib import Path

import pytest

from backend.indexing.identifiers import content_codes, extract_identifiers

CASES = json.loads((Path(__file__).parent / "identifier_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:30] for c in CASES])
def test_indexer_emits_full_and_dashless_forms(case):
    tokens = extract_identifiers(case["text"])
    for token in case.get("must_have", []):
        assert token in tokens
    for token in case.get("must_not_have", []):
        assert token not in tokens


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:30] for c in CASES])
def test_every_query_wording_hits_the_indexed_codes(case):
    indexed = set(content_codes(case["text"]).split())
    for query in case["queries"]:
        query_tokens = set(extract_identifiers(query))
        assert query_tokens & indexed, f"{query!r} gave {sorted(query_tokens)}; indexed {sorted(indexed)}"


def test_prose_numbers_dates_and_units_are_not_identifiers():
    assert extract_identifiers("12.4 bar at 2024-05-02, 300 s, page 5") == []


def test_tokens_keep_first_seen_order_without_duplicates():
    assert extract_identifiers("PT-101 then pt-101 then PT101") == ["PT-101", "PT101"]


def test_squared_and_cubed_units_are_not_identifiers():
    assert extract_identifiers("12 kgf/cm2, 9.81 m/s2, 5 m3") == []
