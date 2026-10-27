import io
from pathlib import Path

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("docling")

from backend.dispatcher.contract import ProcessedDocument  # noqa: E402
from backend.dispatcher.folder_context import build_folder_context  # noqa: E402
from backend.indexing.chunker import chunk_document  # noqa: E402
from backend.postgres.enums import (  # noqa: E402
    AssetKind,
    DocKind,
    FlagSeverity,
    FlagType,
    NodeSource,
    NodeType,
    SourceOrigin,
)
from backend.routes.a1_office.convert import RunResult  # noqa: E402
from backend.routes.a1_office.route import Stores, process_pdf  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "a1_office"
SHA = "d" * 64


def fixture(name):
    (pdf,) = (FIXTURES / name).glob("*.pdf")
    return pdf.name, pdf.read_bytes()


def triage(page_type="digital_text", language="en", script="latin"):
    return {
        "page_type": page_type,
        "has_figures": False,
        "is_rotated": False,
        "language": language,
        "script": script,
    }


def stores(memory_store):
    return Stores(
        put_cir=memory_store(f"s3://dcl-cir/{SHA}/A1/v1/"), put_asset=memory_store("s3://dcl-assets/")
    )


def folder(root, path, name, origin=SourceOrigin.INTERNAL):
    return build_folder_context(root, [root, *path.split("/")], name, root_origin=origin)


def _ready():
    from huggingface_hub import try_to_load_from_cache

    needed = ["docling-layout-heron", "docling-models", "DocumentFigureClassifier-v2.5", "CodeFormulaV2"]
    return all(isinstance(try_to_load_from_cache(f"docling-project/{r}", "README.md"), str) for r in needed)


docling_models = pytest.mark.skipif(not _ready(), reason="Docling models are not cached")


@docling_models
def test_doi_paper_end_to_end(fake_vision, memory_store):
    name, data = fixture("doi_paper")
    st = stores(memory_store)
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APU", "Test Plan 37/literature", name),
        vision=fake_vision(triage_page=triage()),
        stores=st,
    )
    assert isinstance(ProcessedDocument.model_validate(doc.model_dump(mode="json")), ProcessedDocument)
    fields = doc.document
    assert fields.external_ids.doi == "10.5555/dcl.fixture.2026.001"
    assert (fields.source_origin, fields.doc_kind, fields.trust_tier) == (
        SourceOrigin.EXTERNAL_KEPT,
        DocKind.ACADEMIC_PAPER,
        5,
    )
    assert [m.kind for m in doc.mentions] == ["reference"] * 3
    assert doc.flags == []
    assert [a.kind for a in doc.assets] == [AssetKind.PAGE_RENDER]
    assert set(st.put_cir.objects) >= {
        "docling/1-1.json",
        "pages/1.meta.json",
        "pages/1.txt",
        "page_hashes.json",
    }
    assert doc.unit_hashes[0].unit == "page"
    chunks = chunk_document(doc, count_tokens=lambda texts: [len(t.split()) for t in texts])
    assert any("11.8 bar" in c.content for c in chunks if c.node_type is NodeType.CHILD)


@docling_models
def test_german_datasheet_end_to_end(fake_vision, memory_store):
    name, data = fixture("german_datasheet")
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS - Library", "Vendor brochures/DE", name, SourceOrigin.EXTERNAL_KEPT),
        vision=fake_vision(triage_page=triage(language="de")),
        stores=stores(memory_store),
    )
    fields = doc.document
    assert (fields.language, fields.number_locale, fields.source_origin) == (
        "de",
        "comma",
        SourceOrigin.EXTERNAL_KEPT,
    )
    (table,) = [n for n in doc.nodes if n.node_type is NodeType.TABLE]
    assert "Nennschub" in table.content and table.language == "de"
    assert all(n.source is NodeSource.PRINTED for n in doc.nodes)


def test_encrypted_pdf_becomes_a_hard_parse_failure(fake_vision, memory_store):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    out = io.BytesIO()
    pdf.save(out, encryption=pikepdf.Encryption(owner="x", user="x"))
    doc = process_pdf(
        out.getvalue(),
        blob_sha256=SHA,
        file_name="locked.pdf",
        folder=folder("APU", "Reports", "x"),
        vision=fake_vision(),
        stores=stores(memory_store),
    )
    (flag,) = doc.flags
    assert (flag.flag_type, flag.severity, doc.nodes) == (FlagType.PARSE_FAILURE, FlagSeverity.HARD, [])
    assert "encrypted" in flag.evidence.error


