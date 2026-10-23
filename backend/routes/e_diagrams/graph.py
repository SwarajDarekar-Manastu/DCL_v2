"""The diagram graph every Route E parser fills, and the text nodes made from it (file 03 §9 E.1 steps 4–5).

``Graph`` = pages, components (vertices), connections (edges), groups (containers, Visio groups, layers) and
free text (notes). It is stored as ``documents.catalog`` and ``graph.json``. Text for retrieval:
- one ``diagram_summary`` node per page: the page's components, its connections as ``A → B`` lines, groups and
  notes (``Thruster Config Rev C: Tank → Filter F-101 → SV-1 → Injector …``);
- one ``diagram_component`` node per labeled component with its neighbourhood (``SV-1 (solenoid valve):
  inlet from F-101, outlet to INJ-14; electrical from PSU-2``), so a question about one tag retrieves a
  focused chunk.

Tags (``PT-101``, ``SV-1``, ``T7``) and ranges in labels (``PT-101 (0–250 bar)``) become mentions. A graph
whose edges are mostly unlabeled (> 30 %) or whose components are mostly unconnected (> 20 %) is indexed but
marked incomplete with ``CONFLICT`` SOFT (file 06 §4).
"""

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.dispatcher.contract import (
    ConflictEvidence,
    ConflictSide,
    Flag,
    FlagAnchor,
    Mention,
    ProcessedNode,
)
from backend.postgres.enums import FlagSeverity, FlagType, MentionSource, NodeSource, NodeType

TAG = re.compile(r"\b(?:[A-Z]{1,5}-?\d{1,4}[A-Z]?|[A-Z]{1,3}-[A-Z]{1,3}-?\d{1,4})\b")
RANGE = re.compile(
    r"[-+]?\d+(?:[.,]\d+)?\s*(?:[–-]|to)\s*[-+]?\d+(?:[.,]\d+)?\s*(?:bar[ga]?|psi[ga]?|k?Pa|MPa|°C|K|V|A|mA|W|N|g/s|kg/s|mm|m|%)"
)
QUANTITY = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?\s*(?:mm|cm|m|bar[ga]?|psi[ga]?|°C|K|W|V|A|N|g/s|kg/s|%)(?!\w)"
)
UNLABELED_EDGES_MAX = 0.30
ORPHANS_MAX = 0.20
MAX_SUMMARY_EDGES = 80
SEPARATOR = " › "


class DiagramError(ValueError):
    """The file is not a readable diagram (invalid XML, broken package): PARSE_FAILURE HARD."""


@dataclass
class Page:
    number: int
    name: str


@dataclass
class Component:
    id: str
    label: str
    kind: str
    page: int
    group: str | None = None
    line: int | None = None
    box: tuple[float, float, float, float] | None = None  # x, y, width, height in the page's units
    style: str = ""


@dataclass
class Connection:
    id: str
    source: str | None
    target: str | None
    page: int
    label: str = ""
    directed: bool = True
    medium: str | None = None
    line: int | None = None
    style: str = ""
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class Group:
    id: str
    label: str
    page: int
    members: list[str] = field(default_factory=list)
    line: int | None = None


@dataclass
class Note:
    text: str
    page: int
    line: int | None = None
    box: tuple[float, float, float, float] | None = None
    id: str | None = None  # a draw.io text cell an edge may end on


@dataclass
class Graph:
    kind: str  # drawio, visio, svg, dxf
    pages: list[Page] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    edge_semantics: bool = True  # False for SVG/DXF: no connections are expected

    def catalog(self) -> dict[str, Any]:
        """JSON-shaped (tuples become lists), so the staged payload round-trips unchanged."""
        import json

        return json.loads(json.dumps(self._catalog(), ensure_ascii=False))

    def _catalog(self) -> dict[str, Any]:
        def clean(item) -> dict:
            return {k: v for k, v in asdict(item).items() if v not in (None, "", [], {})}

        return {
            "diagram_format": self.kind,
            "pages": [clean(p) for p in self.pages],
            "nodes": [clean(c) for c in self.components],
            "edges": [clean(e) for e in self.connections],
            "groups": [clean(g) for g in self.groups],
            "notes": [clean(n) for n in self.notes],
            **({"extra": self.extra} if self.extra else {}),
        }


