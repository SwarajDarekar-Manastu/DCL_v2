from pathlib import Path

import pytest

pdfium = pytest.importorskip("pypdfium2")

from backend.dispatcher.folder_context import build_folder_context  # noqa: E402
from backend.postgres.enums import DocKind, FlagType, SourceOrigin  # noqa: E402
from backend.routes.a1_office.metadata import (  # noqa: E402
    Vendor,
    extract_metadata,
    find_vendor,
    humanize,
    number_locale,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "a1_office"


def page_text(name: str) -> tuple[str, str]:
    (pdf,) = (FIXTURES / name).glob("*.pdf")
    document = pdfium.PdfDocument(pdf.read_bytes())
    return pdf.name, document[0].get_textpage().get_text_range()


def folder(root: str, path: str, file_name: str):
    """As the dispatcher builds it: the library root's sync_roots default origin is external_kept."""
    origin = SourceOrigin.EXTERNAL_KEPT if root == "APS - Library" else SourceOrigin.INTERNAL
    return build_folder_context(root, [root, *path.split("/")], file_name, root_origin=origin)


def meta(name, root, path, *, title=None, furniture=(), languages=("en",), vendors=None, text=None):
    file_name, first = page_text(name)
    first = text if text is not None else first
    return extract_metadata(
        file_name=file_name,
        title=title,
        first_page_text=first,
        full_text=first,
        furniture=list(furniture),
        folder=folder(root, path, file_name),
        page_languages=list(languages),
        page_count=1,
        vendors=vendors,
    )


def test_doi_paper_in_an_internal_folder_becomes_external_literature():
    result = meta(
        "doi_paper",
        "APU",
        "Test Plan 37/literature",
        title="Catalyst bed preheating effects on HTP monopropellant start-up",
    )
    fields = result.fields
    assert fields.external_ids.doi == "10.5555/dcl.fixture.2026.001"
    assert fields.publisher == "Journal of Synthetic Propulsion Fixtures"
    assert (fields.source_origin, fields.doc_kind, fields.trust_tier) == (
        SourceOrigin.EXTERNAL_KEPT,
        DocKind.ACADEMIC_PAPER,
        5,
    )
    assert result.sources["source_origin"] == "doi"
    assert fields.test_plan_id == "TP37"


def test_german_datasheet_keeps_the_library_origin_and_detects_the_comma_locale():
    result = meta(
        "german_datasheet",
        "APS - Library",
        "Vendor brochures/DE",
        title="Datenblatt - Monergol-Triebwerk MT-1",
        languages=("de",),
    )
    fields = result.fields
    assert (fields.source_origin, fields.language, fields.number_locale) == (
        SourceOrigin.EXTERNAL_KEPT,
        "de",
        "comma",
    )
    assert fields.doc_kind is DocKind.UNKNOWN  # fictitious vendor: L2 decides (fixture note)
    assert fields.trust_tier == 5


def test_known_vendor_with_a_datasheet_cue_is_a_datasheet_tier_4():
    moog = Vendor("moog", "Moog Inc.", ("Moog",), frozenset(), ("moog.com",), False)
    result = meta(
        "german_datasheet",
        "APU",
        "Components",
        title="Moog Datenblatt Ventil",
        vendors=(moog,),
        text="Moog Inc. Datenblatt Magnetventil 12,4 bar",
    )
    assert (result.fields.source_origin, result.fields.doc_kind, result.fields.trust_tier) == (
        SourceOrigin.EXTERNAL_KEPT,
        DocKind.DATASHEET,
        4,
    )
    assert result.fields.publisher == "Moog Inc."


def test_internal_equipment_vendor_alone_does_not_make_a_run_sheet_external():
    labjack = Vendor("labjack", "LabJack", ("LabJack",), frozenset(), ("labjack.com",), True)
    result = meta(
        "rotated_scan",
        "APU",
        "Test Plan 07/Run Sheets",
        vendors=(labjack,),
        text="TEST CELL RUN SHEET recorded with LabJack T7",
    )
    assert result.fields.source_origin == SourceOrigin.INTERNAL
    assert result.fields.trust_tier == 2


def test_short_vendor_aliases_match_case_sensitively_as_whole_words():
    ohb = Vendor("ohb", "OHB SE", ("OHB",), frozenset({"OHB"}), ("ohb.de",), False)
    assert find_vendor("built by OHB in Bremen", (ohb,)) == ohb
    assert find_vendor("the ohb flag", (ohb,)) is None
    assert find_vendor("JOHBAR", (ohb,)) is None


def test_export_control_marking_raises_sensitive_content_hard():
    result = meta(
        "german_datasheet", "APU", "Reports", furniture=["EXPORT CONTROLLED - ITAR"], text="Report text"
    )
    assert result.fields.classification_marking == "EXPORT CONTROLLED"
    assert [(f.flag_type, f.severity) for f in result.flags] == [(FlagType.SENSITIVE_CONTENT, "HARD")]


def test_standard_id_revision_and_draft_marker_from_the_footer():
    result = meta(
        "german_datasheet",
        "APS - Library",
        "Standards",
        furniture=["ECSS-E-ST-35C Rev.1 DRAFT"],
        text="Space engineering - Propulsion general requirements",
    )
    fields = result.fields
    assert (fields.standard_id, fields.standard_revision, fields.revision_marker, fields.doc_kind) == (
        "ECSS-E-ST-35C",
        "1",
        "DRAFT",
        DocKind.STANDARD,
    )
    assert fields.trust_tier == 3


@pytest.mark.parametrize(
    ("text", "locale"), [("12,4 bar and 0,25 N", "comma"), ("12.4 bar", "dot"), ("no numbers", None)]
)
def test_number_locale(text, locale):
    assert number_locale(text) == locale


def test_title_falls_back_to_the_humanized_file_name():
    assert humanize("Test_Report_37_final.pdf") == "Test Report 37 final"
