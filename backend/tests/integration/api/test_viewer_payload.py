"""build_viewer_payload over real rows. Needs DCL_TEST_DATABASE_URL (an empty ParadeDB database)."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from backend.api.viewer import DocumentNotFound, build_viewer_payload
from backend.indexing.anchors import content_hash
from backend.postgres.models import Asset, Blob, Document, DocumentNode, DocumentSource, DriveItem, SyncRoot
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
REPORT = uuid.UUID("6f1c2a3e-0000-4000-8000-000000000001")
SCRIPT = uuid.UUID("6f1c2a3e-0000-4000-8000-000000000002")
PDF_SHA, PY_SHA = "c" * 64, "d" * 64


def signed(minio_uri: str) -> str:
    return f"https://minio.test/{minio_uri.removeprefix('s3://')}?sig=1"


def text_of(page: int) -> str:
    return f"Page {page}: chamber pressure peaked at 1{page}.4 bar(a) during the steady window."


@pytest.fixture(scope="module")
def session():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    url = normalize_url(url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        config = Config(str(ALEMBIC_INI))
        command.upgrade(config, "head")
        engine = create_engine(url)
        with Session(engine) as s:
            s.add(SyncRoot(root_name="APU Heater", remote_drive_id="drive", remote_item_id="root"))
            for sha in (PDF_SHA, PY_SHA):
                s.add(Blob(sha256=sha, size_bytes=1000, minio_uri=f"s3://dcl-raw/{sha[:2]}/{sha[2:4]}/{sha}"))
            s.flush()
            s.add_all(
                [
                    Document(
                        doc_id=REPORT,
                        route="A1",
                        title="Test Report 37",
                        doc_kind="test_report",
                        status="ACTIVE",
                        trust_tier=2,
                        language="de",
                        test_plan_id="TP37",
                        page_count=12,
                    ),
                    Document(
                        doc_id=SCRIPT,
                        route="B",
                        title="nozzle.py",
                        doc_kind="code",
                        status="ACTIVE",
                        trust_tier=2,
                        language="python",
                    ),
                ]
            )
            s.flush()
            s.add_all(
                [
                    DocumentSource(doc_id=REPORT, blob_sha256=PDF_SHA, role="primary"),
                    DocumentSource(doc_id=SCRIPT, blob_sha256=PY_SHA, role="primary"),
                    DriveItem(
                        drive_id="drive",
                        item_id="i1",
                        root_name="APU Heater",
                        name="TR37.pdf",
                        path_cached="APU Heater/TP37/TR37.pdf",
                        web_url="https://onedrive.test/tr37",
                        blob_sha256=PDF_SHA,
                        status="LANDED",
                    ),
                    DriveItem(
                        drive_id="drive",
                        item_id="i2",
                        root_name="APU Heater",
                        name="TR37 copy.pdf",
                        path_cached="APU Heater/Archive/TR37 copy.pdf",
                        web_url="https://onedrive.test/copy",
                        blob_sha256=PDF_SHA,
                        status="LANDED",
                    ),
                    DriveItem(
                        drive_id="drive",
                        item_id="i3",
                        root_name="APU Heater",
                        name="old.pdf",
                        web_url="https://onedrive.test/old",
                        blob_sha256=PDF_SHA,
                        status="DELETED",
                    ),
                    Asset(
                        minio_uri=f"s3://dcl-assets/pages/{PDF_SHA}/0008.png",
                        blob_sha256=PDF_SHA,
                        kind="page_render",
                        page_no=8,
                        width=1240,
                        height=1754,
                    ),
                ]
            )
            for page in range(7, 10):
                s.add(
                    DocumentNode(
                        doc_id=REPORT,
                        node_type="parent",
                        ordinal=page,
                        breadcrumb="3 Results",
                        content=text_of(page),
                        content_en=f"(en) {text_of(page)}",
                        content_sha256=content_hash(text_of(page)),
                        page_no=page,
                        source="printed",
                        bbox=[{"page_no": page, "x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.35}],
                    )
                )
            code = "def expansion_ratio(pc, pe):\n    gamma = 1.3\n    return (pc / pe) ** (1 / gamma)"
            s.add(
                DocumentNode(
                    doc_id=SCRIPT,
                    node_type="code_symbol",
                    ordinal=1,
                    breadcrumb="nozzle.py › expansion_ratio",
                    content=code,
                    content_sha256=content_hash(code),
                    line_start=40,
                    line_end=42,
                    source="printed",
                )
            )
            s.commit()
            yield s
        engine.dispose()
        command.downgrade(config, "base")


def anchor_of(page: int) -> str:
    return f"page:{page}:{content_hash(text_of(page))[:16]}"


def test_exact_citation_opens_the_page_render_with_the_cited_box(session):
    payload = build_viewer_payload(session, REPORT, anchor_of(8), False, signed)
    assert payload.resolution.status == "exact" and payload.resolution.message == ""
    view = payload.view
    assert view.kind == "page" and (view.page_no, view.page_count) == (8, 12)
    assert view.image_url == f"https://minio.test/dcl-assets/pages/{PDF_SHA}/0008.png?sig=1"
    assert [r.bbox for r in view.regions] == [(0.1, 0.3, 0.9, 0.35)]
    assert view.text == text_of(8)
    assert payload.document.test_ids == ["TP37"]
    assert [loc.path for loc in payload.links.onedrive] == [
        "APU Heater/Archive/TR37 copy.pdf",
        "APU Heater/TP37/TR37.pdf",
    ]
    assert payload.links.download_url == f"https://minio.test/dcl-raw/cc/cc/{PDF_SHA}?sig=1"
    assert "node_id" not in payload.model_dump_json()


def test_changed_content_falls_back_to_the_page_and_says_so(session):
    payload = build_viewer_payload(session, REPORT, "page:8:00000000deadbeef", False, signed)
    assert payload.resolution.status == "page_fallback"
    assert "changed after re-indexing" in payload.resolution.message
    assert payload.view.kind == "page" and payload.view.page_no == 8 and payload.view.regions == []


def test_a_reindex_that_moves_the_passage_still_finds_it(session):
    session.execute(update(DocumentNode).where(DocumentNode.page_no == 9).values(page_no=10))
    session.flush()
    payload = build_viewer_payload(session, REPORT, anchor_of(9), False, signed)
    assert payload.resolution.status == "exact"
    assert payload.view.kind == "text"  # page 10 has no render in this fixture
    assert payload.view.text == text_of(9)
    session.rollback()


def test_location_gone_opens_the_document_start(session):
    payload = build_viewer_payload(session, REPORT, "page:99:", False, signed)
    assert payload.resolution.status == "document_only"
    assert payload.view.kind == "text" and payload.view.text.startswith(text_of(7))


def test_no_anchor_opens_the_document(session):
    payload = build_viewer_payload(session, REPORT, "", False, signed)
    assert payload.resolution.status == "exact" and payload.anchor == ""


def test_translation_only_on_request(session):
    off = build_viewer_payload(session, REPORT, anchor_of(8), False, signed)
    on = build_viewer_payload(session, REPORT, anchor_of(8), True, signed)
    assert off.translation.available and off.translation.translated_text is None
    assert on.translation.translated_text == f"(en) {text_of(8)}" and on.translation.source_language == "de"


def test_code_line_anchor_highlights_the_line(session):
    payload = build_viewer_payload(session, SCRIPT, "line:41:", False, signed)
    view = payload.view
    assert view.kind == "code" and view.first_line == 40 and view.highlight == (41, 41)
    assert view.lines[1] == "    gamma = 1.3"


def test_unknown_document(session):
    with pytest.raises(DocumentNotFound):
        build_viewer_payload(session, uuid.uuid4(), "", False, signed)
