"""Versions of a file changed in OneDrive (dispatcher/routing.py replace_older, dispatcher/versions.py).

The old version stays searchable until the new one is, is then removed except its history row, and comes back
when the file is reverted before that. Decisions carry over when unchanged (review/carry_over.py). Needs
DCL_TEST_DATABASE_URL; MinIO is a recording stand-in."""

import uuid

import pytest
from sqlalchemy import select

from backend.dispatcher.routing import replace_older
from backend.dispatcher.versions import Stores, purge_replaced
from backend.indexing.commit import OvertakenRun, commit_document
from backend.postgres.models import (
    Asset,
    Blob,
    Document,
    DocumentNode,
    DocumentRelation,
    DocumentSource,
    DriveItem,
    ReviewFlag,
    SyncRoot,
)
from backend.review.carry_over import carry_over

OLD, NEW = "a1" * 32, "b2" * 32


class Recorder:
    def __init__(self):
        self.deleted: list[str] = []

    def delete(self, key):
        self.deleted.append(key)

    def delete_prefix(self, prefix):
        self.deleted.append(prefix + "*")
        return 1


def _version(session, sha, status, title="Test_Report_12"):
    session.merge(Blob(sha256=sha, size_bytes=10, minio_uri=f"s3://dcl-raw/{sha[:2]}/{sha[2:4]}/{sha}"))
    document = Document(route="A1", status=status, title=title)
    session.add(document)
    session.flush()
    session.add(DocumentSource(doc_id=document.doc_id, blob_sha256=sha, role="primary"))
    session.flush()
    return document


@pytest.fixture()
def edited(session):
    """A report edited in place: the location holds the new bytes and remembers the old."""
    session.merge(SyncRoot(root_name="APU", remote_drive_id="d", remote_item_id="r"))
    old = _version(session, OLD, "ACTIVE")
    new = _version(session, NEW, "PROCESSING")
    session.add(
        DocumentNode(doc_id=old.doc_id, node_type="parent", ordinal=0, content="v1 text", source="printed")
    )
    session.add(Asset(minio_uri=f"s3://dcl-assets/pages/{OLD}/0001.png", blob_sha256=OLD, kind="page_render"))
    item = DriveItem(
        drive_id="d",
        item_id=f"i-{uuid.uuid4().hex[:6]}",
        root_name="APU",
        name="Test_Report_12.pdf",
        status="LANDED",
        blob_sha256=NEW,
        previous_blob_sha256=OLD,
    )
    session.add(item)
    session.flush()
    return old, new, item


def test_the_old_version_stays_searchable_until_the_new_one_is(session, edited):
    old, new, item = edited
    assert replace_older(session) == 0  # the new version is still being processed
    assert (old.status, item.previous_blob_sha256) == ("ACTIVE", OLD)
    new.status = "ACTIVE"  # committed
    assert replace_older(session, NEW) == 1
    assert (old.status, old.metadata_sources["replaced_by"], item.previous_blob_sha256) == (
        "SUPERSEDED",
        str(new.doc_id),
        None,
    )
    assert session.get(DocumentRelation, (new.doc_id, old.doc_id, "SUPERSEDES")) is not None


