"""The M1 acceptance checks themselves are tested: each passes on a good registry state and
fails on a bad one. Runs on a disposable database (DCL_TEST_DATABASE_URL, as the schema tests);
skipped without it."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from backend.postgres.enums import DriveItemStatus as S
from backend.postgres.models import Blob, Document, DocumentSource, DriveFolder, DriveItem, SyncRoot
from backend.postgres.pipeline_config import set_value
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "postgres" / "alembic.ini"
TP7, PRESSURE, TP30, ROOT = "01TP7FOLDERAAAAAAAAAAAAAAAAAAAAAAA", "F-PRESSURE", "F-TP30", "F-ROOT"


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


def item(name, status, folder, reason=None, blob=None, path=None):
    return DriveItem(
        drive_id="D",
        item_id=f"I-{name}",
        root_name="APU",
        parent_item_id=folder,
        name=name,
        status=status,
        gate_reason=reason,
        blob_sha256=blob,
        path_cached=path or f"APU/x/{name}",
        size_bytes=10,
    )


def blob(sha):
    return Blob(sha256=sha, size_bytes=10, minio_uri=f"s3://dcl-raw/{sha}")


def document(sha):
    doc = Document(doc_id=uuid.uuid4(), route="C", status="ACTIVE", entity_ids=[])
    return doc, DocumentSource(doc_id=doc.doc_id, blob_sha256=sha, role="primary")


def seed(session):
    """A good M1 state: one allowlisted subtree (TP7 > Pressure), one folder outside it."""
    session.add(SyncRoot(root_name="APU", remote_drive_id="D", remote_item_id=ROOT))
    session.flush()
    for item_id, parent, name in (
        (ROOT, None, "APU"),
        (TP7, ROOT, "Test Plan 7"),
        (PRESSURE, TP7, "Pressure"),
        (TP30, ROOT, "Test Plan 30"),
    ):
        session.add(
            DriveFolder(drive_id="D", item_id=item_id, parent_item_id=parent, root_name="APU", name=name)
        )
    a, b = "a" * 64, "b" * 64
    session.add_all([blob(a), blob(b)])
    session.flush()
    session.add_all(
        [
            item("run1.dat", S.LANDED, PRESSURE, blob=a, path="APU/Test Plan 7/Pressure/run1.dat"),
            item("run2.dat", S.LANDED, TP30, blob=b, path="APU/Test Plan 30/run2.dat"),
            item("lib.pyc", S.SKIPPED_JUNK, TP30, reason="T2:.pyc"),
            item("old.dat", S.QUARANTINED, TP30, reason="T1:quarantine:_to_delete"),
            item("huge.mp4", S.HELD_LARGE_FILE, TP30, reason="T3:size"),
        ]
    )
    doc, src = document(a)
    session.add(doc)
    session.flush()
    session.add(src)
    set_value(session, "processing.scope", [TP7], updated_by="test")
    set_value(session, "sync.download_scope", [], updated_by="test")


def test_good_state_passes(m1, db):
    c = m1.item_counts(db)
    assert (c["items"], c["accepted"], c["rejected"], c["landed"]) == (5, 3, 2, 2)
    assert m1.decision_violations(c) == []
    assert m1.download_violations(c) == []
    assert m1.out_of_scope_documents(db) == []


def test_undecided_and_reasonless_items_fail(m1, db):
    db.add_all(
        [
            item("new.dat", S.SEEN, TP30),
            item("bad.pyc", S.SKIPPED_JUNK, TP30),
            item("odd.pyc", S.SKIPPED_JUNK, TP30, reason="junk"),
        ]
    )
    db.flush()
    violations = m1.decision_violations(m1.item_counts(db))
    assert len(violations) == 3, violations


def test_unfinished_downloads_fail(m1, db):
    db.add(item("late.dat", S.PENDING_DOWNLOAD, TP30))
    db.flush()
    assert any("pending" in v for v in m1.download_violations(m1.item_counts(db)))


def test_dispatch_outside_the_allowlist_fails(m1, db):
    doc, src = document("b" * 64)
    db.add(doc)
    db.flush()
    db.add(src)
    db.flush()
    assert m1.out_of_scope_documents(db) == [str(doc.doc_id)]


def test_snapshot_compare_shows_a_rename_without_downloads(m1, db):
    before = m1.snapshot(db)
    db.execute(
        update(DriveItem)
        .where(DriveItem.parent_item_id == PRESSURE)
        .values(path_cached="APU/TP7 renamed/Pressure/run1.dat")
    )
    db.flush()
    diff = m1.compare(before, m1.snapshot(db))
    assert diff == {"counts": {}, "jobs": {}, "changed_paths": 1}


def test_bands_follow_the_manual(m1):
    good = {"items": 110_000, "rejected": 105_000, "accepted": 5_072}
    assert m1.band_violations(good) == []
    assert len(m1.band_violations({"items": 5_000, "rejected": 4_000, "accepted": 1_000})) == 3


def test_live_sessions_are_read_only(m1, db):
    import sqlalchemy

    with m1.read_only(os.environ["DCL_DATABASE_URL"]) as session:
        with pytest.raises(sqlalchemy.exc.InternalError, match="read-only transaction"):
            session.execute(sqlalchemy.text("delete from drive_items"))
