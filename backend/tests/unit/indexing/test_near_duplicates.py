"""Near-duplicate reports (file 02 §5.3): MinHash signature, links on commit, re-index and operator rows."""

import uuid

import pytest
from sqlalchemy import select

from backend.indexing import near_duplicates as nd
from backend.postgres.models import (
    Blob,
    Document,
    DocumentNode,
    DocumentRelation,
    DocumentSource,
    DriveItem,
    SyncRoot,
)
from backend.tests.unit.sync.conftest import engine, session  # noqa: F401

WORDS = 1000


def text_of(words: int = WORDS, seed: str = "a") -> str:
    return " ".join(f"{seed}{i}" for i in range(words))


def edited(text: str, count: int) -> str:
    """``text`` with ``count`` evenly spaced words replaced: each touches five shingles."""
    words = text.split()
    for k in range(count):
        words[k * (len(words) // count)] = f"changed{k}"
    return " ".join(words)


def score(a: str, b: str) -> float:
    sa, sb = nd.signature(a), nd.signature(b)
    assert sa is not None and sb is not None
    return nd.similarity(sa, sb)


def test_identical_text_scores_one_and_a_small_edit_stays_above_the_threshold():
    base = text_of()
    assert score(base, base) == 1.0
    assert 0.9 <= score(base, edited(base, 4)) < 1.0


def test_a_heavy_edit_and_unrelated_text_stay_below_the_threshold():
    base = text_of()
    assert score(base, edited(base, 60)) < nd.THRESHOLD
    assert score(base, text_of(seed="z")) < 0.1


def test_numbers_stay_in_the_shingles():
    one = "peak chamber pressure 12.4 bar at the valve " + text_of(200)
    other = "peak chamber pressure 14.1 bar at the valve " + text_of(200)
    assert nd.THRESHOLD <= score(one, other) < 1.0


def test_table_markup_does_not_change_the_signature():
    plain = text_of(200)
    marked = "<table><tr><td>" + plain.replace(" ", "</td><td>") + "</td></tr></table>"
    assert score(plain, marked) == 1.0


def test_short_text_has_no_signature():
    assert nd.signature(text_of(30)) is None


def _doc(db, root: str, title: str, text: str, *, status: str = "ACTIVE", route: str = "A1") -> Document:
    sha = uuid.uuid4().hex + uuid.uuid4().hex
    db.add(Blob(sha256=sha, size_bytes=1, minio_uri=f"s3://dcl-raw/{sha}"))
    db.flush()
    db.add(
        DriveItem(
            drive_id="D",
            item_id=title,
            root_name=root,
            name=f"{title}.pdf",
            parent_item_id="F",
            path_cached=f"{root}/{title}.pdf",
            status="LANDED",
            blob_sha256=sha,
        )
    )
    doc = Document(route=route, status=status, title=title)
    db.add(doc)
    db.flush()
    db.add(DocumentSource(doc_id=doc.doc_id, blob_sha256=sha, role="primary"))
    db.add(DocumentNode(doc_id=doc.doc_id, node_type="parent", ordinal=0, content=text, source="printed"))
    db.flush()
    return doc


def links(db) -> list[DocumentRelation]:
    return list(db.scalars(select(DocumentRelation).where(DocumentRelation.relation == "NEAR_DUPLICATE")))


def test_a_similar_report_is_linked_with_its_score_and_both_stay_active(session):  # noqa: F811
    v1 = _doc(session, "APU Injector", "Test report v1", text_of())
    v2 = _doc(session, "APU Injector", "Test report v2", edited(text_of(), 4))
    assert nd.apply_near_duplicates(session, v1) == []
    found = nd.apply_near_duplicates(session, v2)
    assert [other for other, _ in found] == [v1.doc_id]
    (row,) = links(session)
    assert (row.doc_id_a, row.doc_id_b) == tuple(sorted([v1.doc_id, v2.doc_id]))
    assert (
        row.created_by == "minhash" and row.score == pytest.approx(found[0][1]) and row.score >= nd.THRESHOLD
    )
    assert (v1.status, v2.status) == ("ACTIVE", "ACTIVE")


def test_unrelated_short_other_route_and_other_root_documents_are_not_linked(session):  # noqa: F811
    session.add(SyncRoot(root_name="Other root", remote_drive_id="D2", remote_item_id="ROOT2"))
    session.flush()
    base = _doc(session, "APU Injector", "Base", text_of())
    for other in (
        _doc(session, "APU Injector", "Unrelated", text_of(seed="z")),
        _doc(session, "APU Injector", "Short", text_of(30)),
        _doc(session, "APU Injector", "Other route", text_of(), route="E"),
        _doc(session, "Other root", "Other root copy", text_of()),
        _doc(session, "APU Injector", "Superseded", text_of(), status="SUPERSEDED"),
    ):
        nd.apply_near_duplicates(session, other)
    assert nd.apply_near_duplicates(session, base) == []
    assert links(session) == []


def test_a_reindex_replaces_only_its_own_links(session):  # noqa: F811
    old = _doc(session, "APU Injector", "Old", text_of())
    new = _doc(session, "APU Injector", "New", edited(text_of(), 4))
    third = _doc(session, "APU Injector", "Third", text_of(seed="q"))
    nd.apply_near_duplicates(session, old)
    nd.apply_near_duplicates(session, new)
    a, b = sorted([new.doc_id, third.doc_id])
    session.add(
        DocumentRelation(doc_id_a=a, doc_id_b=b, relation="NEAR_DUPLICATE", score=1.0, created_by="operator")
    )
    session.flush()

    assert len(nd.apply_near_duplicates(session, new)) == 1  # same text again: one link, not two
    assert sorted(r.created_by for r in links(session)) == ["minhash", "operator"]

    session.execute(
        DocumentNode.__table__.update()
        .where(DocumentNode.doc_id == new.doc_id)
        .values(content=text_of(seed="r"))
    )
    session.expire(new)
    assert (
        nd.apply_near_duplicates(session, new) == []
    )  # the text diverged: its link goes, the operator's stays
    assert [r.created_by for r in links(session)] == ["operator"]


def test_backfill_links_documents_that_have_no_signature_yet(session):  # noqa: F811
    _doc(session, "APU Injector", "A", text_of())
    _doc(session, "APU Injector", "B", edited(text_of(), 4))
    _doc(session, "APU Injector", "C", text_of(seed="z"))
    assert [(a, b) for a, b, _ in nd.report(session, floor=0.85)] == [("A", "B")]
    assert nd.backfill(session) == 1
    assert len(links(session)) == 1
    assert nd.backfill(session) == 1  # running it again changes nothing
    assert len(links(session)) == 1


def _committed(db, kit, title: str, body: str) -> Document:
    from backend.indexing.commit import commit_document
    from backend.indexing.index_document import index_document
    from backend.llm_engine.enrichment.entities import AliasIndex

    document = _doc(db, "APU Injector", title, "placeholder")
    processed = kit.document(kit.node("body", body, 0, page_no=1))
    plan = index_document(
        processed,
        doc_id=document.doc_id,
        gemini=None,
        embed_documents=lambda texts, titles: [[0.01] * 768 for _ in texts],
        embed_images=None,
        asset_bytes=None,
        alias_index=AliasIndex(),
        reuse_vectors=lambda hashes: {},
        cloud_allowed=False,
        count_tokens=kit.words,
    )
    commit_document(db, document, processed, plan, 1)
    return document


def test_committing_a_second_version_of_a_report_links_it_to_the_first(session, kit):  # noqa: F811
    first = _committed(session, kit, "Report v1", text_of())
    second = _committed(session, kit, "Report v2", edited(text_of(), 4))
    other = _committed(session, kit, "Different report", text_of(seed="z"))
    assert first.minhash is not None
    (row,) = links(session)
    assert {row.doc_id_a, row.doc_id_b} == {first.doc_id, second.doc_id}
    assert other.doc_id not in {row.doc_id_a, row.doc_id_b}
    assert (first.status, second.status) == ("ACTIVE", "ACTIVE")