def test_scanned_page_with_low_ocr_goes_to_transcribe_page(fake_vision, memory_store):
    from docling_core.types.doc import DoclingDocument

    name, data = fixture("japanese_scanned_page")
    calls = []

    def convert(pdf_bytes, run, file_name):
        calls.append(run)
        return RunResult(run, DoclingDocument(name="scan"), {1: {"ocr_score": 0.3}})

    vision = fake_vision(
        triage_page=triage("scanned_printed", "ja", "cjk"),
        transcribe_page={
            "markdown": "# スラスタ仕様書\n\n推力 1.0 N、比推力 160 s",
            "language": "ja",
            "confidence": 0.8,
        },
    )
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS - Library", "Vendor brochures/JP", name, SourceOrigin.EXTERNAL_KEPT),
        vision=vision,
        stores=stores(memory_store),
        convert=convert,
    )
    assert [r.ocr.engine for r in calls] == ["rapidocr"]  # CJK: no EasyOCR retry
    assert [c[0] for c in vision.calls] == ["triage_page", "transcribe_page"]
    assert [n.content for n in doc.nodes] == ["# スラスタ仕様書", "推力 1.0 N、比推力 160 s"]
    assert {n.source for n in doc.nodes} == {NodeSource.VLM} and doc.document.language == "ja"


LOSS_TABLE = "<table><tr><td>Loss % of Catalyst</td><td>6.8%</td></tr></table>"


def test_a_photographed_form_is_read_whole_and_its_doubtful_entries_go_to_a_person(fake_vision, memory_store):
    """TP07 DE p2: Docling's OCR passed the score but read a handwritten table as two header cells."""
    from docling_core.types.doc import DoclingDocument

    name, data = fixture("rotated_scan")  # an image-only page: images cover all of it
    vision = fake_vision(
        triage_page=triage("scanned_form_with_handwriting"),
        transcribe_page={
            "markdown": f"Post analysis of Catalyst\n\n{LOSS_TABLE}",
            "language": "en",
            "confidence": 0.95,
            "doubtful": [
                {
                    "field_label": "Loss % of Catalyst",
                    "value_raw": "6.8%",
                    "unit": "%",
                    "alternatives": ["6.81 %"],
                    "confidence": 0.85,
                    "illegible": False,
                }
            ],
        },
    )
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APU", "Test Campaign 2/TP07", name),
        vision=vision,
        stores=stores(memory_store),
        convert=lambda pdf, run, n: RunResult(run, DoclingDocument(name="form"), {1: {"ocr_score": 0.9}}),
    )
    assert [c[0] for c in vision.calls] == ["triage_page", "transcribe_page"]
    assert [n.content for n in doc.nodes if n.node_type is NodeType.CHILD][-1].endswith(
        "<td>6.8%</td></tr></table>"
    )
    (flag,) = [f for f in doc.flags if f.flag_type == FlagType.LOW_CONFIDENCE_EXTRACTION]
    assert (flag.severity, flag.anchor.page, flag.evidence.crops[0].crop_uri) == (
        FlagSeverity.SOFT,
        1,
        f"s3://dcl-assets/pages/{SHA}/0001.png",
    )
    assert not [a for a in doc.assets if a.kind is not AssetKind.PAGE_RENDER]  # nothing is cropped


@docling_models
def test_a_typed_page_triage_calls_a_form_stays_with_docling(fake_vision, memory_store):
    name, data = fixture("german_datasheet")  # a text layer and no images
    vision = fake_vision(triage_page=triage("scanned_form_with_handwriting", "de"))
    process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS - Library", "Datasheets", name, SourceOrigin.EXTERNAL_KEPT),
        vision=vision,
        stores=stores(memory_store),
    )
    assert [c[0] for c in vision.calls] == ["triage_page"]


