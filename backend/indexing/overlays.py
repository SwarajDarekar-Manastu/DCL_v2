"""Decisions re-applied on every commit (file 06 principle 8 and §6; file 04 §7).

A person's decision or a rule's answer is stored on the flag (``review_flags.resolution``, anchored by
page, line, sheet/column, bbox or content hash, never a node id). The commit applies it to what it writes:

- ``set_fact_unit``: the numbers of the flagged column or line get the unit (or stay unitless when the unit is
  null) and lose ``needs_unit``; a table's ``column_units`` records the decision.
- ``set_value``: the handwritten entry the flag names (``metadata.handwriting`` key = the anchor's
  ``content_sha256``) is the person's value (source ``human``); the old reading, or ``[illegible]``, is
  replaced in the node text and in its numbers.
- ``choose_table``: the flagged table is version B or the edited cells instead of version A.
- ``mark_junk`` on a page, or on a figure or table (a LOW_CONFIDENCE_EXTRACTION, file 06 §6): the nodes made
  only from it leave search, with their question proxies, numbers and entity mentions. Junk on a file flag
  takes the whole file out in review instead (review/cases.py) and has nothing to drop here.
- ``choose_source``: the document field the disagreement is about takes the chosen side's value.
- ``mark_superseded``: the other document is SUPERSEDED by this one.

``ignore`` and ``accept_both`` change no data: the flag is decided, so its nodes lose ``needs_review``.
Schema mappings change how the file is parsed and are read by the route itself.
"""

import html
import uuid
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.common.units import UnitError, parse_unit, to_canonical
from backend.dispatcher.contract import ILLEGIBLE
from backend.indexing.chunker import IndexNode
from backend.indexing.index_document import IndexPlan
from backend.llm_engine.enrichment.numeric_facts import FactDecision
from backend.postgres.enums import (
    DocumentRelationType,
    DocumentStatus,
    FlagStatus,
    NodeType,
    NumericFactSource,
)
from backend.postgres.models import Document, DocumentRelation, ReviewFlag
from backend.review.rule_answers import subject_key

DECIDED = (FlagStatus.RESOLVED, FlagStatus.AUTO_RESOLVED)
FIELD_BY_SUBJECT = {
    "test plan id": "test_plan_id",
    "test run id": "test_run_id",
    "hardware item": "hardware_item",
}
BBOX_DIGITS = 3


def decided_flags(session: Session, doc_id: uuid.UUID) -> list[ReviewFlag]:
    return [
        f
        for f in session.scalars(
            select(ReviewFlag).where(ReviewFlag.doc_id == doc_id, ReviewFlag.status.in_(DECIDED))
        )
        if f.resolution and f.resolution.get("action")
    ]


def _box(box: dict[str, Any] | None) -> tuple | None:
    if not box or not all(k in box for k in ("x0", "y0", "x1", "y1")):
        return None
    return tuple(round(float(box[k]), BBOX_DIGITS) for k in ("x0", "y0", "x1", "y1"))


def _at(node: IndexNode, anchor: dict[str, Any]) -> bool:
    """Whether ``node`` holds the place the anchor names (sheet, line, then page)."""
    if anchor.get("sheet") is not None:
        return node.sheet_name == anchor["sheet"]
    if anchor.get("line") is not None and node.line_start is not None:
        return node.line_start <= anchor["line"] <= (node.line_end or node.line_start)
    if anchor.get("page") is not None and node.page_no is not None:
        return node.page_no <= anchor["page"] <= (node.page_end or node.page_no)
    return False


def _with_unit(fact: FactDecision, unit: str | None) -> FactDecision:
    if unit is None:
        return replace(fact, needs_unit=False)
    value_si, unit_si = fact.value_si, fact.unit_si
    try:
        value_si, unit_si = to_canonical(float(fact.value_raw.replace(",", ".")), parse_unit(unit))
    except (UnitError, ValueError):
        pass
    return replace(fact, unit_raw=unit, value_si=value_si, unit_si=unit_si, needs_unit=False)


def _set_fact_unit(plan: IndexPlan, flag: ReviewFlag, unit: str | None) -> None:
    anchor, evidence = flag.anchor or {}, flag.evidence or {}
    refs = {n.ref for n in plan.nodes if _at(n, anchor)}
    value = evidence.get("value_raw")
    plan.facts = [
        _with_unit(f, unit)
        if f.node_ref in refs and f.needs_unit and (value is None or f.value_raw == value)
        else f
        for f in plan.facts
    ]
    column = anchor.get("column") or evidence.get("channel")
    if column:
        for node in plan.nodes:
            if node.ref in refs and node.node_type in (NodeType.TABLE, NodeType.TABLE_ROW):
                node.metadata = {
                    **node.metadata,
                    "column_units": {**node.metadata.get("column_units", {}), column: unit},
                }


