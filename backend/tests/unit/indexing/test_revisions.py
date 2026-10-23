"""Revision supersession for drawings (file 02 §5.1): newer revision supersedes, equal revisions conflict."""

import uuid

import pytest
from sqlalchemy import select

from backend.indexing.revisions import Revision, apply_revisions, title_base
from backend.postgres.models import Blob, Document, DocumentRelation, DocumentSource, DriveItem, ReviewFlag
from backend.tests.unit.sync.conftest import engine, session  # noqa: F401


@pytest.mark.parametrize(
    ("marker", "kind", "value"),
    [("Rev C", "letter", 3), ("rev.B", "letter", 2), ("Revision AA", "letter", 27), ("Rev 12", "number", 12)],
)
def test_revision_tokens(marker, kind, value):
    assert Revision.parse(marker) == Revision(kind, value)


def test_titles_match_without_the_revision_token():
    assert title_base("Feed system Rev C") == title_base("Feed_system - rev.B") == "feed system"
    assert Revision.parse("Feed system") is None


def _doc(db, folder: str, title: str, marker: str) -> Document:
    sha = uuid.uuid4().hex + uuid.uuid4().hex
    db.add(Blob(sha256=sha, size_bytes=1, minio_uri=f"s3://dcl-raw/{sha}"))
    db.flush()
    db.add(
        DriveItem(
            drive_id="D",
            item_id=title,
            root_name="APU Injector",
            name=f"{title}.drawio",
            parent_item_id=folder,
            path_cached=f"APU Injector/TP22/{title}.drawio",
            status="LANDED",
            blob_sha256=sha,
        )
    )
    doc = Document(route="E", status="ACTIVE", title=title, revision_marker=marker)
    db.add(doc)
    db.flush()
    db.add(DocumentSource(doc_id=doc.doc_id, blob_sha256=sha, role="primary"))
    db.flush()
    return doc


def test_newer_revision_supersedes_and_a_twin_claim_conflicts(session):  # noqa: F811
    old = _doc(session, "F-TP22", "Feed system Rev B", "Rev B")
    twin = _doc(session, "F-TP22", "Feed system rev C (copy)", "Rev C")
    other_folder = _doc(session, "F-ELSE", "Feed system Rev A", "Rev A")
    new = _doc(session, "F-TP22", "Feed system Rev C", "Rev C")
    twin.title = "Feed system rev C"  # the same drawing claimed twice
    session.flush()
    events = apply_revisions(session, new)
    assert sorted(e.split(":")[0] for e in events) == ["conflict", "supersedes"]
    assert (old.status, other_folder.status, twin.status, new.status) == (
        "SUPERSEDED",
        "ACTIVE",
        "ACTIVE",
        "ACTIVE",
    )
    assert session.get(DocumentRelation, (new.doc_id, old.doc_id, "SUPERSEDES")) is not None
    conflicts = session.scalars(select(ReviewFlag).where(ReviewFlag.flag_type == "CONFLICT")).all()
    assert sorted(str(f.doc_id) for f in conflicts) == sorted([str(new.doc_id), str(twin.doc_id)])
    assert apply_revisions(session, new) == ["conflict:" + str(twin.doc_id)]  # idempotent: B is settled now


def test_an_older_revision_arriving_late_is_superseded_itself(session):  # noqa: F811
    newer = _doc(session, "F-TP22", "Valve block Rev 3", "Rev 3")
    late = _doc(session, "F-TP22", "Valve block Rev 2", "Rev 2")
    assert apply_revisions(session, late) == [f"superseded_by:{newer.doc_id}"]
    assert (late.status, newer.status) == ("SUPERSEDED", "ACTIVE")
