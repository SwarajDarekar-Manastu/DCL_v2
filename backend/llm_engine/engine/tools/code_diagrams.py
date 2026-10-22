"""T4 `inspect_code_and_diagrams` (file 07 §4): code symbols and P&ID traversal.

Code (Route B nodes): exact symbol lookup by `metadata.qualname` (or the bare name), the module header, and
the call graph one level each way from `metadata.calls[]`; `code_semantic` is T1 restricted to code nodes.

Diagrams (Route E): the diagram document's `documents.catalog` holds the graph
`{nodes: [{id, tag, label, type}], edges: [{source, target, label, medium, directed}], groups: [...]}`;
traversal runs here in Python (six diagrams, a few hundred cells): neighbors, upstream and downstream BFS,
and the shortest path between two tags, returned linearized (`Tank → F-101 → SV-1 → INJ-14`) with the
diagram's anchor and render asset.
"""

import uuid
from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from backend.indexing.anchors import NodeView, make_anchor
from backend.llm_engine.engine.tools import Source, ToolResult, page_label, provenance_of

NAME = "inspect_code_and_diagrams"
DESCRIPTION = (
    "Look up code symbols (exact name, callers and callees, semantic search in code) or traverse a P&ID / "
    "diagram (neighbors, upstream, downstream, path between two tags)."
)


class CodeDiagramArgs(BaseModel):
    mode: Literal["symbol_lookup", "code_semantic", "callers_callees", "diagram_path", "diagram_neighbors"]
    symbol: str | None = Field(default=None, description="qualified or bare symbol name")
    query: str | None = None
    diagram_doc_id: uuid.UUID | None = None
    diagram_title: str | None = None
    from_tag: str | None = None
    to_tag: str | None = None
    direction: Literal["upstream", "downstream", "both"] = "both"


# ---------------------------------------------------------------- diagrams (pure)


class Graph:
    def __init__(self, catalog: dict[str, Any]):
        self.nodes = {str(n["id"]): n for n in catalog.get("nodes", [])}
        self.by_tag = {}
        for node_id, node in self.nodes.items():
            for key in (node.get("tag"), node.get("label"), node_id):
                if key:
                    self.by_tag.setdefault(str(key).strip().upper(), node_id)
        self.out: dict[str, list[tuple[str, dict]]] = {n: [] for n in self.nodes}
        self.into: dict[str, list[tuple[str, dict]]] = {n: [] for n in self.nodes}
        for edge in catalog.get("edges", []):
            source, target = str(edge["source"]), str(edge["target"])
            if source not in self.nodes or target not in self.nodes:
                continue
            self.out[source].append((target, edge))
            self.into[target].append((source, edge))
            if edge.get("directed") is False:
                self.out[target].append((source, edge))
                self.into[source].append((target, edge))

    def find(self, tag: str) -> str | None:
        return self.by_tag.get(tag.strip().upper())

    def name(self, node_id: str) -> str:
        node = self.nodes[node_id]
        return str(node.get("tag") or node.get("label") or node_id)

    def reach(self, start: str, direction: str) -> list[list[str]]:
        """Simple paths away from `start` (BFS order) up to the leaves; `upstream` walks edges backwards."""
        adjacency = self.into if direction == "upstream" else self.out
        paths, queue = [], deque([[start]])
        while queue:
            path = queue.popleft()
            nexts = [n for n, _ in adjacency[path[-1]] if n not in path]
            if not nexts and len(path) > 1:
                paths.append(path)
            queue.extend(path + [n] for n in nexts)
        return paths

    def shortest_path(self, start: str, goal: str) -> list[str] | None:
        queue, seen = deque([[start]]), {start}
        while queue:
            path = queue.popleft()
            if path[-1] == goal:
                return path
            for nxt, _ in self.out[path[-1]] + self.into[path[-1]]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(path + [nxt])
        return None

    def neighbors(self, node_id: str) -> dict[str, list[str]]:
        describe = lambda pairs: [  # noqa: E731
            self.name(n) + (f" [{e.get('medium')}]" if e.get("medium") else "") for n, e in pairs
        ]
        return {"upstream": describe(self.into[node_id]), "downstream": describe(self.out[node_id])}