def test_a_replaced_version_is_removed_except_its_history_row(session, edited):
    old, new, _ = edited
    new.status = "ACTIVE"
    replace_older(session, NEW)
    question = ReviewFlag(
        case_key=f"{old.doc_id}:",
        doc_id=old.doc_id,
        fingerprint="f" * 64,
        flag_type="CONFLICT",
        severity="SOFT",
    )
    revision = _version(session, "c3" * 32, "SUPERSEDED", "ECSS Rev 1")  # a newer revision exists: kept
    session.add_all(
        [
            question,
            DocumentNode(
                doc_id=revision.doc_id, node_type="parent", ordinal=0, content="rev 1", source="printed"
            ),
        ]
    )
    session.flush()
    raw, cir, assets = Recorder(), Recorder(), Recorder()
    assert purge_replaced(session, Stores(raw, cir, assets)) == 1
    nodes = session.scalars(select(DocumentNode.doc_id)).all()
    assert (old.doc_id in nodes, revision.doc_id in nodes) == (False, True)
    assert session.get(Blob, OLD) is None and session.get(Blob, NEW) is not None
    assert session.scalars(select(DocumentSource).where(DocumentSource.doc_id == old.doc_id)).all() == []
    assert session.scalars(select(Asset).where(Asset.blob_sha256 == OLD)).all() == []
    assert (raw.deleted, cir.deleted, assets.deleted) == (
        [f"{OLD[:2]}/{OLD[2:4]}/{OLD}"],
        [f"{OLD}/*"],
        [f"pages/{OLD}/0001.png"],
    )
    assert (session.get(ReviewFlag, question.flag_id).status, old.status, old.title) == (
        "AUTO_RESOLVED",
        "SUPERSEDED",
        "Test_Report_12",
    )
    assert purge_replaced(session, Stores(raw, cir, assets)) == 0  # done once


def test_reverting_before_removal_brings_the_earlier_version_back(session, edited):
    old, new, item = edited
    new.status = "ACTIVE"
    replace_older(session, NEW)
    item.blob_sha256, item.previous_blob_sha256 = OLD, NEW  # the file is put back as it was
    session.flush()
    assert replace_older(session) == 1
    assert (old.status, new.status, new.metadata_sources["replaced_by"]) == (
        "ACTIVE",
        "SUPERSEDED",
        str(old.doc_id),
    )
    assert session.get(DocumentRelation, (new.doc_id, old.doc_id, "SUPERSEDES")) is None


def test_an_unchanged_question_keeps_its_decision_and_a_changed_one_is_asked_again(session, edited):
    old, new, _ = edited
    sides = {"kind": "conflict", "subject": "test plan id", "a": {"label": "folder", "value": "TP7"}}
    kept = ReviewFlag(
        case_key=f"{old.doc_id}:",
        doc_id=old.doc_id,
        fingerprint="1" * 64,
        flag_type="CONFLICT",
        severity="SOFT",
        evidence={**sides, "b": {"label": "content", "value": "TP6"}},
        status="RESOLVED",
        resolution={"action": "accept_both"},
        resolved_by="asha@x",
    )
    changed = ReviewFlag(
        case_key=f"{old.doc_id}:",
        doc_id=old.doc_id,
        fingerprint="2" * 64,
        flag_type="CONFLICT",
        severity="SOFT",
        evidence={**sides, "b": {"label": "content", "value": "TP5"}},
        status="RESOLVED",
        resolution={"action": "accept_both"},
        resolved_by="asha@x",
    )
    same_again = ReviewFlag(
        case_key=f"{new.doc_id}:",
        doc_id=new.doc_id,
        fingerprint="1" * 64,
        flag_type="CONFLICT",
        severity="SOFT",
        evidence={**sides, "b": {"label": "content", "value": "TP6"}},
        status="OPEN",
    )
    now_differs = ReviewFlag(
        case_key=f"{new.doc_id}:",
        doc_id=new.doc_id,
        fingerprint="2" * 64,
        flag_type="CONFLICT",
        severity="SOFT",
        evidence={**sides, "b": {"label": "content", "value": "TP4"}},
        status="OPEN",
    )
    session.add_all([kept, changed, same_again, now_differs])
    session.flush()
    assert carry_over(session, new.doc_id, NEW, [same_again, now_differs]) == 1
    assert (same_again.status, same_again.resolution, same_again.resolved_by) == (
        "RESOLVED",
        {"action": "accept_both"},
        "asha@x",
    )
    assert now_differs.status == "OPEN"


def test_a_run_that_its_document_outlived_is_not_committed(session, edited):
    old, _, _ = edited
    old.status = "SUPERSEDED"
    session.flush()
    with pytest.raises(OvertakenRun):
        commit_document(session, old, None, None, 1)
