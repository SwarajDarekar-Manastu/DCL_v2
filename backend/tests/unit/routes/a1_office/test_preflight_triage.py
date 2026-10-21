import io
from pathlib import Path

import pytest

pikepdf = pytest.importorskip("pikepdf")  # parse dependencies (pikepdf, pypdfium2) until pyproject lists them
pytest.importorskip("pypdfium2")

from backend.llm_engine.vision.schemas import PageTriage, PageType, Script  # noqa: E402
from backend.llm_engine.vision.service import VisionOutput  # noqa: E402
from backend.routes.a1_office.preflight import (  # noqa: E402
    PreflightFailure,
    garbage_ratio,
    preflight,
    render_page,
    windows,
)
from backend.routes.a1_office.triage import combine, ocr_groups, triage_pages  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "a1_office"


def fixture(name: str) -> bytes:
    (pdf,) = (FIXTURES / name).glob("*.pdf")
    return pdf.read_bytes()


def blank_pdf(pages: int, password: str | None = None) -> bytes:
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(595, 842))
    out = io.BytesIO()
    pdf.save(out, encryption=pikepdf.Encryption(owner=password, user=password) if password else False)
    return out.getvalue()


@pytest.mark.parametrize(
    ("name", "image_only"),
    [
        ("doi_paper", False),
        ("german_datasheet", False),
        ("japanese_scanned_page", True),
        ("rotated_scan", True),
    ],
)
def test_fixtures_split_into_digital_and_image_only(name, image_only):
    result = preflight(fixture(name))
    assert result.page_count == 1 and not result.repaired
    assert result.page(1).image_only is image_only


def test_encrypted_pdf_fails_with_the_reason():
    with pytest.raises(PreflightFailure) as caught:
        preflight(blank_pdf(1, password="secret"))
    assert caught.value.reason == "encrypted"


def test_damaged_pdf_is_repaired_or_fails_with_a_reason():
    data = fixture("german_datasheet")
    cut = data.replace(b"startxref", b"startxrfe")
    result = preflight(cut)
    assert result.page_count == 1
    with pytest.raises(PreflightFailure) as caught:
        preflight(b"%PDF-1.4\nthis is not a pdf at all")
    assert caught.value.reason == "unrepairable"


def test_long_documents_are_windowed_by_100_pages():
    assert windows(450) == [(1, 100), (101, 200), (201, 300), (301, 400), (401, 450)]
    assert windows(400) == [(1, 400)]
    assert preflight(blank_pdf(450)).windows[-1] == (401, 450)


@pytest.mark.parametrize(
    ("text", "garbage"),
    [
        ("The chamber pressure rose to 12.4 bar.", False),
        ("燃焼室圧力は1.2 MPaに達した。", False),
        ("Давление в камере 12,4 бар.", False),
        (" �� ##$% &&*@", True),
    ],
)
def test_garbage_ratio_counts_broken_text_but_not_foreign_scripts(text, garbage):
    assert (garbage_ratio(text) > 0.4) is garbage


def test_thumbnail_long_side_is_768_px():
    from PIL import Image

    image = Image.open(io.BytesIO(render_page(fixture("rotated_scan"), 1, long_side_px=768)))
    assert max(image.size) == 768


def reading(page_type, script="latin", language="en", **kw):
    return PageTriage.model_validate(
        {
            "page_type": page_type,
            "has_handwriting": False,
            "has_tables": False,
            "has_figures": kw.get("figures", False),
            "is_rotated": kw.get("rotated", False),
            "language": language,
            "script": script,
        }
    )


@pytest.mark.parametrize(
    ("model_type", "image_only", "expected"),
    [
        ("digital_text", True, PageType.SCANNED_PRINTED),
        ("scanned_printed", False, PageType.DIGITAL_TEXT),
        ("scanned_form_with_handwriting", True, PageType.SCANNED_FORM_WITH_HANDWRITING),
        ("table_dense", False, PageType.TABLE_DENSE),
    ],
)
def test_signals_bound_the_model(model_type, image_only, expected):
    assert combine(reading(model_type), image_only) == expected


class Vision:
    def __init__(self, readings):
        self.readings = readings
        self.calls = []

    def triage_page(self, thumbnail, *, context, doc_id=None, anchor=None):
        self.calls.append((context, anchor))
        return VisionOutput(self.readings.pop(0), "gemini-3.5-flash-lite", "triage_page.v1", "h", False)


def test_japanese_scan_goes_to_rapidocr_and_a_latin_scan_to_tesseract():
    ja = triage_pages(
        preflight(fixture("japanese_scanned_page")),
        Vision([reading("scanned_printed", "cjk", "ja")]),
        context="APS - Library / Specs / thruster_spec_ja_scan.pdf",
    )
    run_sheet = triage_pages(
        preflight(fixture("rotated_scan")),
        Vision([reading("scanned_printed", "latin", "en", rotated=True)]),
        context="APU / TP07 / run_sheet_T01_rotated.pdf",
    )
    assert (ja[0].page_type, ja[0].script, ja[0].ocr_engine, ja[0].language) == (
        PageType.SCANNED_PRINTED,
        Script.CJK,
        "rapidocr",
        "ja",
    )
    assert (run_sheet[0].ocr_engine, run_sheet[0].is_rotated) == ("tesseract", True)
    assert ocr_groups(ja + run_sheet) == {("rapidocr", "ja"): [1], ("tesseract", "en"): [1]}


def test_digital_page_needs_no_ocr_and_the_call_names_the_page():
    vision = Vision([reading("digital_text", "latin", "de")])
    (decision,) = triage_pages(preflight(fixture("german_datasheet")), vision, context="APS - Library / MT-1")
    assert (decision.page_type, decision.ocr_engine, decision.language) == (PageType.DIGITAL_TEXT, None, "de")
    assert vision.calls == [("APS - Library / MT-1 · page 1 of 1", "page:1:")]
    assert decision.meta()["prompt_version"] == "triage_page.v1"


def test_without_cloud_permission_no_triage_call_is_made():
    vision = Vision([])
    (decision,) = triage_pages(
        preflight(fixture("japanese_scanned_page")), vision, context="x", cloud_allowed=False
    )
    assert vision.calls == []
    assert (decision.page_type, decision.triage_source, decision.ocr_engine) == (
        PageType.SCANNED_PRINTED,
        "signals",
        "tesseract",
    )
