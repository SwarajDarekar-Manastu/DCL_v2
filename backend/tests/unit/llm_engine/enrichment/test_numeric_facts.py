import pytest

from backend.llm_engine.enrichment.extract import NumericExtract
from backend.llm_engine.enrichment.numeric_facts import (
    DroppedFact,
    DropReason,
    FactDecision,
    NumberLocale,
    fact_source,
    parse_number,
    validate_fact,
)
from backend.postgres.enums import DocKind, GaugeOrAbs, NodeSource, NumericFactSource, SourceOrigin

RANGES = [  # S5's shape (config/sanity_ranges.yaml v2): one checks_external_kept range per quantity, last
    {"id": "chamber_pressure", "physical_quantity": "pressure", "unit": "bar", "min": 0, "max": 150},
    {"id": "valve_pressure", "physical_quantity": "pressure", "unit": "bar", "min": 0, "max": 400},
    {
        "id": "pressure",
        "physical_quantity": "pressure",
        "unit": "bar",
        "min": 0,
        "max": 700,
        "checks_external_kept": True,
    },
    {
        "id": "temperature",
        "physical_quantity": "temperature",
        "unit": "K",
        "min": 200,
        "max": 2000,
        "checks_external_kept": True,
    },
]
TEXT = "Der Kammerdruck stieg auf 12,4 bar(g); das Bett erreichte 600 °C."


def fact(value, unit, quantity="pressure", span=TEXT, label="chamber pressure"):
    return NumericExtract(
        quantity=quantity, quantity_label=label, value=value, unit=unit, context="c", span=span
    )


def check(f, locale=NumberLocale.COMMA, external=False):
    return validate_fact(
        f,
        node_ref="n1",
        node_text=TEXT,
        locale=locale,
        source=NumericFactSource.PRINTED,
        ranges=RANGES,
        external=external,
    )


@pytest.mark.parametrize(
    ("value", "locale", "number", "ambiguous"),
    [
        ("12,4", NumberLocale.COMMA, 12.4, False),
        ("1.234,5", NumberLocale.COMMA, 1234.5, False),
        ("1.234", NumberLocale.COMMA, 1234.0, True),
        ("1,234.5", NumberLocale.DOT, 1234.5, False),
        ("1,234", NumberLocale.DOT, 1234.0, False),
        ("−3.5", NumberLocale.DOT, -3.5, False),
    ],
)
def test_locale_aware_number_parsing(value, locale, number, ambiguous):
    assert parse_number(value, locale) == (number, ambiguous)


@pytest.mark.parametrize("value", ["12.4.5", "abc", "1,23,4"])
def test_malformed_numbers_raise(value):
    with pytest.raises(ValueError):
        parse_number(value, NumberLocale.DOT)


def test_comma_document_gauge_pressure_converts_with_provenance():
    out = check(fact("12,4", "bar(g)"))
    assert isinstance(out, FactDecision)
    assert (out.value_si, out.unit_si, out.gauge_or_abs) == (12.4, "bar", GaugeOrAbs.GAUGE)
    assert (out.value_raw, out.unit_raw, out.span_start, out.span_end) == ("12,4", "bar(g)", 0, len(TEXT))
    assert not out.suspect and not out.needs_unit


def test_temperature_goes_to_kelvin():
    out = check(fact("600", "°C", quantity="temperature"))
    assert (round(out.value_si, 2), out.unit_si) == (873.15, "kelvin")


def test_unit_of_the_wrong_dimension_drops_the_fact():
    out = check(fact("12,4", "N"))
    assert isinstance(out, DroppedFact) and out.reason is DropReason.DIMENSION_MISMATCH


@pytest.mark.parametrize("unit", [None, "Skt.", "dB²", "dB^2"])  # dB²: Atlas, 2026-10-28
def test_missing_or_unreadable_unit_keeps_the_number_with_needs_unit(unit):
    out = check(fact("12,4", unit))
    assert isinstance(out, FactDecision) and out.needs_unit and out.value_si is None


def test_out_of_range_and_locale_ambiguous_values_are_suspect():
    assert check(fact("900", "bar")).suspect
    assert check(fact("1.234", "bar")).suspect


@pytest.mark.parametrize(
    ("value", "label", "external", "suspect"),
    [
        ("300", "peak chamber pressure", False, True),  # internal chamber fact: 0-150 bar
        ("300", "valve pressure rating", False, False),  # internal valve fact: 0-400 bar
        ("300", "inlet pressure", False, False),  # no role known: last range, 0-700 bar
        ("300", "chamber pressure", True, False),  # library document: the checks_external_kept range
        ("800", "rated pressure", True, True),
    ],
)
def test_sanity_range_follows_origin_and_role(value, label, external, suspect):
    assert check(fact(value, "bar", label=label), external=external).suspect is suspect


@pytest.mark.parametrize(
    ("origin", "kind", "expected"),
    [
        (SourceOrigin.EXTERNAL_KEPT, DocKind.DATASHEET, NumericFactSource.VENDOR_CLAIM),
        (SourceOrigin.EXTERNAL_KEPT, DocKind.ACADEMIC_PAPER, NumericFactSource.LITERATURE),
        (SourceOrigin.INTERNAL, DocKind.TEST_REPORT, NumericFactSource.PRINTED),
    ],
)
def test_external_numbers_are_never_labelled_as_measured(origin, kind, expected):
    assert fact_source(NodeSource.PRINTED, origin, kind) == expected


def test_ocr_and_vlm_nodes_keep_their_extraction_source():
    assert fact_source(NodeSource.VLM, SourceOrigin.INTERNAL, DocKind.TEST_REPORT) == NumericFactSource.VLM
    assert fact_source(NodeSource.OCR, SourceOrigin.INTERNAL, DocKind.TEST_REPORT) == NumericFactSource.OCR
