"""Decisions change the data (file 06 principle 8): the overlays the commit applies to the plan it writes."""

import uuid
from types import SimpleNamespace

from backend.dispatcher.contract import PageBox
from backend.indexing.chunker import IndexNode
from backend.indexing.index_document import IndexPlan
from backend.indexing.overlays import _choose_table, _junk, _set_fact_unit, _set_value
from backend.llm_engine.enrichment.entities import EntityDecisions
from backend.llm_engine.enrichment.numeric_facts import FactDecision
from backend.postgres.enums import GaugeOrAbs, NodeSource, NodeType, NumericFactSource, Quantity


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


def test_a_typed_handwriting_value_replaces_the_model_reading_in_text_and_numbers():
    node = _node(
        "p8",
        "Orifice dia: 0.8? mm",
        page_no=8,
        metadata={"handwriting": [{"key": KEY, "value_raw": "0.8?", "label": "Orifice"}]},
    )
    plan = _plan([node], [_fact("p8", "0.8?", "mm")])
    flag = SimpleNamespace(anchor={"page": 8, "content_sha256": KEY}, evidence={})
    _set_value(plan, flag, {"action": "set_value", "value": "0.85", "unit": "mm", "illegible": False})
    (reading,) = plan.nodes[0].metadata["handwriting"]
    assert (plan.nodes[0].content, reading["value_raw"], reading["source"]) == (
        "Orifice dia: 0.85 mm",
        "0.85",
        "human",
    )
    assert (plan.facts[0].value_raw, plan.facts[0].source) == ("0.85", NumericFactSource.HUMAN)


def test_a_value_typed_for_an_illegible_entry_replaces_the_illegible_mark():
    node = _node(
        "p2",
        "<td>Tare weight (g)</td><td>[illegible]</td>",
        page_no=2,
        metadata={
            "handwriting": [{"key": KEY, "value_raw": None, "label": "Tare weight (g)", "illegible": True}]
        },
    )
    plan = _plan([node], [])
    flag = SimpleNamespace(anchor={"page": 2, "content_sha256": KEY}, evidence={})
    _set_value(plan, flag, {"action": "set_value", "value": "36.706", "unit": "g", "illegible": False})
    assert plan.nodes[0].content == "<td>Tare weight (g)</td><td>36.706</td>"


def _box(page, x0, y0, x1, y1):
    return PageBox(page_no=page, x0=x0, y0=y0, x1=x1, y1=y1)


def _report():
    """Page 41: text, a photo (Docling's box) with a question proxy; page 42: text."""
    return _plan(
        [
            _node("t41", "Injector INJ-09 after the firing.", page_no=41, origin_refs=["t41"]),
            _node(
                "fig",
                "Photo: eroded injector face",
                NodeType.FIGURE,
                page_no=41,
                bboxes=[_box(41, 0.12, 0.22, 0.38, 0.48)],
                origin_refs=["fig"],
            ),
            _node(
                "fig-q",
                "What does the injector face show?",
                NodeType.QUESTION_PROXY,
                page_no=41,
                origin_refs=["fig"],
            ),
            _node("t42", "Throat 11.36 mm", page_no=42, origin_refs=["t42"]),
        ],
        [_fact("fig", "11.32", "mm"), _fact("t42", "11.36", "mm")],
    )


def test_junking_an_image_drops_only_that_image_its_proxy_and_its_numbers():
    plan = _report()
    crop = {"x0": 0.1, "y0": 0.2, "x1": 0.4, "y1": 0.5}  # the flag's box is the padded crop around Docling's
    _junk(plan, SimpleNamespace(anchor={"page": 41, "bbox": crop}))
    assert [n.ref for n in plan.nodes] == ["t41", "t42"]
    assert [f.node_ref for f in plan.facts] == ["t42"]


def test_junking_a_page_drops_that_page_and_keeps_the_rest_of_the_file():
    plan = _report()
    _junk(plan, SimpleNamespace(anchor={"page": 41}))
    assert [n.ref for n in plan.nodes] == ["t42"]
    assert [f.node_ref for f in plan.facts] == ["t42"]


def test_choosing_table_b_puts_version_b_in_the_table_node():
    plan = _plan([_node("t", "<table>A</table>", node_type=NodeType.TABLE, page_no=1)], [])
    flag = SimpleNamespace(anchor={"page": 1}, evidence={"table_b_html": "<table>B</table>"})
    _choose_table(plan, flag, {"action": "choose_table", "choice": "B"})
    assert (plan.nodes[0].content, plan.nodes[0].metadata["table_choice"]) == ("<table>B</table>", "B")