def test_without_cloud_a_low_page_keeps_its_ocr_and_is_flagged(fake_vision, memory_store):
    from docling_core.types.doc import DoclingDocument

    name, data = fixture("rotated_scan")
    vision = fake_vision()
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APU", "Test Plan 07/Run Sheets", name),
        vision=vision,
        stores=stores(memory_store),
        cloud_allowed=False,
        convert=lambda pdf, run, n: RunResult(run, DoclingDocument(name="scan"), {1: {"ocr_score": 0.2}}),
    )
    assert vision.calls == []
    assert [(f.flag_type, f.severity) for f in doc.flags] == [
        (FlagType.LOW_CONFIDENCE_EXTRACTION, FlagSeverity.SOFT)
    ]
    assert doc.document.test_plan_id == "TP07"


@docling_models
def test_a_transcribed_page_keeps_its_footer_and_a_foreign_plan_id_is_a_conflict(fake_vision, memory_store):
    """The TP7 sheet whose printed footer says Test Plan 6 (benchmark: must present both values)."""
    from docling_core.types.doc import DoclingDocument

    name, data = fixture("japanese_scanned_page")

    def convert(pdf_bytes, run, file_name):
        return RunResult(run, DoclingDocument(name="scan"), {1: {"ocr_score": 0.3}})

    vision = fake_vision(
        triage_page=triage("scanned_printed", "en", "latin"),
        transcribe_page={
            "markdown": "Injector cold flow\n\nFlow 12.1 g/s",
            "language": "en",
            "confidence": 0.7,
            "furniture": ["Test Campaign 2 - Test Plan 6", "Sheet 3"],
        },
    )
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS", "Test Campaign 2/TP7/Handwritten", name),
        vision=vision,
        stores=stores(memory_store),
        convert=convert,
    )
    assert doc.document.test_plan_id == "TP07"  # the folder value stays until a reviewer resolves it
    conflicts = [f for f in doc.flags if f.flag_type == FlagType.CONFLICT]
    assert [(c.evidence.a.value, c.evidence.b.value) for c in conflicts] == [("TP07", "TP06")]
    assert conflicts[0].severity == FlagSeverity.SOFT and conflicts[0].anchor.page == 1
    assert all("Test Plan 6" not in n.content for n in doc.nodes)  # furniture is not body text


@docling_models
def test_a_blocked_transcription_keeps_the_ocr_and_flags_the_page(fake_vision, memory_store):
    """A Gemini refusal (safety block, outage) must not fail the document."""
    from docling_core.types.doc import DoclingDocument

    from backend.llm_engine.gemini_types import GeminiError

    name, data = fixture("japanese_scanned_page")

    def convert(pdf_bytes, run, file_name):
        return RunResult(run, DoclingDocument(name="scan"), {1: {"ocr_score": 0.3}})

    def blocked(kwargs):
        raise GeminiError("no candidates returned (block_reason=SAFETY)")

    vision = fake_vision(triage_page=triage("scanned_printed", "en", "latin"), transcribe_page=blocked)
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS", "Test Campaign 2/TP7", name),
        vision=vision,
        stores=stores(memory_store),
        convert=convert,
    )
    low = [f for f in doc.flags if f.flag_type == FlagType.LOW_CONFIDENCE_EXTRACTION]
    assert [f.anchor.page for f in low] == [1] and low[0].severity == FlagSeverity.SOFT


def test_nul_bytes_from_a_text_layer_never_reach_the_commit(fake_vision, memory_store):
    from backend.routes.a1_office.route import without_nul

    name, data = fixture("german_datasheet")
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS - Library", "Vendor brochures/DE", name, SourceOrigin.EXTERNAL_KEPT),
        vision=fake_vision(triage_page=triage(language="de")),
        stores=stores(memory_store),
    )
    assert without_nul(doc) is doc  # nothing to clean: the same object
    dirty = doc.model_copy(
        update={"nodes": [doc.nodes[0].model_copy(update={"content": "Schub\x00 12\x00 N"}), *doc.nodes[1:]]}
    )
    clean = without_nul(dirty)
    assert clean.nodes[0].content == "Schub 12 N" and clean.nodes[1:] == doc.nodes[1:]
    assert "\x00" not in clean.model_dump_json()


