import re

import pytest

from backend.indexing.chunker import (
    ChunkingConfig,
    build_embed_texts,
    chunk_document,
    contextual_header,
    split_sentences,
)
from backend.indexing.tables import split_table, table_rows
from backend.postgres.enums import NodeType


def sentences(n, start=0, words=12):
    return " ".join(
        f"Sentence {i} " + " ".join(["word"] * (words - 3)) + " end." for i in range(start, start + n)
    )


def by_type(nodes, node_type):
    return [n for n in nodes if n.node_type is node_type]


def test_small_section_gives_one_parent_and_one_identical_child(kit):
    text = "The chamber pressure PT-101 rose to 12.4 bar. The bed reached 600 C."
    nodes = chunk_document(kit.document(kit.node("s1", text, 0, page_no=8)), count_tokens=kit.words)
    parent, child = nodes
    assert (parent.node_type, child.node_type) == (NodeType.PARENT, NodeType.CHILD)
    assert (parent.ref, child.ref, child.parent_ref) == ("s1#p0", "s1#p0c0", "s1#p0")
    assert parent.content == child.content == text
    assert [n.ordinal for n in nodes] == [0, 1]
    assert child.page_no == 8
    assert child.content_codes == "PT-101 PT101"
    assert len(child.content_sha256) == 64


def test_long_section_splits_at_paragraphs_under_1800_and_children_under_400(kit):
    paragraphs = [sentences(10, start=i * 10) for i in range(40)]  # 40 paragraphs x 120 words = 4,800
    nodes = chunk_document(kit.document(kit.node("s1", "\n\n".join(paragraphs), 0)), count_tokens=kit.words)
    parents, children = by_type(nodes, NodeType.PARENT), by_type(nodes, NodeType.CHILD)
    assert len(parents) == 3
    assert all(len(p.content.split()) <= 1800 for p in parents)
    for paragraph in paragraphs:
        assert sum(paragraph in p.content for p in parents) == 1
    assert all(250 <= len(c.content.split()) <= 400 for c in children)
    assert all(p.breadcrumb == "Test Report 37 › 3 Results" for p in parents)


def test_children_cut_only_at_sentence_ends_and_overlap_by_one_sentence(kit):
    text = sentences(100)
    nodes = chunk_document(kit.document(kit.node("s1", text, 0)), count_tokens=kit.words)
    children = by_type(nodes, NodeType.CHILD)
    assert len(children) >= 3
    for child in children:
        assert re.match(r"^Sentence \d+ ", child.content) and child.content.endswith("end.")
    for previous, current in zip(children, children[1:], strict=False):
        last = re.findall(r"Sentence \d+ [^.]*end\.", previous.content)[-1]
        assert current.content.startswith(last)


def test_display_equation_stays_with_its_defining_sentence(kit):
    text = (
        sentences(30) + " The bed loading G is defined as follows. $$G = \\dot m / A_b$$ " + sentences(30, 30)
    )
    children = by_type(
        chunk_document(kit.document(kit.node("s1", text, 0)), count_tokens=kit.words), NodeType.CHILD
    )
    holder = [c for c in children if "$$G" in c.content]
    assert holder and all("The bed loading G is defined as follows. $$G" in c.content for c in holder)


def test_paragraph_nodes_give_children_their_own_pages_and_boxes(kit):
    doc = kit.document(
        *[
            kit.node(f"para{i}", sentences(20, i * 20), i, page_no=i + 1, bboxes=[kit.box(i + 1)])
            for i in range(3)
        ]
    )
    nodes = chunk_document(doc, count_tokens=kit.words)
    parent = by_type(nodes, NodeType.PARENT)[0]
    assert (parent.page_no, parent.page_end, len(parent.bboxes)) == (1, 3, 3)
    first_child = by_type(nodes, NodeType.CHILD)[0]
    assert first_child.page_no == 1
    assert {b.page_no for b in first_child.bboxes} <= {1, 2}


def test_a_new_breadcrumb_starts_a_new_parent(kit):
    doc = kit.document(
        kit.node("a", "Procedure text.", 0, breadcrumb="TR37 › 2 Procedure"),
        kit.node("b", "Results text.", 1, breadcrumb="TR37 › 3 Results"),
    )
    parents = by_type(chunk_document(doc, count_tokens=kit.words), NodeType.PARENT)
    assert [p.content for p in parents] == ["Procedure text.", "Results text."]


def test_sentence_split_keeps_abbreviations_initials_and_decimals():
    text = "See Fig. 4 and approx. 12.4 bar per J. Smith. Next sentence here! 次の文。最後"
    assert split_sentences(text) == [
        "See Fig. 4 and approx. 12.4 bar per J. Smith.",
        "Next sentence here!",
        "次の文。",
        "最後",
    ]


def table_html(n_rows, words_per_cell=20, rowspan_at=None):
    cell = " ".join(["v"] * words_per_cell)
    rows = []
    for i in range(n_rows):
        if i == rowspan_at:
            rows.append(f'<tr><td rowspan="3">group {i}</td><td>{cell}</td></tr>')
        else:
            rows.append(f"<tr><td>r{i}</td><td>{cell}</td></tr>")
    return f'<table class="t"><thead><tr><th>Run</th><th>Pc (bar)</th></tr></thead>{"".join(rows)}</table>'


def test_small_table_stays_whole(kit):
    nodes = chunk_document(
        kit.document(kit.node("t1", table_html(5), 0, node_type=NodeType.TABLE, page_no=3)),
        count_tokens=kit.words,
    )
    assert [(n.ref, n.node_type) for n in nodes] == [("t1", NodeType.TABLE)]