def linear(graph: Graph, path: list[str]) -> str:
    return " → ".join(graph.name(n) for n in path)


def traverse(catalog: dict[str, Any], args: CodeDiagramArgs) -> tuple[dict, str, list[str]]:
    graph = Graph(catalog)
    warnings: list[str] = []
    start = graph.find(args.from_tag or "")
    if start is None:
        return {}, f"Tag {args.from_tag!r} is not in this diagram.", [f"unknown tag {args.from_tag}"]
    if args.mode == "diagram_neighbors":
        near = graph.neighbors(start)
        display = (
            f"{graph.name(start)}: upstream {', '.join(near['upstream']) or 'none'}; "
            f"downstream {', '.join(near['downstream']) or 'none'}"
        )
        return {"tag": graph.name(start), **near}, display, warnings
    if args.to_tag:
        goal = graph.find(args.to_tag)
        if goal is None:
            return {}, f"Tag {args.to_tag!r} is not in this diagram.", [f"unknown tag {args.to_tag}"]
        path = graph.shortest_path(start, goal)
        if path is None:
            return {"path": None}, f"No connection between {args.from_tag} and {args.to_tag}.", warnings
        return {"path": [graph.name(n) for n in path]}, f"Path: {linear(graph, path)}", warnings
    directions = ["upstream", "downstream"] if args.direction == "both" else [args.direction]
    result, lines = {}, []
    for direction in directions:
        paths = graph.reach(start, direction)
        if direction == "upstream":
            paths = [list(reversed(p)) for p in paths]
        result[direction] = [[graph.name(n) for n in p] for p in paths]
        lines += [f"{direction.capitalize()}: {linear(graph, p)}" for p in paths] or [
            f"{direction.capitalize()}: none"
        ]
    return result, "\n".join(lines), warnings


# ---------------------------------------------------------------- code (database)

CODE_COLUMNS = (
    "n.node_id, n.doc_id, n.node_type, n.ordinal, n.content, n.content_sha256, n.breadcrumb, n.page_no, "
    "n.page_end, n.line_start, n.line_end, n.t_start_ms, n.t_end_ms, n.sheet_name, n.cell_range, n.bbox, "
    "n.metadata, "
    "n.source_origin, n.doc_kind, d.title"
)
VISIBLE = "n.doc_status IN ('ACTIVE', 'ACTIVE_WITH_SOFT_FLAGS')"


def _symbol_rows(session: Session, names: list[str]) -> list[Any]:
    statement = text(
        f"SELECT {CODE_COLUMNS} FROM document_nodes n JOIN documents d ON d.doc_id = n.doc_id "  # noqa: S608
        f"WHERE n.node_type = 'code_symbol' AND {VISIBLE} AND "
        "(n.metadata->>'qualname' = ANY(:names) OR n.metadata->>'symbol' = ANY(:names)) ORDER BY n.ordinal"
    )
    return list(session.execute(statement, {"names": names}))


def _module_header(session: Session, doc_id: uuid.UUID) -> Any | None:
    statement = text(
        f"SELECT {CODE_COLUMNS} FROM document_nodes n JOIN documents d ON d.doc_id = n.doc_id "  # noqa: S608
        "WHERE n.doc_id = :doc_id AND n.node_type = 'module_header' LIMIT 1"
    ).bindparams(bindparam("doc_id", type_=UUID(as_uuid=True)))
    return session.execute(statement, {"doc_id": doc_id}).first()


def _callers(session: Session, names: list[str]) -> list[Any]:
    statement = text(
        f"SELECT {CODE_COLUMNS} FROM document_nodes n JOIN documents d ON d.doc_id = n.doc_id "  # noqa: S608
        f"WHERE n.node_type = 'code_symbol' AND {VISIBLE} AND "
        "EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(n.metadata->'calls', '[]'::jsonb)) c "
        "WHERE c = ANY(:names))"
    )
    return list(session.execute(statement, {"names": names}))


