import pytest

from backend.dispatcher.contract import Anchor, AnchorError
from backend.indexing.anchors import (
    ResolutionStatus,
    content_hash,
    make_anchor,
    normalize_content,
    resolve_among,
)
from backend.indexing.chunker import ChunkingConfig, chunk_document
from backend.postgres.enums import NodeType


def report(kit):
    """Twelve pages, one paragraph node each, with page boxes."""
    paragraphs = [
        kit.node(
            f"para{p}",
            " ".join(f"Page {p} sentence {i} says the pressure was {p}.{i} bar." for i in range(40)),
            p,
            page_no=p,
            bboxes=[kit.box(p)],
        )
        for p in range(1, 13)
    ]
    return kit.document(*paragraphs)


def test_hash_ignores_case_spacing_and_dash_variants():
    assert content_hash("PT‑101  rose\nto 12.4 bar") == content_hash("pt-101 rose to 12.4 BAR")
    assert normalize_content("  A B  ") == "a b"


def test_make_anchor_uses_the_page_and_round_trips_through_the_link_form(kit):
    child = next(
        n for n in chunk_document(report(kit), count_tokens=kit.words) if n.node_type is NodeType.CHILD
    )
    anchor = make_anchor(kit.doc_id, child)
    assert anchor.page_no == child.page_no == 1
    assert anchor.content_sha256 == child.content_sha256
    assert Anchor.parse(kit.doc_id, anchor.serialize()).model_dump(
        exclude={"breadcrumb"}
    ) == anchor.model_dump(exclude={"breadcrumb"})


def test_make_anchor_falls_back_to_line_then_time(kit):
    nodes = chunk_document(
        kit.document(
            kit.node(
                "code",
                "def f(): pass",
                0,
                node_type=NodeType.CODE_SYMBOL,
                line_start=88,
                source="source_code",
            ),
            kit.node("ev", "ignition flash", 1, node_type=NodeType.VIDEO_EVENT, t_start_ms=400),
        ),
        count_tokens=kit.words,
    )
    assert [make_anchor(kit.doc_id, n).serialize().split(":")[0] for n in nodes] == ["line", "t"]


def test_node_without_any_locator_cannot_be_anchored(kit):
    (summary,) = chunk_document(
        kit.document(kit.node("run", "TP07 T04 summary", 0, node_type=NodeType.RUN_SUMMARY)),
        count_tokens=kit.words,
    )
    with pytest.raises(AnchorError, match="locator"):
        make_anchor(kit.doc_id, summary)


def test_same_chunking_resolves_every_anchor_exactly_with_its_boxes(kit):
    nodes = chunk_document(report(kit), count_tokens=kit.words)
    for node in nodes:
        resolution = resolve_among(make_anchor(kit.doc_id, node), nodes)
        assert resolution.status is ResolutionStatus.EXACT
        assert node in resolution.matches
        assert all(box.page_no == node.page_no for box in resolution.boxes)


def test_anchors_survive_a_chunk_size_change_by_falling_back_to_the_page(kit):
    before = chunk_document(report(kit), count_tokens=kit.words)
    after = chunk_document(report(kit), ChunkingConfig(child_max_tokens=150), count_tokens=kit.words)
    statuses = []
    for node in before:
        resolution = resolve_among(make_anchor(kit.doc_id, node), after)
        statuses.append(resolution.status)
        assert resolution.status is not ResolutionStatus.DOCUMENT_ONLY
        assert resolution.page_no == node.page_no
        assert all(m.page_no <= node.page_no <= m.page_end for m in resolution.matches)
    assert ResolutionStatus.PAGE_FALLBACK in statuses
    assert ResolutionStatus.EXACT in statuses  # parents did not change


def test_moved_passage_still_resolves_exactly_on_its_new_page(kit):
    nodes = chunk_document(report(kit), count_tokens=kit.words)
    child = next(n for n in nodes if n.node_type is NodeType.CHILD and n.page_no == 3)
    stale = make_anchor(kit.doc_id, child).model_copy(update={"page_no": 2})
    resolution = resolve_among(stale, [n for n in nodes if n.node_type is NodeType.CHILD])
    assert resolution.status is ResolutionStatus.EXACT
    assert resolution.page_no == 3


def test_page_that_no_longer_exists_resolves_to_the_document(kit):
    nodes = chunk_document(report(kit), count_tokens=kit.words)
    anchor = Anchor(doc_id=kit.doc_id, page_no=40, content_sha256="ab" * 32)
    resolution = resolve_among(anchor, nodes)
    assert (resolution.status, resolution.page_no, resolution.matches) == (
        ResolutionStatus.DOCUMENT_ONLY,
        None,
        [],
    )


def test_short_hash_prefix_in_a_link_still_matches(kit):
    nodes = chunk_document(report(kit), count_tokens=kit.words)
    anchor = Anchor(doc_id=kit.doc_id, page_no=nodes[1].page_no, content_sha256=nodes[1].content_sha256[:16])
    assert resolve_among(anchor, nodes).status is ResolutionStatus.EXACT
