"""Decisions change the data (file 06 principle 8): applied to the route's document before it is chunked
(``apply_decisions``), so what is indexed is the decided content; units on the extracted numbers after."""

import uuid
from types import SimpleNamespace

from backend.dispatcher.contract import DocumentFields, Mention, PageBox, ProcessedDocument, ProcessedNode
from backend.indexing.chunker import IndexNode, chunk_document
from backend.indexing.index_document import IndexPlan
from backend.indexing.overlays import _set_fact_unit, apply_decisions, overlay_plan
from backend.llm_engine.enrichment.entities import EntityDecisions
from backend.llm_engine.enrichment.numeric_facts import FactDecision
from backend.postgres.enums import GaugeOrAbs, NodeSource, NodeType, NumericFactSource, Quantity, Route


def _node(ref, content, node_type=NodeType.CHILD, **kw) -> IndexNode:
    return IndexNode(
        ref=ref,
        parent_ref=None,
        node_type=node_type,
        level=1,
        ordinal=0,
        breadcrumb="Report",
        language="en",
        content=content,
        content_codes=content,
        content_sha256="0" * 64,
        token_count=5,
        source=NodeSource.PRINTED,
        embed=True,
        **kw,
    )


def _fact(ref, value, unit=None) -> FactDecision:
    return FactDecision(
        node_ref=ref,
        quantity=Quantity.PRESSURE,
        value_raw=value,
        unit_raw=unit,
        value_si=None,
        unit_si=None,
        gauge_or_abs=GaugeOrAbs.UNKNOWN,
        context="chamber pressure",
        span_start=None,
        span_end=None,
        source=NumericFactSource.TABLE,
        suspect=False,
        needs_unit=unit is None,
    )


def _plan(nodes, facts) -> IndexPlan:
    return IndexPlan(doc_id=uuid.uuid4(), nodes=nodes, entities=EntityDecisions(), facts=facts, document={})


def test_a_unit_decision_gives_the_flagged_numbers_their_unit_and_nothing_else():
    plan = _plan(
        [_node("a", "Pc 12.4", line_start=1, line_end=10), _node("b", "Pc 12.4", line_start=11, line_end=20)],
        [_fact("a", "12.4"), _fact("a", "9.1"), _fact("b", "12.4")],
    )
    flag = SimpleNamespace(anchor={"line": 5}, evidence={"kind": "unit_fact", "value_raw": "12.4"})
    _set_fact_unit(plan, flag, "bar")
    fixed, other_value, other_node = plan.facts
    assert (fixed.unit_raw, fixed.needs_unit, fixed.value_si, fixed.unit_si) == (
        "bar",
        False,
        12.4,
        "bar",
    )  # bar is the canonical pressure unit (common/units.py)
    assert (other_value.unit_raw, other_node.unit_raw) == (None, None)


def test_leave_as_text_keeps_the_number_unitless_and_decided():
    plan = _plan([_node("a", "C_F -0.88", line_start=120, line_end=130)], [_fact("a", "-0.88")])
    _set_fact_unit(plan, SimpleNamespace(anchor={"line": 126}, evidence={"value_raw": "-0.88"}), None)
    assert (plan.facts[0].unit_raw, plan.facts[0].needs_unit) == (None, False)


KEY = "ab" * 16


def words(texts):
    return [len(text.split()) for text in texts]


def _route_node(ref, content, node_type=NodeType.CHILD, **kw) -> ProcessedNode:
    return ProcessedNode(
        ref=ref,
        node_type=node_type,
        ordinal=0,
        breadcrumb="Report",
        content=content,
        source=NodeSource.VLM,
        **kw,
    )


def _document(nodes, mentions=()) -> ProcessedDocument:
    sha = "cd" * 32
    return ProcessedDocument(
        blob_sha256=sha,
        route=Route.A1,
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{sha}/A1/v1/",
        document=DocumentFields(title="Report", test_plan_id="TP6"),
        nodes=nodes,
        mentions=list(mentions),
    )


def _decided(action, anchor, evidence=None, **resolution):
    return SimpleNamespace(
        anchor=anchor, evidence=evidence or {}, resolution={"action": action, **resolution}, resolved_at=None
    )


def test_a_typed_handwriting_value_is_what_gets_chunked_not_the_model_reading():
    node = _route_node(
        "vlm/p8/0",
        "Orifice dia: 0.8? mm",
        page_no=8,
        metadata={"handwriting": [{"key": KEY, "value_raw": "0.8?", "label": "Orifice"}]},
    )
    flag = _decided("set_value", {"page": 8, "content_sha256": KEY}, value="0.85", unit="mm", illegible=False)
    decided = apply_decisions(_document([node]), [flag])
    (reading,) = decided.nodes[0].metadata["handwriting"]
    assert (decided.nodes[0].content, reading["value_raw"], reading["source"]) == (
        "Orifice dia: 0.85 mm",
        "0.85",
        "human",
    )
    chunks = [n.content for n in chunk_document(decided, count_tokens=words)]
    assert any("0.85 mm" in c for c in chunks) and not any("0.8?" in c for c in chunks)


