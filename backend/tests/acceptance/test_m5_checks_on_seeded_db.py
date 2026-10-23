"""The M5 acceptance checks themselves are tested: each passes on a good state and fails on a bad
one. Disposable database (DCL_TEST_DATABASE_URL); MinIO existence comes from a set."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from backend.postgres.models import Asset, Blob, Document, DocumentNode, DocumentSource
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "postgres" / "alembic.ini"
SHA = "a" * 64


@pytest.fixture()
def db(monkeypatch):
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    url = normalize_url(url)
    monkeypatch.setenv("DCL_DATABASE_URL", url)
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            seed(session)
            session.commit()
            yield session
    finally:
        engine.dispose()
        command.downgrade(config, "base")


@pytest.fixture(scope="module")
def m5():
    from backend.tests.acceptance.conftest import _load

    return _load("m5_state")


def asset(session, name, kind, w, h, bbox):
    a = Asset(
        asset_id=uuid.uuid4(),
        minio_uri=f"s3://dcl-assets/x/{name}.png",
        blob_sha256=SHA,
        kind=kind,
        page_no=1,
        bbox=bbox,
        width=w,
        height=h,
    )
    session.add(a)
    return a


def node(session, doc, node_type, content, a=None, cls=None, ordinal=0):
    session.add(
        DocumentNode(
            doc_id=doc.doc_id,
            node_type=node_type,
            ordinal=ordinal,
            content=content,
            source="printed",
            asset_id=a.asset_id if a else None,
            metadata_={"class": cls} if cls else {},
        )
    )


def seed(session):
    """One A1 PDF: a figure crop, a full-page image, a handwriting crop and a table with its crop."""
    session.add(Blob(sha256=SHA, size_bytes=10, minio_uri=f"s3://dcl-raw/{SHA}"))
    doc = Document(doc_id=uuid.uuid4(), route="A1", status="ACTIVE", entity_ids=[])
    session.add(doc)
    session.flush()
    session.add(DocumentSource(doc_id=doc.doc_id, blob_sha256=SHA, role="primary"))
    figure = asset(session, "fig", "figure_crop", 900, 600, {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.4})
    full = asset(session, "full", "figure_crop", 2400, 3300, {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0})
    hand = asset(session, "hand", "handwriting_crop", 300, 80, {"x0": 0.2, "y0": 0.5, "x1": 0.45, "y1": 0.53})
    table = asset(session, "table", "table_crop", 1500, 700, {"x0": 0.1, "y0": 0.6, "x1": 0.9, "y1": 0.9})
    session.flush()
    node(session, doc, "figure", "Plot of chamber pressure against time", figure, "plot", 0)
    node(session, doc, "figure", "Scanned page photograph", full, "full_page_image", 1)
    node(session, doc, "child", "handwritten value 12.5", hand, None, 2)
    node(session, doc, "table", "<table><tr><td>1</td></tr></table>", table, None, 3)


SHEETS = {f"s3://dcl-assets/qa/{SHA}/crops.png"}


def test_every_check_passes_on_the_good_state(m5, db):
    assert m5.crop_violations(db) == []
    assert m5.table_crop_violations(db) == []
    assert m5.figure_content_violations(db) == []
    assert m5.contact_sheet_violations(db, SHEETS.__contains__) == []
    report = m5.report(db, SHEETS.__contains__)
    assert report["counts"]["a1_documents"] == 1
    assert set(report["violations"].values()) == {0}


def test_a_sliver_fails(m5, db):
    db.execute(update(Asset).where(Asset.kind == "handwriting_crop").values(width=60, height=20))
    assert len(m5.crop_violations(db)) == 1


def test_a_crop_below_the_page_share_fails(m5, db):
    tiny = {"x0": 0.2, "y0": 0.5, "x1": 0.25, "y1": 0.52}  # 0.1 % of the page
    db.execute(update(Asset).where(Asset.kind == "handwriting_crop").values(bbox=tiny))
    assert len(m5.crop_violations(db)) == 1


def test_a_page_wide_crop_fails_unless_full_page_image(m5, db):
    whole = {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.95}
    db.execute(update(Asset).where(Asset.minio_uri.endswith("/fig.png")).values(bbox=whole))
    assert len(m5.crop_violations(db)) == 1  # the full_page_image one still passes


def test_a_table_without_its_crop_fails(m5, db):
    db.execute(update(DocumentNode).where(DocumentNode.node_type == "table").values(asset_id=None))
    assert len(m5.table_crop_violations(db)) == 1


def test_an_empty_figure_fails(m5, db):
    db.execute(update(DocumentNode).where(DocumentNode.ordinal == 0).values(content="  "))
    assert len(m5.figure_content_violations(db)) == 1


def test_a_missing_contact_sheet_fails(m5, db):
    assert len(m5.contact_sheet_violations(db, set().__contains__)) == 1
