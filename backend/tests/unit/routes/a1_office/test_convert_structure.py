from pathlib import Path

import pytest

pytest.importorskip("pikepdf")
pytest.importorskip("pypdfium2")

from backend.llm_engine.vision.schemas import PageType, Script
from backend.postgres.enums import NodeSource, NodeType
from backend.routes.a1_office.convert import (
    OcrPlan,
    Run,
    RunResult,
    engine_languages,
    low_ocr_pages,
    plan_runs,
)
from backend.routes.a1_office.structure import PageContext, build_structure, heading_level
from backend.routes.a1_office.triage import PageDecision

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "a1_office"


def decision(page_no, page_type=PageType.DIGITAL_TEXT, engine=None, language="en", script=Script.LATIN):
    return PageDecision(
        page_no=page_no,
        page_type=page_type,
        language=language,
        script=script,
        is_rotated=False,
        image_only=engine is not None,
        ocr_engine=engine,
    )


def test_runs_split_by_ocr_plan_and_contiguity():
    decisions = [
        decision(1),
        decision(2),
        decision(3, PageType.SCANNED_PRINTED, "tesseract", "de"),
        decision(4, PageType.SCANNED_PRINTED, "tesseract", "de"),
        decision(5, PageType.SCANNED_PRINTED, "rapidocr", "ja", Script.CJK),
        decision(6),
        decision(7, PageType.SCANNED_PRINTED, "tesseract", "de"),
    ]
    assert plan_runs(decisions) == [
        Run(1, 2, None),
        Run(3, 4, OcrPlan("tesseract", ("Latin",))),
        Run(5, 5, OcrPlan("rapidocr", ("japan",))),
        Run(6, 6, None),
        Run(7, 7, OcrPlan("tesseract", ("Latin",))),
    ]


@pytest.mark.parametrize(
    ("engine", "language", "script", "codes"),
    [
        ("tesseract", "ru", "cyrillic", ("Cyrillic",)),
        ("tesseract", "de", "latin", ("Latin",)),
        ("tesseract", None, None, ("Latin",)),
        ("rapidocr", "zh", "cjk", ("chinese",)),
        ("easyocr", "de", "latin", ("de", "en")),
    ],
)
def test_engine_language_codes(engine, language, script, codes):
    assert engine_languages(engine, language, script) == codes


def test_pipeline_options_ocr_only_on_scanned_runs_and_never_remote():
    pytest.importorskip("docling")
    from backend.routes.a1_office.convert import pipeline_options

    digital = pipeline_options(None)
    scanned = pipeline_options(OcrPlan("rapidocr", ("japan",)))
    assert (digital.do_ocr, scanned.do_ocr) == (False, True)
    assert scanned.ocr_options.lang == ["japan"] and str(scanned.ocr_options.mode.value) == "full_page"
    for options in (digital, scanned):
        assert options.do_picture_description is False and options.enable_remote_services is False
        assert options.table_structure_options.mode.value == "accurate"
        assert str(options.accelerator_options.device.value) == "cpu"


def test_low_ocr_pages_include_nan_scores():
    result = RunResult(
        Run(1, 3, OcrPlan("tesseract", ("eng",))),
        None,
        {1: {"ocr_score": 0.9}, 2: {"ocr_score": 0.4}, 3: {"ocr_score": float("nan")}},
    )
    assert low_ocr_pages(result) == [2, 3]
    assert low_ocr_pages(RunResult(Run(1, 1, None), None, {})) == []


@pytest.mark.parametrize(
    ("text", "level"),
    [("3 Results", 1), ("3.2 Chamber Pressure", 2), ("4.2.3a x", 1), ("Abstract", 1), ("3.2.1. Ignition", 3)],
)
def test_heading_levels_from_numbering(text, level):
    assert heading_level(text) == level


def _docling_ready() -> bool:
    try:
        import docling  # noqa: F401
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    needed = ["docling-layout-heron", "docling-models", "DocumentFigureClassifier-v2.5", "CodeFormulaV2"]
    return all(isinstance(try_to_load_from_cache(f"docling-project/{r}", "README.md"), str) for r in needed)


docling_only = pytest.mark.skipif(not _docling_ready(), reason="Docling or its cached models are missing")


@pytest.fixture(scope="module")
def converted():
    from backend.routes.a1_office.convert import convert_run

    out = {}
    for name in ("doi_paper", "german_datasheet"):
        (pdf,) = (FIXTURES / name).glob("*.pdf")
        result = convert_run(pdf.read_bytes(), Run(1, 1, None), pdf.name)
        out[name] = build_structure(
            [result.document],
            {1: PageContext(language="en", source=NodeSource.PRINTED)},
            fallback_title=pdf.stem,
        )
    return out


@docling_only
def test_paper_references_are_mentions_and_the_abstract_is_its_own_section(converted):
    paper = converted["doi_paper"]
    assert paper.title == "Catalyst bed preheating effects on HTP monopropellant start-up"
    assert len(paper.references) == 3
    assert [m.kind for m in paper.mentions] == ["reference"] * 3
    assert not any("Catalyst bed activation in peroxide thrusters" in n.content for n in paper.nodes)
    crumbs = [n.breadcrumb.split(" › ")[-1] for n in paper.nodes]
    assert "Abstract" in crumbs and "3 Results" in crumbs and "References" not in crumbs
    results = next(n for n in paper.nodes if n.breadcrumb.endswith("3 Results"))
    assert "11.8 bar" in results.content


@docling_only
def test_page_header_with_journal_and_doi_is_furniture_not_body(converted):
    paper = converted["doi_paper"]
    furniture = " ".join(paper.furniture.get(1, []))
    assert (
        "Journal of Synthetic Propulsion Fixtures" in furniture or "10.5555/dcl.fixture.2026.001" in furniture
    )
    assert not any("Journal of Synthetic Propulsion Fixtures" in n.content for n in paper.nodes)


@docling_only
def test_datasheet_table_is_one_html_node_and_boxes_are_top_left_fractions(converted):
    sheet = converted["german_datasheet"]
    (table,) = [n for n in sheet.nodes if n.node_type is NodeType.TABLE]
    assert table.content.startswith("<table>") and "Nennschub" in table.content and "1,0 N" in table.content
    assert table.metadata["n_rows"] >= 6 and table.metadata["n_cols"] == 2
    for node in sheet.nodes:
        assert node.page_no == 1 and node.bboxes
        for box in node.bboxes:
            assert 0 <= box.x0 <= box.x1 <= 1 and 0 <= box.y0 <= box.y1 <= 1
    title_text = next(n for n in sheet.nodes if n.node_type is NodeType.CHILD)
    assert title_text.bboxes[0].y0 < table.bboxes[0].y0  # text above the table, top-left origin
