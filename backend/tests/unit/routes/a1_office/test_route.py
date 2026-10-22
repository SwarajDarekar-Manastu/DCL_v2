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
        "has_handwriting": False,
        "has_tables": True,
        "has_figures": False,
        "is_rotated": False,
        "language": language,
        "script": script,
        "handwriting_regions": [],
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