def strip_html(value: str) -> str:
    import html

    text = re.sub(r"<br\s*/?>|</div>|</p>|</li>", " ", value, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def tags_of(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in TAG.finditer(text)))


def _name(component: Component | Group | None, fallback: str) -> str:
    if component is None:
        return fallback
    if component.label:
        return component.label
    kind = getattr(component, "kind", "group")
    return f"unlabeled {kind}"


def _medium(connection: Connection) -> str:
    return f" [{connection.medium}]" if connection.medium else ""


def graph_flags(graph: Graph) -> list[Flag]:
    if not graph.edge_semantics:
        return []
    flags = []
    edges = [e for e in graph.connections if e.source or e.target]
    unlabeled = [e for e in edges if not e.label]
    connected = {e.source for e in edges} | {e.target for e in edges}
    components = [c for c in graph.components if c.kind != "text"]
    orphans = [c for c in components if c.id not in connected]
    checks = [
        ("unlabeled edges", len(unlabeled), len(edges), UNLABELED_EDGES_MAX),
        ("orphan components", len(orphans), len(components), ORPHANS_MAX),
    ]
    for subject, count, total, limit in checks:
        if total and count / total > limit:
            flags.append(
                Flag(
                    flag_type=FlagType.CONFLICT,
                    severity=FlagSeverity.SOFT,
                    anchor=FlagAnchor(content_sha256=hashlib.sha256(f"graph|{subject}".encode()).hexdigest()),
                    evidence=ConflictEvidence(
                        subject=f"diagram graph incomplete: {subject}",
                        relation="check_failed",
                        a=ConflictSide(
                            label=subject, value=f"{count} of {total}", provenance="parsed diagram"
                        ),
                        b=ConflictSide(
                            label="limit", value=f"at most {limit:.0%}", provenance="file 06 §4 (Route E)"
                        ),
                    ),
                )
            )
    return flags


