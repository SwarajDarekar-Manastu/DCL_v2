"""Stable anchors (file 04 §4.4): how citations, flags, benchmark gold and deep links point at content.

Node ids change on every re-index, so durable records store an `Anchor` (S1's model in
backend/dispatcher/contract.py, serialized `<kind>:<value>:<content_sha256>`). This module computes the
content hash, builds anchors from index nodes, and resolves an anchor against a document's current nodes:

1. exact: a current node has the same normalized-content hash (the passage still exists, even if it moved);
2. page_fallback: no hash match, but nodes cover the anchor's page, line, time or cells (the passage was
   re-chunked, for example after a chunk-size change); the viewer opens the page without a highlight;
3. document_only: nothing covers the locator; the viewer opens the document.

`resolve_among` is the pure step; `resolve_anchor(session, anchor)` loads the candidate rows of
`document_nodes` (hash prefix match or locator cover, one query) and runs it.
"""

import hashlib
import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import Anchor, AnchorError, PageBox
from backend.postgres.models import DocumentNode

WHITESPACE = re.compile(r"\s+")
DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")


def normalize_content(text: str) -> str:
    """NFKC, unified dashes, case-folded, whitespace collapsed: survives re-OCR spacing and case noise."""
    text = unicodedata.normalize("NFKC", text).translate(DASHES).casefold()
    return WHITESPACE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    """`document_nodes.content_sha256`: SHA-256 hex of the normalized content."""
    return hashlib.sha256(normalize_content(text).encode("utf-8")).hexdigest()


class Locatable(Protocol):
    """What anchoring reads from a node: an IndexNode now, a document_nodes row later."""

    content_sha256: str
    breadcrumb: str
    page_no: int | None
    page_end: int | None
    line_start: int | None
    line_end: int | None
    t_start_ms: int | None
    t_end_ms: int | None
    sheet_name: str | None
    cell_range: str | None
    bboxes: list[PageBox]


def make_anchor(doc_id: uuid.UUID | str, node: Locatable) -> Anchor:
    """The anchor of a node; the locator is the first of page, line, time, cells that the node has."""
    locator: dict[str, Any]
    if node.page_no is not None:
        locator = {"page_no": node.page_no}
    elif node.line_start is not None:
        locator = {"line_start": node.line_start}
    elif node.t_start_ms is not None:
        locator = {"t_start_ms": node.t_start_ms}
    elif node.sheet_name and node.cell_range:
        locator = {"sheet_name": node.sheet_name, "cell_range": node.cell_range}
    else:
        raise AnchorError("node has no page, line, time or cell locator; the route must set one")
    return Anchor(
        doc_id=doc_id, content_sha256=node.content_sha256, breadcrumb=node.breadcrumb or None, **locator
    )


class ResolutionStatus(StrEnum):
    EXACT = "exact"
    PAGE_FALLBACK = "page_fallback"
    DOCUMENT_ONLY = "document_only"


@dataclass(frozen=True)
class AnchorResolution:
    """`matches` are the current nodes the anchor points at (exact) or that cover its locator (fallback).
    `boxes` are the cited passage's boxes, 0..1 top-left, only for an exact match."""

    status: ResolutionStatus
    anchor: Anchor
    page_no: int | None
    matches: list[Any] = field(default_factory=list)
    boxes: list[PageBox] = field(default_factory=list)


def _covers(node: Locatable, anchor: Anchor) -> bool:
    if anchor.page_no is not None:
        return node.page_no is not None and node.page_no <= anchor.page_no <= (node.page_end or node.page_no)
    if anchor.line_start is not None:
        return node.line_start is not None and node.line_start <= anchor.line_start <= (
            node.line_end or node.line_start
        )
    if anchor.t_start_ms is not None:
        return node.t_start_ms is not None and node.t_start_ms <= anchor.t_start_ms <= (
            node.t_end_ms if node.t_end_ms is not None else node.t_start_ms
        )
    return node.sheet_name == anchor.sheet_name and node.cell_range == anchor.cell_range


