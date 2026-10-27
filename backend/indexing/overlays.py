"""Decisions re-applied on every run (file 06 principle 8 and §6; file 04 §7).

A person's decision or a rule's answer is stored on the flag (``review_flags.resolution``, anchored by
page, line, sheet/column, bbox or content hash, never a node id). ``apply_decisions`` applies it to the
route's own document when it leaves the gate (review/staged.py), before chunking, so the search text,
vectors, table summaries, numbers and card are all built from the decided content. Applied after chunking
(until 2026-10-27), a typed handwriting value never found its entry (the chunker keeps no text-node
metadata) and a chosen table B was stored while search still read table A.

- ``set_value``: the handwritten entry the flag names (``metadata.handwriting`` key = the anchor's
  ``content_sha256``) is the person's value (source ``human``); the old reading, or ``[illegible]``, is
  replaced in the node text; its numbers are marked ``human`` after extraction (``overlay_plan``).
- ``set_cell`` / ``set_text`` (the page check, review/page_reading.py): a cell or a line of a page read whole
  that the reader did not flag is the person's text, while it still reads what the person saw.
- ``choose_table``: the flagged table (the table on the page whose centre lies in the flag's box) is
  version B or the edited cells instead of version A.
- ``mark_junk`` on a page, or on a figure or table (a LOW_CONFIDENCE_EXTRACTION, file 06 §6): the route's
  nodes of it, their children and mentions leave the document, so nothing is built from them. Junk on a file
  flag takes the whole file out in review instead (review/cases.py) and has nothing to drop here.
- ``choose_source``: the document field the disagreement is about takes the chosen side's value, in the
  node rows (here) and in the documents row (``overlay_document``).
- ``set_fact_unit`` (``overlay_plan``, after the numbers are extracted): the numbers of the flagged column or
  line get the unit (or stay unitless when the unit is null) and lose ``needs_unit``; a table's
  ``column_units`` records the decision.
- ``mark_superseded`` (``overlay_document``): the other document is SUPERSEDED by this one.

``ignore`` and ``accept_both`` change no data: the flag is decided, so its nodes lose ``needs_review``.
Schema mappings change how the file is parsed and are read by the route itself.
"""

import html
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.common.units import UnitError, parse_unit, to_canonical
from backend.dispatcher.contract import (
    FIELD_BY_SUBJECT,
    ILLEGIBLE,
    DocumentFields,
    ProcessedDocument,
    ProcessedNode,
    subject_key,
)
from backend.indexing.chunker import IndexNode
from backend.indexing.index_document import IndexPlan
from backend.llm_engine.enrichment.numeric_facts import FactDecision
from backend.postgres.enums import (
    DocumentRelationType,
    DocumentStatus,
    FlagStatus,
    NodeSource,
    NodeType,
    NumericFactSource,
)
from backend.postgres.models import Document, DocumentRelation, ReviewFlag
from backend.review.page_reading import block_key, set_cell, set_text

DECIDED = (FlagStatus.RESOLVED, FlagStatus.AUTO_RESOLVED)
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


def _at(node: IndexNode | ProcessedNode, anchor: dict[str, Any]) -> bool:
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


def _cells_html(cells: list[list[str]]) -> str:
    rows = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in cells)
    return f"<table>{rows}</table>"


def _inside(node: ProcessedNode, box: tuple | None) -> bool:
    """Whether the node's centre lies in the flag's box (a figure or table flag's box is its padded crop);
    no box on the flag means the whole page."""
    if box is None:
        return True
    x0, y0, x1, y1 = box
    return any(x0 <= (b.x0 + b.x1) / 2 <= x1 and y0 <= (b.y0 + b.y1) / 2 <= y1 for b in node.bboxes)


def _with_value(node: ProcessedNode, anchor: dict[str, Any], resolution: dict[str, Any]) -> ProcessedNode:
    key = anchor.get("content_sha256")
    readings = node.metadata.get("handwriting") or []
    if key is None or not _at(node, anchor) or not any(r.get("key") == key for r in readings):
        return node
    new = None if resolution.get("illegible") else resolution.get("value")
    content, updated = node.content, []
    for reading in readings:
        if reading.get("key") == key:
            shown = reading.get("value_raw") or ILLEGIBLE
            if new and shown in content:
                content = content.replace(shown, new, 1)
            reading = {
                **reading,
                "value_raw": new,
                "unit": resolution.get("unit"),
                "illegible": new is None,
                "source": "human",
            }
        updated.append(reading)
    return node.model_copy(update={"content": content, "metadata": {**node.metadata, "handwriting": updated}})