def _set_value(plan: IndexPlan, flag: ReviewFlag, resolution: dict[str, Any]) -> None:
    anchor = flag.anchor or {}
    key = anchor.get("content_sha256")
    new = None if resolution.get("illegible") else resolution.get("value")
    for node in plan.nodes:
        if not _at(node, anchor):
            continue
        readings = node.metadata.get("handwriting") or []
        touched = False
        for reading in readings:
            if key is None or reading.get("key") != key:
                continue
            old = reading.get("value_raw")
            reading.update(value_raw=new, unit=resolution.get("unit"), illegible=new is None, source="human")
            touched = True
            shown = old or ILLEGIBLE
            if new and shown in node.content:
                node.content = node.content.replace(shown, new, 1)
            plan.facts = [
                replace(f, value_raw=new, source=NumericFactSource.HUMAN, confidence=1.0)
                if f.node_ref == node.ref and old and new and f.value_raw == old
                else f
                for f in plan.facts
            ]
        if touched:
            node.metadata = {**node.metadata, "handwriting": readings}


def _cells_html(cells: list[list[str]]) -> str:
    rows = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in cells)
    return f"<table>{rows}</table>"


def _choose_table(plan: IndexPlan, flag: ReviewFlag, resolution: dict[str, Any]) -> None:
    choice, evidence = resolution.get("choice"), flag.evidence or {}
    content = (
        evidence.get("table_b_html")
        if choice == "B"
        else _cells_html(resolution["cells"])
        if choice == "edited" and resolution.get("cells")
        else None
    )
    for node in plan.nodes:
        if node.node_type == NodeType.TABLE and _at(node, flag.anchor or {}):
            if content:
                node.content = content
            node.metadata = {**node.metadata, "table_choice": choice}


def overlay_plan(session: Session, doc_id: uuid.UUID, plan: IndexPlan) -> list[ReviewFlag]:
    """Apply the decisions that change nodes and numbers; returns the decided flags."""
    flags = decided_flags(session, doc_id)
    for flag in flags:
        resolution = flag.resolution
        action = resolution["action"]
        if action == "set_fact_unit":
            _set_fact_unit(plan, flag, resolution.get("unit"))
        elif action == "set_value":
            _set_value(plan, flag, resolution)
        elif action == "choose_table":
            _choose_table(plan, flag, resolution)
        elif action == "mark_junk":
            _junk(plan, flag)
    return flags


JUNKABLE_OBJECTS = (NodeType.FIGURE, NodeType.PHOTO, NodeType.TABLE)


def _junk(plan: IndexPlan, flag: ReviewFlag) -> None:
    anchor = flag.anchor or {}
    page, box = anchor.get("page"), _box(anchor.get("bbox"))
    if page is None:
        return

    def junked(node: IndexNode) -> bool:
        if node.page_no != page or (node.page_end or page) != page:
            return False
        if box is None:
            return True
        x0, y0, x1, y1 = box  # the flag's box is the padded crop: the object's centre lies inside it
        return node.node_type in JUNKABLE_OBJECTS and any(
            x0 <= (b.x0 + b.x1) / 2 <= x1 and y0 <= (b.y0 + b.y1) / 2 <= y1 for b in node.bboxes
        )

    origins = {ref for node in plan.nodes if junked(node) for ref in node.origin_refs}
    gone = {n.ref for n in plan.nodes if junked(n) or (n.origin_refs and set(n.origin_refs) <= origins)}
    while children := {n.ref for n in plan.nodes if n.parent_ref in gone and n.ref not in gone}:
        gone |= children
    plan.nodes = [n for n in plan.nodes if n.ref not in gone]
    plan.facts = [f for f in plan.facts if f.node_ref not in gone]
    plan.entities.mentions = [m for m in plan.entities.mentions if m.node_ref not in gone]


def overlay_document(session: Session, document: Document) -> None:
    """Apply the decisions that change the document row or other documents (after the commit's own checks and
    the flags the commit raises itself, which a rule may just have answered)."""
    for flag in decided_flags(session, document.doc_id):
        resolution, evidence = flag.resolution, flag.evidence or {}
        if resolution["action"] == "choose_source":
            field = FIELD_BY_SUBJECT.get(subject_key(evidence.get("subject")))
            side = evidence.get("a" if resolution.get("choice") == "A" else "b") or {}
            if field and side.get("value"):
                setattr(document, field, side["value"])
        elif resolution["action"] == "mark_superseded":
            supersede(
                session,
                document,
                uuid.UUID(str(resolution["superseded_doc_id"])),
                flag.resolved_by or "review",
            )


def supersede(session: Session, document: Document, other_id: uuid.UUID, by: str) -> None:
    """``document`` SUPERSEDES ``other_id``: the relation once, and the other document leaves the index."""
    other = session.get(Document, other_id)
    if other is None or other.doc_id == document.doc_id:
        return
    other.status = DocumentStatus.SUPERSEDED
    if (
        session.get(DocumentRelation, (document.doc_id, other.doc_id, DocumentRelationType.SUPERSEDES))
        is None
    ):
        session.add(
            DocumentRelation(
                doc_id_a=document.doc_id,
                doc_id_b=other.doc_id,
                relation=DocumentRelationType.SUPERSEDES,
                created_by=by,
            )
        )
