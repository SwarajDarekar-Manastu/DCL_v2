"""U1 `get_document` (file 07 §4): a document's parents in reading order — the whole report, a page range or
one section — within a character budget; a longer document is read progressively (`next_ordinal` continues
where this call stopped).

What exists, halted files with their review cases and which file a question means are the catalog step's
(`engine/catalog.py`, run before the analysis); it replaced the U2 `catalog_lookup` tool (user 2026-10-26).
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Session
from sqlalchemy.types import Text

from backend.indexing.anchors import NodeView, make_anchor
from backend.llm_engine.engine.tools import Source, ToolResult, page_label, provenance_of

GET_NAME = "get_document"
GET_DESCRIPTION = (
    "Read one document in order (all, a page range, or a section), for summaries and full reads."
)
BUDGET_CHARS = 40_000
VISIBLE = ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS")


class GetDocumentArgs(BaseModel):
    doc_id: uuid.UUID | None = None
    title: str | None = Field(default=None, description="exact or partial title when the id is unknown")
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, description="text of the section heading, e.g. '3.2 Chamber'")
    start_ordinal: int = Field(default=0, ge=0, description="continue a progressive read")


NODE_COLUMNS = (
    "n.node_id, n.doc_id, n.node_type, n.ordinal, n.content, n.content_sha256, n.breadcrumb, n.page_no, "
    "n.page_end, n.line_start, n.line_end, n.t_start_ms, n.t_end_ms, n.sheet_name, n.cell_range, n.bbox, "
    "n.needs_review, "
    "n.language"
)


def _find_document(session: Session, args: GetDocumentArgs):
    if args.doc_id:
        statement = text("SELECT * FROM documents WHERE doc_id = :id").bindparams(
            bindparam("id", type_=UUID(as_uuid=True))
        )
        return session.execute(statement, {"id": args.doc_id}).mappings().first()
    statement = text(
        "SELECT * FROM documents WHERE title ILIKE :pattern AND status = ANY(:visible) "
        "ORDER BY (lower(title) = lower(:exact)) DESC, doc_date DESC NULLS LAST LIMIT 1"
    ).bindparams(bindparam("visible", type_=ARRAY(Text)))
    title = args.title or ""
    return (
        session.execute(statement, {"pattern": f"%{title}%", "exact": title, "visible": list(VISIBLE)})
        .mappings()
        .first()
    )


def get_document(session: Session, args: GetDocumentArgs) -> ToolResult:
    doc = _find_document(session, args)
    if doc is None:
        return ToolResult(
            tool=GET_NAME,
            result=None,
            warnings=["document not found"],
            display=f"No document matches {args.title or args.doc_id}.",
        )
    clauses = [
        "n.doc_id = :doc_id",
        "n.ordinal >= :start",
        "(n.node_type = 'parent' OR "
        "(n.parent_node_id IS NULL AND n.node_type NOT IN ('child', 'question_proxy')))",
    ]
    params = {"doc_id": doc["doc_id"], "start": args.start_ordinal}
    if args.page_from:
        clauses.append("coalesce(n.page_end, n.page_no) >= :page_from")
        params["page_from"] = args.page_from
    if args.page_to:
        clauses.append("n.page_no <= :page_to")
        params["page_to"] = args.page_to
    if args.section:
        clauses.append("n.breadcrumb ILIKE :section")
        params["section"] = f"%{args.section}%"
    statement = text(
        f"SELECT {NODE_COLUMNS} FROM document_nodes n WHERE {' AND '.join(clauses)} ORDER BY n.ordinal"  # noqa: S608
    ).bindparams(bindparam("doc_id", type_=UUID(as_uuid=True)))
    rows = list(session.execute(statement, params))
    used, blocks, sources, last = 0, [], [], None
    for row in rows:
        if used and used + len(row.content) > BUDGET_CHARS:
            break
        used += len(row.content)
        last = row.ordinal
        label = page_label(doc["title"], row.page_no)
        marker = " ⚠ unverified extraction" if row.needs_review else ""
        blocks.append(f"## {row.breadcrumb or doc['title']} ({label}){marker}\n{row.content}")
        sources.append(
            Source(
                doc_id=row.doc_id,
                anchor=make_anchor(row.doc_id, NodeView.from_row(row)).serialize()
                if (row.page_no or row.line_start or row.t_start_ms is not None or row.cell_range)
                else None,
                title=doc["title"],
                label=label,
                provenance=provenance_of(doc["source_origin"], doc["doc_kind"]),
                language=row.language,
                needs_review=row.needs_review,
            )
        )
    remaining = len(rows) - len(blocks)
    warnings = []
    if doc["status"] == "HALTED":
        warnings.append("the document is halted for review; its content is not in the active index")
    if doc["status"] == "SUPERSEDED":
        warnings.append("the document is superseded by a newer revision")
    result = {
        "doc_id": str(doc["doc_id"]),
        "title": doc["title"],
        "doc_kind": doc["doc_kind"],
        "parents_returned": len(blocks),
        "parents_remaining": remaining,
        "next_ordinal": (last + 1) if remaining and last is not None else None,
        "summary": (doc["enrichment"] or {}).get("doc_summary"),
    }
    header = f"# {doc['title']} ({doc['doc_kind']}, {provenance_of(doc['source_origin'], doc['doc_kind'])})"
    tail = (
        f"\n\n[{remaining} more section(s); continue with start_ordinal={result['next_ordinal']}]"
        if remaining
        else ""
    )
    return ToolResult(
        tool=GET_NAME,
        result=result,
        provenance=sources,
        warnings=warnings,
        display=header + "\n\n" + "\n\n".join(blocks) + tail,
    )