def test_a_value_typed_for_an_illegible_entry_replaces_the_illegible_mark():
    node = _route_node(
        "vlm/p2/0",
        "<td>Tare weight (g)</td><td>[illegible]</td>",
        page_no=2,
        metadata={
            "handwriting": [{"key": KEY, "value_raw": None, "label": "Tare weight (g)", "illegible": True}]
        },
    )
    flag = _decided(
        "set_value", {"page": 2, "content_sha256": KEY}, value="36.706", unit="g", illegible=False
    )
    assert (
        apply_decisions(_document([node]), [flag]).nodes[0].content
        == "<td>Tare weight (g)</td><td>36.706</td>"
    )


def test_the_numbers_of_a_typed_value_are_the_persons():
    plan = _plan(
        [_node("p8", "Orifice dia: 0.85 mm", page_no=8)], [_fact("p8", "0.85", "mm"), _fact("p8", "3.2")]
    )
    flag = _decided("set_value", {"page": 8, "content_sha256": KEY}, value="0.85", unit="mm", illegible=False)
    session = SimpleNamespace(scalars=lambda _: [SimpleNamespace(**vars(flag), status="RESOLVED")])
    overlay_plan(session, plan.doc_id, plan)
    assert [f.source for f in plan.facts] == [NumericFactSource.HUMAN, NumericFactSource.TABLE]


def _box(page, x0, y0, x1, y1):
    return PageBox(page_no=page, x0=x0, y0=y0, x1=x1, y1=y1)


def _report():
    """Page 41: text and a photo (Docling's box) with a caption under it and a mention; page 42: text."""
    return _document(
        [
            _route_node("t41", "Injector INJ-09 after the firing.", page_no=41),
            _route_node(
                "fig",
                "Photo: eroded injector face",
                NodeType.FIGURE,
                page_no=41,
                bboxes=[_box(41, 0.12, 0.22, 0.38, 0.48)],
            ),
            _route_node("fig-cap", "Figure 7: injector face", parent_ref="fig", page_no=41),
            _route_node("t42", "Throat 11.36 mm", page_no=42),
        ],
        [
            Mention(node_ref="fig", kind="part_number", surface="INJ-09"),
            Mention(node_ref="t42", kind="part_number", surface="INJ-10"),
        ],
    )


def test_junking_an_image_drops_only_that_image_what_hangs_under_it_and_its_mentions():
    crop = {"x0": 0.1, "y0": 0.2, "x1": 0.4, "y1": 0.5}  # the flag's box is the padded crop around Docling's
    decided = apply_decisions(_report(), [_decided("mark_junk", {"page": 41, "bbox": crop})])
    assert [n.ref for n in decided.nodes] == ["t41", "t42"]
    assert [m.node_ref for m in decided.mentions] == ["t42"]


def test_junking_a_page_leaves_nothing_of_it_to_chunk():
    decided = apply_decisions(_report(), [_decided("mark_junk", {"page": 41})])
    assert [n.ref for n in decided.nodes] == ["t42"]
    assert not any("INJ-09" in n.content for n in chunk_document(decided, count_tokens=words))


def test_choosing_table_b_changes_only_the_flagged_table_and_is_what_gets_chunked():
    flagged = _route_node(
        "tA",
        "<table><tr><td>austenic</td></tr></table>",
        NodeType.TABLE,
        page_no=33,
        bboxes=[_box(33, 0.1, 0.1, 0.9, 0.5)],
    )
    other = _route_node(
        "tB",
        "<table><tr><td>other</td></tr></table>",
        NodeType.TABLE,
        page_no=33,
        bboxes=[_box(33, 0.1, 0.6, 0.9, 0.9)],
    )
    flag = _decided(
        "choose_table",
        {"page": 33, "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.5}},
        {"table_b_html": "<table><tr><td>austenitic</td></tr></table>"},
        choice="B",
    )
    decided = apply_decisions(_document([flagged, other]), [flag])
    assert [n.content for n in decided.nodes] == [
        "<table><tr><td>austenitic</td></tr></table>",
        other.content,
    ]
    tables = [n.content for n in chunk_document(decided, count_tokens=words) if n.node_type == NodeType.TABLE]
    assert any("austenitic" in c for c in tables) and not any("austenic<" in c for c in tables)


def test_a_chosen_side_sets_the_document_field_every_node_row_is_written_from():
    flag = _decided(
        "choose_source",
        {},
        {
            "subject": "test_plan_id",
            "a": {"label": "folder", "value": "TP7"},
            "b": {"label": "content", "value": "TP6"},
        },
        choice="A",
    )
    assert (
        apply_decisions(_document([_route_node("t", "x", page_no=1)]), [flag]).document.test_plan_id == "TP7"
    )


def test_a_cell_corrected_on_the_page_check_is_what_gets_chunked_while_it_still_reads_the_same():
    from backend.review.page_reading import block_key

    table = "<table><tr><td>Time</td><td>T2 [C]</td></tr><tr><td>09:10</td><td>40.25</td></tr></table>"
    node = _route_node("vlm/p11/2", table, page_no=11)
    fix = _decided(
        "set_cell",
        {"page": 11},
        block_key=block_key(table),
        table=0,
        row=1,
        col=1,
        old="40.25",
        value="40.52",
    )
    stale = _decided(
        "set_cell", {"page": 11}, block_key=block_key(table), table=0, row=1, col=1, old="1.0", value="x"
    )
    decided = apply_decisions(_document([node]), [fix, stale])
    assert decided.nodes[0].content == table.replace("40.25", "40.52")
    chunks = " ".join(n.content for n in chunk_document(decided, count_tokens=words))
    assert "40.52" in chunks and "40.25" not in chunks