def graph_nodes(graph: Graph, title: str, language: str = "en") -> tuple[list[ProcessedNode], list[Mention]]:
    """Summary node per page and one node per labeled component, with tag and range mentions."""
    by_id: dict[str, Component | Group] = {c.id: c for c in graph.components}
    by_id.update({g.id: g for g in graph.groups})
    notes_by_id = {n.id: n for n in graph.notes if n.id}
    groups = {g.id: g for g in graph.groups}
    incoming: dict[str, list[Connection]] = defaultdict(list)
    outgoing: dict[str, list[Connection]] = defaultdict(list)
    for edge in graph.connections:
        if edge.source:
            outgoing[edge.source].append(edge)
        if edge.target:
            incoming[edge.target].append(edge)
    nodes: list[ProcessedNode] = []
    mentions: list[Mention] = []

    def add(ref, node_type, content, page, crumb, metadata, line=None, tag_text=""):
        nodes.append(
            ProcessedNode(
                ref=ref,
                node_type=node_type,
                level=crumb.count(SEPARATOR) + 1,
                ordinal=len(nodes),
                breadcrumb=crumb,
                language=language,
                content=content,
                page_no=page,
                line_start=line,
                source=NodeSource.STRUCTURED,
                metadata=metadata,
            )
        )
        for tag in tags_of(content if node_type == NodeType.DIAGRAM_COMPONENT else tag_text):
            mentions.append(Mention(node_ref=ref, kind="tag", surface=tag, source=MentionSource.REGEX))
        for match in RANGE.finditer(content):
            mentions.append(
                Mention(node_ref=ref, kind="quantity", surface=match.group(0), source=MentionSource.REGEX)
            )

    for page in graph.pages:
        crumb = SEPARATOR.join([title, page.name]) if len(graph.pages) > 1 else title
        components = [c for c in graph.components if c.page == page.number]
        all_edges = [e for e in graph.connections if e.page == page.number]
        edges = [e for e in all_edges if e.source or e.target]
        free_lines = len(all_edges) - len(edges)
        groups_here = [g for g in graph.groups if g.page == page.number]
        notes = [n for n in graph.notes if n.page == page.number]
        lines = [f"{title} — {page.name}" if len(graph.pages) > 1 else title]
        labeled = [c for c in components if c.label]
        if labeled:
            kinds = Counter(c.kind for c in components)
            lines.append(
                "Components: "
                + "; ".join(
                    f"{c.label} ({c.kind})" if c.kind not in ("shape", "text label") else c.label
                    for c in labeled
                )
            )
            unlabeled = len(components) - len(labeled)
            if unlabeled:
                common = ", ".join(f"{k} ×{n}" for k, n in kinds.most_common(5))
                lines.append(f"Unlabeled shapes: {unlabeled} ({common})")
        if notes:
            lines.append("Notes: " + " | ".join(n.text for n in notes))

        def end(node_id: str | None) -> str | None:
            item = by_id.get(node_id) if node_id else None
            if item is not None and item.label:
                return item.label
            note = notes_by_id.get(node_id) if node_id else None
            return note.text if note is not None else None

        listed = 0
        anonymous = 0
        for edge in edges:
            a, b = end(edge.source), end(edge.target)
            if a is None and b is None and not edge.label:
                anonymous += 1
                continue
            if listed < MAX_SUMMARY_EDGES:
                arrow = "→" if edge.directed else "—"
                label = f" ({edge.label})" if edge.label else ""
                lines.append(
                    f"{a or _name(by_id.get(edge.source), '(free end)')} {arrow} "
                    f"{b or _name(by_id.get(edge.target), '(free end)')}{label}{_medium(edge)}"
                )
            listed += 1
        if listed > MAX_SUMMARY_EDGES:
            lines.append(f"… {listed - MAX_SUMMARY_EDGES} more connections")
        if anonymous:
            lines.append(f"Connections between unlabeled shapes: {anonymous}")
        if free_lines:
            lines.append(f"Free lines (dimension or leader lines, not connected): {free_lines}")
        for group in groups_here:
            members = [_name(by_id.get(m), m) for m in group.members if m in by_id and by_id[m].label]
            if members:
                lines.append(f"Group {group.label or group.id}: {', '.join(members)}")
        line_numbers = [c.line for c in components if c.line] + [e.line for e in edges if e.line]
        add(
            f"page{page.number}",
            NodeType.DIAGRAM_SUMMARY,
            "\n".join(lines),
            page.number,
            crumb,
            {
                "page_name": page.name,
                "components": len(components),
                "connections": len(edges),
                "free_lines": free_lines,
                "unlabeled_connections": sum(1 for e in edges if not e.label),
            },
            min(line_numbers) if line_numbers else None,
            " ".join(n.text for n in notes),
        )
        for component in labeled:
            if len(component.label) < 3 and not (incoming.get(component.id) or outgoing.get(component.id)):
                continue  # grid letters, sheet numbers: in the summary only
            parts = [
                f"{component.label} ({component.kind})"
                if component.kind not in ("shape",)
                else component.label
            ]
            relations = []
            for edge in incoming.get(component.id, []):
                other = _name(by_id.get(edge.source), "?")
                word = "from" if edge.directed else "connected to"
                relations.append(f"{word} {other}{_label(edge)}{_medium(edge)}")
            for edge in outgoing.get(component.id, []):
                other = _name(by_id.get(edge.target), "?")
                word = "to" if edge.directed else "connected to"
                relations.append(f"{word} {other}{_label(edge)}{_medium(edge)}")
            if relations:
                parts.append(": " + "; ".join(relations))
            group = groups.get(component.group) if component.group else None
            if group is not None and group.label:
                parts.append(f". Part of {group.label}")
            add(
                f"c{page.number}:{component.id}",
                NodeType.DIAGRAM_COMPONENT,
                "".join(parts),
                page.number,
                SEPARATOR.join([crumb, component.label[:80]]),
                {"component_id": component.id, "kind": component.kind, "tags": tags_of(component.label)},
                component.line,
            )
    return nodes, mentions


def _label(edge: Connection) -> str:
    return f" ({edge.label})" if edge.label else ""


def duplicate_tags(graph: Graph) -> dict[str, list[str]]:
    seen: dict[tuple[int, str], int] = Counter()
    for component in graph.components:
        for tag in tags_of(component.label):
            seen[(component.page, tag)] += 1
    out: dict[str, list[str]] = defaultdict(list)
    for (page, tag), count in seen.items():
        if count > 1:
            out[str(page)].append(tag)
    return dict(out)
