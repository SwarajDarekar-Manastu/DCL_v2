"""One real file per route, through the real dispatcher, route runner, enrichment units, embedding and commit,
ends ACTIVE with embedded nodes and an enrichment summary.

Real files come from the git-ignored ``data/samples`` (S5's export); a missing sample skips its test.
Gemini and the embedder are fakes, so the test proves the wiring; the real models were run by hand
(STATUS 2026-10-23).
Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.dispatcher.routing import dispatch
from backend.dispatcher.source_run import (
    process_a2_document,
    process_b_document,
    process_e_document,
    process_g_document,
)
from backend.indexing.index_document import index_document
from backend.llm_engine.enrichment.entities import AliasIndex
from backend.llm_engine.gemini_types import GenerateResult, Usage
from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import Document, DocumentNode, DriveFolder, DriveItem, EntityMention, SyncRoot
from backend.tests.unit.dispatcher.test_dispatch import _put

SAMPLES = Path(__file__).resolve().parents[4] / "data" / "samples"
ROOT = "APU Injector"
VOCABULARY = {
    "xlwings": "tool_software",
    "Injector Flange": "component",
    "injector": "component",
    "pressure": "other",
}


class Gemini:
    def generate_sync(self, *, model, messages, context, schema, **options):
        text = messages[-1].parts[0].text
        entities = [
            {"type": kind, "surface": surface, "normalized_hint_en": surface}
            for surface, kind in VOCABULARY.items()
            if surface in text and kind != "other"
        ]
        parsed = schema.model_validate(
            {
                "summary": "A real file, summarised by a fake.",
                "section_kind": "other",
                "entities": entities,
                "questions_answered": ["Which file is this and where was it used?"],
            }
        )
        return GenerateResult(
            text="",
            parsed=parsed,
            tool_calls=(),
            usage=Usage(1, 1),
            model=model,
            finish_reason="stop",
            request_id="r",
            latency_ms=1,
        )


def _indexer(session, doc, doc_id, cloud_allowed):
    assert cloud_allowed is True
    return index_document(
        doc,
        doc_id=doc_id,
        gemini=Gemini(),
        embed_documents=lambda texts, titles: [[0.01] * 768 for _ in texts],
        embed_images=None,
        asset_bytes=None,
        alias_index=AliasIndex(),
        reuse_vectors=lambda hashes: {},
        cloud_allowed=True,
        count_tokens=lambda texts: [len(t.split()) for t in texts],
    )


def _load(session, minio, files: list[Path], base: Path) -> None:
    """The files as landed OneDrive items under ``APU Injector/<their folders>``."""
    folders: dict[str, str] = {}
    for path in files:
        parts = [ROOT, *path.relative_to(base).parent.parts]
        for depth in range(1, len(parts) + 1):
            folder = "/".join(parts[:depth])
            if folder not in folders:
                parent = "/".join(parts[: depth - 1])
                session.add(
                    DriveFolder(
                        drive_id="D",
                        item_id=folder,
                        root_name=ROOT,
                        name=parts[depth - 1],
                        parent_item_id=folders.get(parent),
                        path_cached=folder,
                    )
                )
                folders[folder] = folder
        data = path.read_bytes()
        session.add(
            DriveItem(
                drive_id="D",
                item_id=f"{'/'.join(parts)}/{path.name}",
                root_name=ROOT,
                name=path.name,
                extension=path.suffix.casefold() or None,
                parent_item_id="/".join(parts),
                path_cached=f"{'/'.join(parts)}/{path.name}",
                status=DriveItemStatus.LANDED,
                blob_sha256=_put(session, minio, data),
                detected_mime="application/octet-stream",
                size_bytes=len(data),
            )
        )


def _run(session, minio, files, base, scope_folder, route, runner, pick):
    _load(session, minio, files, base)
    session.get(SyncRoot, ROOT).cloud_allowed = True
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, [scope_folder], "test")
    pipeline_config.set_value(session, f"routes.{route}.enabled", True, "test")
    session.commit()
    dispatch(session, minio, section_file_sets=())
    document = pick(
        session.scalars(
            select(Document).where(Document.route == route, Document.status == "PROCESSING")
        ).all()
    )
    runner(session, minio, document.doc_id, _indexer)
    session.commit()
    return session.get(Document, document.doc_id)


def _assert_indexed(session, document: Document, enriched: bool = True, entities: bool = True) -> None:
    assert document.status in ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS"), (
        document.status,
        document.metadata_sources,
    )
    nodes = session.scalars(select(DocumentNode).where(DocumentNode.doc_id == document.doc_id)).all()
    assert nodes and all(n.embedding is not None for n in nodes)
    assert document.search_text
    assert isinstance(document.doc_id, uuid.UUID)
    mentions = session.scalar(
        select(func.count()).select_from(EntityMention).where(EntityMention.doc_id == document.doc_id)
    )
    if enriched:
        assert document.enrichment["doc_summary"].startswith("A real file, summarised by a fake.")
        assert mentions or not entities
    else:  # no chunker parent, so no model call: the manual plans AST and graph nodes only (03 §6, §9)
        assert not document.enrichment.get("doc_summary")


def test_a_real_python_script_reaches_active_embedded_and_enriched(session, minio):
    pytest.importorskip("tree_sitter_python")
    folder = SAMPLES / "E1" / "29122025 - Injector 10 Cold flow test"
    script = folder / "Test_plan_creator.py"
    if not script.is_file():
        pytest.skip("sample E1 not exported")
    document = _run(
        session, minio, [script], SAMPLES, f"{ROOT}/E1/{folder.name}", "B", process_b_document, lambda d: d[0]
    )
    _assert_indexed(session, document, enriched=False)
    types = set(session.scalars(select(DocumentNode.node_type).where(DocumentNode.doc_id == document.doc_id)))
    assert {"module_header", "code_symbol"} <= types


def test_a_real_drawio_diagram_reaches_active_embedded_and_enriched(session, minio):
    pytest.importorskip("ezdxf")
    diagram = SAMPLES / "E6" / "Test Plan 22" / "THruster config - Rev C.drawio"
    if not diagram.is_file():
        pytest.skip("sample E6 not exported")
    document = _run(session, minio, [diagram], SAMPLES, f"{ROOT}/E6", "E", process_e_document, lambda d: d[0])
    _assert_indexed(session, document, enriched=False)
    types = set(session.scalars(select(DocumentNode.node_type).where(DocumentNode.doc_id == document.doc_id)))
    assert "diagram_summary" in types


def test_a_real_latex_report_reaches_active_embedded_and_enriched(session, minio):
    pytest.importorskip("pylatexenc")
    folder = SAMPLES / "E1" / "29122025 - Injector 10 Cold flow test"
    sources = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix in (".tex", ".pdf", ".json"))
    if not sources:
        pytest.skip("sample E1 not exported")
    document = _run(
        session,
        minio,
        sources,
        SAMPLES,
        f"{ROOT}/E1/{folder.name}",
        "A2",
        process_a2_document,
        lambda docs: next(d for d in docs if d.title == "Sections"),
    )
    _assert_indexed(session, document)


@pytest.mark.parametrize(
    ("name", "listed"),
    [
        ("real_scdoc_1.scdoc", "SpaceClaim/Geometry/part1bodies.sab"),
        ("real_wbpz_1.wbpz", "solve.out"),
        ("real_zip_latex_project.zip", "Injector/Test_plan.tex"),
    ],
)
def test_a_real_g_file_becomes_one_searchable_card(session, minio, name, listed):
    sample = SAMPLES / "G" / "corpus" / name
    if not sample.is_file():
        pytest.skip("sample G/corpus not exported")
    document = _run(
        session, minio, [sample], SAMPLES, f"{ROOT}/G/corpus", "G", process_g_document, lambda docs: docs[0]
    )
    _assert_indexed(session, document, entities=False)
    nodes = session.scalars(select(DocumentNode).where(DocumentNode.doc_id == document.doc_id)).all()
    types = sorted(n.node_type for n in nodes)
    assert types == ["child", "parent", "question_proxy"]
    assert any(listed in n.content for n in nodes if n.node_type == "child")
    assert document.catalog["listing"]["count"] > 0 and document.title == name