def _hash_matches(node: Locatable, anchor: Anchor) -> bool:
    return bool(anchor.content_sha256) and node.content_sha256.startswith(anchor.content_sha256)


def resolve_among(anchor: Anchor, nodes: Sequence[Locatable]) -> AnchorResolution:
    """Resolve an anchor against the current nodes of its document (exact → page fallback → document)."""
    exact = [n for n in nodes if _hash_matches(n, anchor)]
    if exact:
        on_locator = [n for n in exact if _covers(n, anchor)] or exact
        best = on_locator[0]
        boxes = [box for box in best.bboxes if anchor.page_no is None or box.page_no == anchor.page_no]
        page = anchor.page_no if anchor.page_no is not None and _covers(best, anchor) else best.page_no
        return AnchorResolution(ResolutionStatus.EXACT, anchor, page, on_locator, boxes or list(best.bboxes))
    covering = [n for n in nodes if _covers(n, anchor)]
    if covering:
        return AnchorResolution(ResolutionStatus.PAGE_FALLBACK, anchor, anchor.page_no, covering)
    return AnchorResolution(ResolutionStatus.DOCUMENT_ONLY, anchor, None)


@dataclass(frozen=True)
class NodeView:
    """A `document_nodes` row as `resolve_among` reads it; `node_id` is request-scoped, never stored."""

    node_id: uuid.UUID
    node_type: str
    ordinal: int
    content_sha256: str
    breadcrumb: str
    page_no: int | None
    page_end: int | None
    line_start: int | None
    line_end: int | None
    t_start_ms: int | None
    t_end_ms: int | None
    sheet_name: str | None
    cell_range: str | None
    bboxes: list[PageBox]

    @classmethod
    def from_row(cls, row: DocumentNode) -> "NodeView":
        return cls(
            node_id=row.node_id,
            node_type=row.node_type,
            ordinal=row.ordinal,
            content_sha256=row.content_sha256 or "",
            breadcrumb=row.breadcrumb or "",
            page_no=row.page_no,
            page_end=row.page_end,
            line_start=row.line_start,
            line_end=row.line_end,
            t_start_ms=row.t_start_ms,
            t_end_ms=row.t_end_ms,
            sheet_name=row.sheet_name,
            cell_range=row.cell_range,
            bboxes=[PageBox.model_validate(box) for box in row.bbox or []],
        )


def _locator_clause(anchor: Anchor):
    n = DocumentNode
    if anchor.page_no is not None:
        return and_(n.page_no <= anchor.page_no, func.coalesce(n.page_end, n.page_no) >= anchor.page_no)
    if anchor.line_start is not None:
        return and_(
            n.line_start <= anchor.line_start, func.coalesce(n.line_end, n.line_start) >= anchor.line_start
        )
    if anchor.t_start_ms is not None:
        return and_(
            n.t_start_ms <= anchor.t_start_ms, func.coalesce(n.t_end_ms, n.t_start_ms) >= anchor.t_start_ms
        )
    return and_(n.sheet_name == anchor.sheet_name, n.cell_range == anchor.cell_range)


def resolve_anchor(session: Session, anchor: Anchor) -> AnchorResolution:
    """Resolve a stored anchor against the document's current nodes (exact → page fallback → document).

    `matches` are `NodeView`s in reading order; the viewer uses `page_no` and `boxes`, the benchmark
    compares retrieved nodes against `matches`.
    """
    by_hash = (
        DocumentNode.content_sha256.startswith(anchor.content_sha256) if anchor.content_sha256 else false()
    )
    rows = session.scalars(
        select(DocumentNode)
        .where(DocumentNode.doc_id == anchor.doc_id, or_(by_hash, _locator_clause(anchor)))
        .order_by(DocumentNode.ordinal)
    ).all()
    return resolve_among(anchor, [NodeView.from_row(row) for row in rows])