def test_every_image_asset_has_its_size_and_no_figure_is_empty(fake_vision, memory_store):
    from backend.dispatcher.contract import ProcessedNode
    from backend.routes.a1_office.route import fill_empty_figures

    name, data = fixture("german_datasheet")
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS - Library", "Vendor brochures/DE", name, SourceOrigin.EXTERNAL_KEPT),
        vision=fake_vision(triage_page=triage(language="de")),
        stores=stores(memory_store),
    )
    assert doc.assets and all(a.width and a.height and a.bytes for a in doc.assets)
    figures = [
        ProcessedNode(
            ref=f"fig{i}",
            node_type=NodeType.FIGURE,
            ordinal=i,
            content="",
            page_no=2,
            source=NodeSource.PRINTED,
            metadata={"class": "line_chart", "caption": caption},
        )
        for i, caption in enumerate([None, "Figure 3: Pc over time", None])
    ]
    filled = fill_empty_figures(figures)
    assert [f.content for f in filled] == [
        "[Figure fig0 (line_chart) on page 2]",
        "Figure 3: Pc over time",
        "[Figure fig2 (line_chart) on page 2]",
    ]
    assert len({f.content for f in filled}) == 3  # distinct content hashes, distinct anchors


def test_formula_enrichment_beyond_the_cap_is_flagged_and_stage_timings_reach_the_cir(
    fake_vision, memory_store
):
    import json

    from backend.routes.a1_office import convert as convert_module

    def convert_with_formulas(data, run, name):
        result = convert_module.convert_run(data, run, name)
        budget = convert_module._BUDGET.get()
        budget.used, budget.skipped = budget.limit, 7  # as if the page held limit + 7 formulas
        return result

    name, data = fixture("doi_paper")
    store = stores(memory_store)
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS - Library", "Preheat", name, SourceOrigin.EXTERNAL_KEPT),
        vision=fake_vision(triage_page=triage()),
        stores=store,
        convert=convert_with_formulas,
        enrichment_max=3,
    )
    [flag] = [
        f for f in doc.flags if f.suggested_resolution and "enrichment" in f.suggested_resolution.rationale
    ]
    assert (flag.flag_type, flag.severity) == (FlagType.LOW_CONFIDENCE_EXTRACTION, FlagSeverity.SOFT)
    assert "skipped for 7 of 10 items (cap 3 per document)" in flag.suggested_resolution.rationale
    timings = json.loads(store.put_cir.objects["timings.json"])
    assert {"preflight", "triage", "convert", "page_renders", "transcribe_page", "figures", "tables"} <= set(
        timings["stages"]
    )
    assert timings["enrichment"] == {"limit": 3, "used": 3, "skipped": 7}
    assert timings["runs"][0]["pages"] == [1, 1] and "layout" in timings["runs"][0]["docling"]


def test_the_enrichment_cap_counts_per_document_and_lets_everything_through_outside_one():
    from backend.routes.a1_office.convert import cap_enrichment, enrichment_budget

    class FakeModel:
        def prepare_element(self, conv_res, element):
            return element if element != "text" else None

    model = FakeModel()
    cap_enrichment(model)
    cap_enrichment(model)  # idempotent: wrapping twice does not double count
    with enrichment_budget(2) as budget:
        kept = [model.prepare_element(conv_res=None, element=e) for e in ["f1", "text", "f2", "f3", "c1"]]
    assert kept == ["f1", None, "f2", None, None] and (budget.used, budget.skipped) == (2, 2)
    assert model.prepare_element(conv_res=None, element="f9") == "f9"  # no document budget: untouched


def test_tables_get_a_crop_and_the_document_a_contact_sheet(fake_vision, memory_store):
    name, data = fixture("german_datasheet")
    store = stores(memory_store)
    doc = process_pdf(
        data,
        blob_sha256=SHA,
        file_name=name,
        folder=folder("APS - Library", "Vendor brochures/DE", name, SourceOrigin.EXTERNAL_KEPT),
        vision=fake_vision(triage_page=triage(language="de")),
        stores=store,
    )
    (table,) = [n for n in doc.nodes if n.node_type is NodeType.TABLE]
    (crop,) = [a for a in doc.assets if a.ref == table.asset_ref]
    assert crop.kind == "table_crop" and crop.minio_uri.startswith(f"s3://dcl-assets/tables/{SHA}/")
    page_width_pt = 595.0  # the fixture is A4
    expected_px = (crop.bbox.x1 - crop.bbox.x0) * page_width_pt * 200 / 72  # stored at 200 dpi
    assert abs(crop.width - expected_px) <= 3
    qa = doc.document.catalog["qa"]
    assert qa["contact_sheet"] == f"s3://dcl-assets/qa/{SHA}/crops.png" and qa["crops"] >= 1