def _with_table(node: ProcessedNode, flag: ReviewFlag) -> ProcessedNode:
    anchor, evidence, resolution = flag.anchor or {}, flag.evidence or {}, flag.resolution
    if (
        node.node_type != NodeType.TABLE
        or not _at(node, anchor)
        or not _inside(node, _box(anchor.get("bbox")))
    ):
        return node
    choice = resolution.get("choice")
    content = (
        evidence.get("table_b_html")
        if choice == "B"
        else _cells_html(resolution["cells"])
        if choice == "edited" and resolution.get("cells")
        else None
    )
    return node.model_copy(
        update={"content": content or node.content, "metadata": {**node.metadata, "table_choice": choice}}
    )


JUNKABLE_OBJECTS = (NodeType.FIGURE, NodeType.PHOTO, NodeType.TABLE)


def _without(nodes: list[ProcessedNode], anchor: dict[str, Any]) -> list[ProcessedNode]:
    page, box = anchor.get("page"), _box(anchor.get("bbox"))
    if page is None:
        return nodes

    def junked(node: ProcessedNode) -> bool:
        if node.page_no != page or (node.page_end or page) != page:
            return False
        return box is None or (node.node_type in JUNKABLE_OBJECTS and _inside(node, box))

    gone = {n.ref for n in nodes if junked(n)}
    while children := {n.ref for n in nodes if n.parent_ref in gone and n.ref not in gone}:
        gone |= children
    return [n for n in nodes if n.ref not in gone]


def _with_source(fields: DocumentFields, flag: ReviewFlag) -> DocumentFields:
    evidence = flag.evidence or {}
    field = FIELD_BY_SUBJECT.get(subject_key(evidence.get("subject")))
    side = evidence.get("a" if flag.resolution.get("choice") == "A" else "b") or {}
    return fields.model_copy(update={field: side["value"]}) if field and side.get("value") else fields


def apply_decisions(processed: ProcessedDocument, flags: list[ReviewFlag]) -> ProcessedDocument:
    """The route's document as people and rules decided it (``flags``: ``decided_flags``)."""
    nodes, fields = list(processed.nodes), processed.document
    # a correction names its paragraph by the hash of the text as read: found before any decision edits it
    paragraphs = {block_key(n.content): i for i, n in enumerate(nodes) if n.source == NodeSource.VLM}
    for flag in sorted(flags, key=lambda f: f.resolved_at or datetime.min.replace(tzinfo=UTC)):
        resolution = flag.resolution
        i = paragraphs.get(resolution.get("block_key", ""))
        if (
            resolution["action"] not in ("set_cell", "set_text")
            or i is None
            or not _at(nodes[i], flag.anchor or {})
        ):
            continue
        edited = (
            set_cell(
                nodes[i].content,
                resolution["table"],
                resolution["row"],
                resolution["col"],
                resolution["old"],
                resolution["value"],
            )
            if resolution["action"] == "set_cell"
            else set_text(nodes[i].content, resolution["old"], resolution["text"])
        )
        if edited is not None:
            nodes[i] = nodes[i].model_copy(update={"content": edited})
    for flag in flags:
        resolution, anchor = flag.resolution, flag.anchor or {}
        action = resolution["action"]
        if action == "set_value":
            nodes = [_with_value(n, anchor, resolution) for n in nodes]
        elif action == "choose_table":
            nodes = [_with_table(n, flag) for n in nodes]
        elif action == "mark_junk":
            nodes = _without(nodes, anchor)
        elif action == "choose_source":
            fields = _with_source(fields, flag)
    refs = {n.ref for n in nodes}
    return processed.model_copy(
        update={
            "nodes": nodes,
            "mentions": [m for m in processed.mentions if m.node_ref in refs],
            "document": fields,
        }
    )


def _human_numbers(plan: IndexPlan, flag: ReviewFlag) -> None:
    """The numbers extracted from a person's handwritten value are the person's (source human)."""
    resolution = flag.resolution
    new = None if resolution.get("illegible") else resolution.get("value")
    if not new:
        return
    refs = {n.ref for n in plan.nodes if _at(n, flag.anchor or {})}
    plan.facts = [
        replace(f, source=NumericFactSource.HUMAN, confidence=1.0)
        if f.node_ref in refs and f.value_raw == new
        else f
        for f in plan.facts
    ]


def overlay_plan(session: Session, doc_id: uuid.UUID, plan: IndexPlan) -> list[ReviewFlag]:
    """Apply the decisions that act on the extracted numbers; returns the decided flags. Every other
    decision was applied to the document before chunking (``apply_decisions``)."""
    flags = decided_flags(session, doc_id)
    for flag in flags:
        action = flag.resolution["action"]
        if action == "set_fact_unit":
            _set_fact_unit(plan, flag, flag.resolution.get("unit"))
        elif action == "set_value":
            _human_numbers(plan, flag)
    return flags


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
