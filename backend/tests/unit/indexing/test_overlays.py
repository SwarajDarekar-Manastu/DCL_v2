"""Decisions change the data (file 06 principle 8): the overlays the commit applies to the plan it writes."""

import uuid
from types import SimpleNamespace

from backend.indexing.chunker import IndexNode
from backend.indexing.index_document import IndexPlan
from backend.indexing.overlays import _choose_table, _set_fact_unit, _set_value
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


def test_a_typed_handwriting_value_replaces_the_model_reading_in_text_and_numbers():
    box = {"x0": 0.215, "y0": 0.603, "x1": 0.475, "y1": 0.623}
    node = _node(
        "p8",
        "Orifice dia: 0.8? mm",
        page_no=8,
        metadata={"handwriting": [{"bbox": {**box, "page_no": 8}, "value_raw": "0.8?", "label": "Orifice"}]},
    )
    plan = _plan([node], [_fact("p8", "0.8?", "mm")])
    flag = SimpleNamespace(anchor={"page": 8, "bbox": box}, evidence={})
    _set_value(plan, flag, {"action": "set_value", "value": "0.85", "unit": "mm", "illegible": False})
    (reading,) = plan.nodes[0].metadata["handwriting"]
    assert (plan.nodes[0].content, reading["value_raw"], reading["source"]) == (
        "Orifice dia: 0.85 mm",
        "0.85",
        "human",
    )
    assert (plan.facts[0].value_raw, plan.facts[0].source) == ("0.85", NumericFactSource.HUMAN)


def test_choosing_table_b_puts_version_b_in_the_table_node():
    plan = _plan([_node("t", "<table>A</table>", node_type=NodeType.TABLE, page_no=1)], [])
    flag = SimpleNamespace(anchor={"page": 1}, evidence={"table_b_html": "<table>B</table>"})
    _choose_table(plan, flag, {"action": "choose_table", "choice": "B"})
    assert (plan.nodes[0].content, plan.nodes[0].metadata["table_choice"]) == ("<table>B</table>", "B")