def test_long_table_becomes_row_blocks_with_header_and_never_cuts_a_row_or_rowspan(kit):
    html = table_html(200, rowspan_at=40)
    header, rows = table_rows(html)
    blocks = split_table(html, 1200, kit.words)
    assert len(blocks) > 1
    rebuilt = []
    for block in blocks:
        assert len(block.split()) <= 1200
        block_header, block_rows = table_rows(block)
        assert block_header == header
        rebuilt.extend(block_rows)
    assert rebuilt == rows
    holder = next(b for b in blocks if "group 40" in b)
    assert "<td>r41</td>" in holder and "<td>r42</td>" in holder


def test_table_rows_point_at_the_first_block_of_a_split_table(kit):
    doc = kit.document(
        kit.node("t1", table_html(200), 0, node_type=NodeType.TABLE, page_no=3),
        kit.node("t1/r0", "Run r0 | 12.4", 1, node_type=NodeType.TABLE_ROW, parent_ref="t1", page_no=3),
    )
    nodes = chunk_document(doc, count_tokens=kit.words)
    tables = by_type(nodes, NodeType.TABLE)
    assert tables[0].ref == "t1#t0" and tables[0].metadata["part"] == f"1/{len(tables)}"
    assert by_type(nodes, NodeType.TABLE_ROW)[0].parent_ref == "t1#t0"


def test_special_nodes_pass_through_and_keep_their_text_parent_whole(kit):
    doc = kit.document(
        kit.node("sec0", sentences(200), 0, t_start_ms=0, t_end_ms=600_000, breadcrumb="Workshop"),
        kit.node(
            "w0", "first window", 1, node_type=NodeType.TRANSCRIPT_WINDOW, parent_ref="sec0", t_start_ms=0
        ),
        kit.node("fig1", "Plot of Pc", 2, node_type=NodeType.FIGURE, page_no=4, asset_ref=None),
    )
    nodes = chunk_document(doc, count_tokens=kit.words)
    assert [(n.ref, n.node_type, n.parent_ref) for n in nodes] == [
        ("sec0", NodeType.PARENT, None),
        ("w0", NodeType.TRANSCRIPT_WINDOW, "sec0"),
        ("fig1", NodeType.FIGURE, None),
    ]


def test_header_matches_the_manual_shape(kit):
    doc = kit.document().document
    header = contextual_header(
        doc.model_copy(update={"doc_date": __import__("datetime").date(2024, 5, 2)}),
        "Test Report 37 › 3 Hot Fire Results › 3.2 Chamber Pressure",
        ["injector INJ-14", "PT-101", "C-103"],
        ChunkingConfig(),
        kit.words,
    )
    assert header == (
        "Doc: Test Report 37 (test_report, internal, TP37, 2024-05-02)\n"
        "Section: 3 Hot Fire Results › 3.2 Chamber Pressure\n"
        "Entities: injector INJ-14, PT-101, C-103"
    )


def test_header_drops_entities_first_to_stay_within_80_tokens(kit):
    doc = kit.document().document
    entities = [f"entity{i}" for i in range(200)]
    header = contextual_header(doc, "Test Report 37 › 3 Results", entities, ChunkingConfig(), kit.words)
    assert len(header.split()) <= 80
    assert header.startswith("Doc: Test Report 37") and "Section: 3 Results" in header


def test_embed_text_hash_changes_with_the_title_but_not_with_ordinals(kit):
    doc = kit.document(kit.node("s1", "Pressure rose.", 0))
    first = build_embed_texts(
        chunk_document(doc, count_tokens=kit.words), doc.document, count_tokens=kit.words
    )
    renamed = doc.document.model_copy(update={"title": "Test Report 37 rev B"})
    second = build_embed_texts(chunk_document(doc, count_tokens=kit.words), renamed, count_tokens=kit.words)
    again = build_embed_texts(
        chunk_document(doc, count_tokens=kit.words), doc.document, count_tokens=kit.words
    )
    assert first[1].embed_text.endswith("---\nPressure rose.")
    assert first[1].embed_text_hash != second[1].embed_text_hash
    assert first[1].embed_text_hash == again[1].embed_text_hash


@pytest.fixture(scope="module")
def real_tokens():
    try:
        from backend.llm_engine.local_models import count_tokens

        count_tokens(["probe"])
    except Exception as exc:  # tokenizer not cached and no network
        pytest.skip(f"EmbeddingGemma tokenizer unavailable: {exc}")
    return count_tokens


def test_no_embed_text_exceeds_8000_tokens_with_the_real_tokenizer(kit, real_tokens):
    code = "def solve(x):\n" + "\n".join(
        f"    y{i} = compute(x, {i}) * 12.4  # step {i}" for i in range(6000)
    )
    doc = kit.document(
        kit.node("s1", "\n\n".join(sentences(30, i * 30) for i in range(40)), 0, page_no=1),
        kit.node("t1", table_html(2000, words_per_cell=8), 1, node_type=NodeType.TABLE, page_no=2),
        kit.node(
            "sym", code, 2, node_type=NodeType.CODE_SYMBOL, line_start=1, line_end=6001, source="source_code"
        ),
    )
    nodes = build_embed_texts(
        chunk_document(doc, count_tokens=real_tokens), doc.document, count_tokens=real_tokens
    )
    embedded = [n for n in nodes if n.embed]
    counts = real_tokens([n.embed_text for n in embedded])
    assert max(counts) <= 8000
    assert {n.node_type for n in embedded} >= {
        NodeType.PARENT,
        NodeType.CHILD,
        NodeType.TABLE,
        NodeType.CODE_SYMBOL,
    }
    assert max(c for n, c in zip(embedded, counts, strict=True) if n.node_type is NodeType.CHILD) <= 520