def _code_source(row) -> Source:
    view = NodeView.from_row(row)
    lines = f"L{row.line_start}–{row.line_end}" if row.line_start else None
    return Source(
        doc_id=row.doc_id,
        anchor=make_anchor(row.doc_id, view).serialize(),
        title=row.title,
        label=page_label(row.title, None, lines),
        provenance=provenance_of(row.source_origin, row.doc_kind),
    )


def code_lookup(session: Session, args: CodeDiagramArgs) -> ToolResult:
    name = (args.symbol or "").strip()
    names = [name, name.split(".")[-1]] if name else []
    rows = _symbol_rows(session, names)
    if not rows:
        return ToolResult(
            tool=NAME,
            result=[],
            display=f"No code symbol named {name!r} was found.",
            warnings=[f"symbol {name!r} not found"],
        )
    lines, sources, result = [], [], []
    for row in rows[:5]:
        meta = row.metadata or {}
        qualname = meta.get("qualname") or meta.get("symbol")
        header = _module_header(session, row.doc_id)
        entry = {
            "qualname": qualname,
            "code": row.content,
            "calls": meta.get("calls", []),
            "lines": [row.line_start, row.line_end],
            "module_header": header.content if header else None,
        }
        if args.mode == "callers_callees":
            entry["callers"] = [
                (r.metadata or {}).get("qualname") for r in _callers(session, [qualname, name])
            ]
        result.append(entry)
        sources.append(_code_source(row))
        lines.append(f"{qualname} ({row.title}, lines {row.line_start}–{row.line_end})")
        if entry.get("callers") is not None:
            lines.append(
                f"  callers: {', '.join(c for c in entry['callers'] if c) or 'none'}; "
                f"calls: {', '.join(entry['calls']) or 'none'}"
            )
        lines.append(row.content)
    return ToolResult(tool=NAME, result=result, provenance=sources, display="\n".join(lines))


def _diagram(session: Session, args: CodeDiagramArgs) -> Any | None:
    if args.diagram_doc_id:
        where, params = "doc_id = :doc_id", {"doc_id": args.diagram_doc_id}
    else:
        where, params = (
            "title ILIKE :title AND catalog IS NOT NULL",
            {"title": f"%{args.diagram_title or ''}%"},
        )
    statement = text(
        f"SELECT doc_id, title, catalog, source_origin, doc_kind FROM documents WHERE {where} "  # noqa: S608
        "AND status IN ('ACTIVE', 'ACTIVE_WITH_SOFT_FLAGS') ORDER BY updated_at DESC LIMIT 1"
    )
    if args.diagram_doc_id:
        statement = statement.bindparams(bindparam("doc_id", type_=UUID(as_uuid=True)))
    return session.execute(statement, params).first()


def inspect_code_and_diagrams(session: Session, args: CodeDiagramArgs, search=None) -> ToolResult:
    if args.mode in ("symbol_lookup", "callers_callees"):
        return code_lookup(session, args)
    if args.mode == "code_semantic":
        if search is None:
            return ToolResult(
                tool=NAME, result=None, display="Code search is unavailable.", warnings=["no search"]
            )
        return search(args.query or args.symbol or "", node_types=["code_symbol", "module_header"])
    diagram = _diagram(session, args)
    if diagram is None or not diagram.catalog:
        return ToolResult(
            tool=NAME,
            result=None,
            display="No diagram found for the request.",
            warnings=["diagram not found"],
        )
    result, display, warnings = traverse(diagram.catalog, args)
    source = Source(
        doc_id=diagram.doc_id,
        anchor="page:1:",
        title=diagram.title,
        label=page_label(diagram.title, 1),
        provenance=provenance_of(diagram.source_origin, diagram.doc_kind),
    )
    return ToolResult(
        tool=NAME,
        result=result,
        provenance=[source],
        warnings=warnings,
        display=f"{diagram.title}: {display}",
    )
