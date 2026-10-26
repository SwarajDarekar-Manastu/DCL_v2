"""Chunker (file 04 §4): route nodes → the retrievable nodes of `document_nodes`. Embed small, read big.

Input conventions (`ProcessedDocument.nodes`, S1's contract):
- Text is `parent` or `child` nodes. Consecutive text nodes (by ordinal) with the same breadcrumb and
  parent_ref form one section; a route may emit one node per section, per page fragment or per paragraph,
  and finer units give finer page anchors and boxes. A text node that a special node names as its parent_ref
  (a 10-minute transcript section above its windows) is kept whole as that parent.
- `table` nodes carry HTML; `table_row` nodes (FMEA, requirement and datasheet rows) name their table.
- Every other node type is one retrievable node as the route made it.

Output per section: parents split at heading boundaries, capped at 1,800 tokens (balanced split at
paragraph boundaries, each part keeping the heading, a tail under 300 tokens merged back); children of
250–400 tokens, sentence-aware, one sentence of overlap, a display equation glued to the sentence before it.
Tables up to 1,200 tokens stay whole, longer ones become row blocks with the header repeated; a block never
cuts a row or a rowspan group. `build_embed_texts` adds the English contextual header (§4.2) after
enrichment and caps every embed_text at 8,000 tokens.
"""

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.dispatcher.contract import DocumentFields, PageBox, ProcessedDocument, ProcessedNode
from backend.indexing.anchors import content_hash
from backend.indexing.identifiers import content_codes
from backend.indexing.tables import split_table, table_summary, table_to_text
from backend.llm_engine.local_models import MAX_EMBED_TEXT_TOKENS, format_document
from backend.postgres.enums import NodeSource, NodeType, SourceOrigin

TokenCounter = Callable[[list[str]], list[int]]
TEXT_TYPES = frozenset({NodeType.PARENT, NodeType.CHILD})
BREADCRUMB_SEPARATOR = " › "


@dataclass(frozen=True)
class ChunkingConfig:
    """Defaults of file 04 §4.1; `pipeline_config` `chunking.*` overrides them once it is readable."""

    parent_max_tokens: int = 1800
    parent_min_part_tokens: int = 300
    child_max_tokens: int = 400
    table_max_tokens: int = 1200
    header_max_tokens: int = 120
    embed_parents: bool = True


class IndexNode(BaseModel):
    """One future `document_nodes` row without ids or vectors; S1's commit assigns node ids from `ref`."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    parent_ref: str | None
    node_type: NodeType
    level: int
    ordinal: int
    breadcrumb: str
    language: str | None
    content: str
    content_codes: str
    content_sha256: str
    token_count: int
    page_no: int | None = None
    page_end: int | None = None
    bboxes: list[PageBox] = []
    line_start: int | None = None
    line_end: int | None = None
    t_start_ms: int | None = None
    t_end_ms: int | None = None
    sheet_name: str | None = None
    cell_range: str | None = None
    source: NodeSource
    confidence: float | None = None
    asset_ref: str | None = None
    metadata: dict[str, Any] = {}
    embed: bool
    embed_title: str | None = None
    embed_text: str | None = None
    embed_text_hash: str | None = None
    origin_refs: list[str] = []
    embedding: list[float] | None = Field(default=None, repr=False)
    image_embedding: list[float] | None = Field(default=None, repr=False)


# ---------------------------------------------------------------- text units


@dataclass
class Unit:
    """An unbreakable piece of text (a sentence, or an equation with its defining sentence)."""

    text: str
    tokens: int
    origin: ProcessedNode
    paragraph: int


ABBREVIATIONS = frozenset(
    "e.g i.e fig figs eq eqs no nr vs approx ref refs tab sec dr mr ms prof etc ca cf al z.b d.h bzw vgl abb "
    "rev max min resp incl st".split()
)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])|\n+")
DISPLAY_EQUATION = re.compile(r"(\$\$.*?\$\$)", re.DOTALL)
PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def split_sentences(text: str) -> list[str]:
    """Sentence-aware split for Latin and CJK text; keeps abbreviations, initials and decimals intact."""
    pieces: list[str] = []
    start = 0
    for match in SENTENCE_END.finditer(text):
        end = match.start()
        candidate = text[start:end].strip()
        following = text[match.end() : match.end() + 1]
        if "\n" not in match.group(0) and match.group(0) and _not_a_sentence_end(candidate, following):
            continue
        if candidate:
            pieces.append(candidate)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return pieces


def _not_a_sentence_end(candidate: str, following: str) -> bool:
    last_word = candidate.rsplit(maxsplit=1)[-1] if candidate else ""
    word = last_word.rstrip(".").lower().lstrip("([")
    if word in ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
        return True
    return bool(following) and following.islower()


def _sentence_units(text: str) -> list[str]:
    """Sentences, with each display equation glued to the sentence before it (file 03 §A1.5)."""
    units: list[str] = []
    for part in DISPLAY_EQUATION.split(text):
        if not part.strip():
            continue
        if part.startswith("$$") and units:
            units[-1] = f"{units[-1]} {part.strip()}"
        elif part.startswith("$$"):
            units.append(part.strip())
        else:
            units.extend(split_sentences(part))
    return units


def _count(count_tokens: TokenCounter, texts: list[str]) -> list[int]:
    return count_tokens(texts) if texts else []


def _split_long(unit: Unit, max_tokens: int, count_tokens: TokenCounter) -> list[Unit]:
    """A single sentence above the cap is cut at word boundaries (the only cut inside a sentence)."""
    if unit.tokens <= max_tokens:
        return [unit]
    words = unit.text.split()
    pieces = max(2, math.ceil(unit.tokens / max_tokens))
    size = max(1, math.ceil(len(words) / pieces))
    texts = [" ".join(words[i : i + size]) for i in range(0, len(words), size)]
    out: list[Unit] = []
    for text, tokens in zip(texts, _count(count_tokens, texts), strict=True):
        out.extend(_split_long(Unit(text, tokens, unit.origin, unit.paragraph), max_tokens, count_tokens))
    return out


def _pack(units: list[Unit], max_tokens: int, overlap: bool) -> list[list[Unit]]:
    """Balanced greedy packing: n groups of about (total + overlap) / n tokens each, never above max."""
    total = sum(u.tokens for u in units)
    overlap_tokens = total / len(units) if overlap and units else 0.0
    count = max(1, math.ceil(total / max_tokens))
    while (target := (total + (count - 1) * overlap_tokens) / count) > max_tokens:
        count += 1
    groups: list[list[Unit]] = []
    current: list[Unit] = []
    size = 0
    for unit in units:
        if current and (size + unit.tokens > max_tokens or size >= target):
            groups.append(current)
            carried = current[-1] if overlap and len(current) > 1 else None
            current, size = ([carried], carried.tokens) if carried else ([], 0)
            if current and size + unit.tokens > max_tokens:
                current, size = [], 0
        current.append(unit)
        size += unit.tokens
    if current:
        groups.append(current)
    return groups


def _join(units: list[Unit]) -> str:
    out = ""
    for i, unit in enumerate(units):
        if i:
            out += "\n\n" if unit.paragraph != units[i - 1].paragraph else " "
        out += unit.text
    return out


# ---------------------------------------------------------------- anchors of derived nodes


def _span(origins: list[ProcessedNode]) -> dict[str, Any]:
    pages = [p for o in origins for p in (o.page_no, o.page_end) if p is not None]
    lines = [p for o in origins for p in (o.line_start, o.line_end) if p is not None]
    times = [p for o in origins for p in (o.t_start_ms, o.t_end_ms) if p is not None]
    boxes: list[PageBox] = []
    for origin in origins:
        boxes.extend(box for box in origin.bboxes if box not in boxes)
    first = origins[0]
    return {
        "page_no": min(pages) if pages else None,
        "page_end": max(pages) if pages else None,
        "line_start": min(lines) if lines else None,
        "line_end": max(lines) if lines else None,
        "t_start_ms": min(times) if times else None,
        "t_end_ms": max(times) if times else None,
        "sheet_name": first.sheet_name,
        "cell_range": first.cell_range if len(origins) == 1 else None,
        "bboxes": boxes,
        "origin_refs": [o.ref for o in origins],
    }


def _unique_origins(units: list[Unit]) -> list[ProcessedNode]:
    seen: dict[str, ProcessedNode] = {}
    for unit in units:
        seen.setdefault(unit.origin.ref, unit.origin)
    return list(seen.values())


def _mean_confidence(origins: list[ProcessedNode]) -> float | None:
    values = [o.confidence for o in origins if o.confidence is not None]
    return min(values) if values else None


# ---------------------------------------------------------------- the chunker


def _node(
    ref: str,
    parent_ref: str | None,
    node_type: NodeType,
    content: str,
    origin: ProcessedNode,
    count: int,
    embed: bool,
    **fields: Any,
) -> IndexNode:
    base = {
        "level": origin.level,
        "breadcrumb": origin.breadcrumb,
        "language": origin.language,
        "source": origin.source,
        "confidence": origin.confidence,
        "asset_ref": None,
        "metadata": {},
    }
    base.update(fields)
    return IndexNode(
        ref=ref,
        parent_ref=parent_ref,
        node_type=node_type,
        ordinal=0,
        content=content,
        content_codes=content_codes(content),
        content_sha256=content_hash(content),
        token_count=count,
        embed=embed,
        **base,
    )


def _passthrough(origin: ProcessedNode, parent_ref: str | None, tokens: int, embed: bool) -> IndexNode:
    fields = _span([origin])
    fields.update(cell_range=origin.cell_range, asset_ref=origin.asset_ref, metadata=dict(origin.metadata))
    return _node(origin.ref, parent_ref, origin.node_type, origin.content, origin, tokens, embed, **fields)


def _sections(nodes: list[ProcessedNode], keep_whole: set[str]) -> list[list[ProcessedNode] | ProcessedNode]:
    """Document-order items: a list of text nodes forming one section, or a single node kept as is."""
    items: list[list[ProcessedNode] | ProcessedNode] = []
    for node in nodes:
        is_text = node.node_type in TEXT_TYPES and node.ref not in keep_whole
        if not is_text:
            items.append(node)
            continue
        if not node.content.strip():
            continue
        previous = items[-1] if items else None
        if (
            isinstance(previous, list)
            and previous[-1].breadcrumb == node.breadcrumb
            and previous[-1].parent_ref == node.parent_ref
        ):
            previous.append(node)
        else:
            items.append([node])
    return items


def _chunk_section(
    section: list[ProcessedNode], config: ChunkingConfig, count_tokens: TokenCounter
) -> list[IndexNode]:
    paragraphs = [
        (origin, p) for origin in section for p in PARAGRAPH_BREAK.split(origin.content) if p.strip()
    ]
    sentences: list[tuple[ProcessedNode, int, str]] = [
        (origin, i, s) for i, (origin, p) in enumerate(paragraphs) for s in _sentence_units(p)
    ]
    texts = [s for _, _, s in sentences]
    units = [
        Unit(text, tokens, origin, i)
        for (origin, i, text), tokens in zip(sentences, _count(count_tokens, texts), strict=True)
    ]
    units = [piece for u in units for piece in _split_long(u, config.child_max_tokens, count_tokens)]
    if not units:
        return []

    parts = _paragraph_parts(units, config)
    head = section[0]
    out: list[IndexNode] = []
    for k, part in enumerate(parts):
        parent_ref = f"{head.ref}#p{k}"
        parent_text = _join(part)
        origins = _unique_origins(part)
        out.append(
            _node(
                parent_ref,
                None,
                NodeType.PARENT,
                parent_text,
                head,
                sum(u.tokens for u in part),
                config.embed_parents,
                confidence=_mean_confidence(origins),
                metadata={"part": f"{k + 1}/{len(parts)}"} if len(parts) > 1 else {},
                **_span(origins),
            )
        )
        for j, child in enumerate(_pack(part, config.child_max_tokens, overlap=True)):
            child_origins = _unique_origins(child)
            out.append(
                _node(
                    f"{parent_ref}c{j}",
                    parent_ref,
                    NodeType.CHILD,
                    _join(child),
                    head,
                    sum(u.tokens for u in child),
                    True,
                    level=head.level + 1,
                    confidence=_mean_confidence(child_origins),
                    **_span(child_origins),
                )
            )
    return out


def _paragraph_parts(units: list[Unit], config: ChunkingConfig) -> list[list[Unit]]:
    """Parents: whole paragraphs packed to ≤ parent_max (a paragraph is split only if it alone is larger)."""
    total = sum(u.tokens for u in units)
    if total <= config.parent_max_tokens:
        return [units]
    by_paragraph: list[list[Unit]] = []
    for unit in units:
        if by_paragraph and by_paragraph[-1][0].paragraph == unit.paragraph:
            by_paragraph[-1].append(unit)
        else:
            by_paragraph.append([unit])
    blocks: list[Unit] = []
    pieces: list[list[Unit]] = []
    for paragraph in by_paragraph:
        size = sum(u.tokens for u in paragraph)
        groups = (
            [paragraph]
            if size <= config.parent_max_tokens
            else _pack(paragraph, config.parent_max_tokens, False)
        )
        for group in groups:
            pieces.append(group)
            blocks.append(Unit("", sum(u.tokens for u in group), group[0].origin, len(pieces) - 1))
    packed = _pack(blocks, config.parent_max_tokens, overlap=False)
    parts = [[u for block in group for u in pieces[block.paragraph]] for group in packed]
    if len(parts) > 1 and sum(u.tokens for u in parts[-1]) < config.parent_min_part_tokens:
        parts[-2].extend(parts.pop())
    return parts


def chunk_document(
    document: ProcessedDocument,
    config: ChunkingConfig | None = None,
    count_tokens: TokenCounter | None = None,
) -> list[IndexNode]:
    """All retrievable nodes of one document in reading order, ordinals assigned, embed_text not yet set."""
    if count_tokens is None:
        from backend.llm_engine.local_models import count_tokens
    config = config or ChunkingConfig()
    nodes = sorted(document.nodes, key=lambda n: n.ordinal)
    keep_whole = {n.parent_ref for n in nodes if n.parent_ref and n.node_type not in TEXT_TYPES}
    first_derived: dict[str, str] = {}
    out: list[IndexNode] = []
    for item in _sections(nodes, keep_whole):
        if isinstance(item, list):
            chunks = _chunk_section(item, config, count_tokens)
            if chunks:
                for origin in item:
                    first_derived[origin.ref] = chunks[0].ref
            out.extend(chunks)
        elif item.node_type is NodeType.TABLE:
            out.extend(_table_nodes(item, config, count_tokens, first_derived))
        else:
            tokens = _count(count_tokens, [item.content])[0]
            embed = config.embed_parents if item.node_type in TEXT_TYPES else True
            out.append(_passthrough(item, item.parent_ref, tokens, embed))
    for node in out:
        if node.parent_ref in first_derived:
            node.parent_ref = first_derived[node.parent_ref]
    _attach_to_sections(out)
    for node in out:
        if node.node_type is NodeType.TABLE and not node.metadata.get("summary"):
            node.metadata = {
                **node.metadata,
                "summary": table_summary(
                    node.content, node.metadata.get("caption"), node.metadata.get("part")
                ),
            }
    for ordinal, node in enumerate(out):
        node.ordinal = ordinal
    return out


SECTION_MEMBERS = frozenset({NodeType.TABLE, NodeType.FIGURE})


def _attach_to_sections(nodes: list[IndexNode]) -> None:
    """A table or figure the route left without a parent belongs to the section it sits in: the section part
    (parent) with its breadcrumb before it in reading order, else the first one after it. A section that holds
    only tables and figures ("8.2 Test 01") has no part, so the nearest enclosing section with text takes them
    ("8 Observations", else the document's top). The writer then gets the section's text with a table hit."""
    parts: dict[str, list[tuple[int, str]]] = {}
    for position, node in enumerate(nodes):
        if node.node_type is NodeType.PARENT:
            parts.setdefault(node.breadcrumb, []).append((position, node.ref))
    for position, node in enumerate(nodes):
        if node.node_type not in SECTION_MEMBERS or node.parent_ref is not None:
            continue
        crumbs = [c.strip() for c in node.breadcrumb.split(BREADCRUMB_SEPARATOR.strip())]
        for depth in range(len(crumbs), 0, -1):
            found = parts.get(BREADCRUMB_SEPARATOR.join(crumbs[:depth]))
            if found:
                before = [ref for at, ref in found if at < position]
                node.parent_ref = before[-1] if before else found[0][1]
                break


def _table_nodes(
    table: ProcessedNode, config: ChunkingConfig, count_tokens: TokenCounter, first_derived: dict[str, str]
) -> list[IndexNode]:
    blocks = split_table(table.content, config.table_max_tokens, count_tokens)
    if len(blocks) == 1:
        return [_passthrough(table, table.parent_ref, _count(count_tokens, [table.content])[0], True)]
    out = []
    for k, block in zip(range(len(blocks)), blocks, strict=True):
        fields = _span([table])
        metadata = {**table.metadata, "part": f"{k + 1}/{len(blocks)}"}
        fields.update(asset_ref=table.asset_ref, metadata=metadata)
        out.append(
            _node(
                f"{table.ref}#t{k}",
                table.parent_ref,
                NodeType.TABLE,
                block,
                table,
                _count(count_tokens, [block])[0],
                True,
                **fields,
            )
        )
    first_derived[table.ref] = out[0].ref
    return out


# ---------------------------------------------------------------- contextual header and embed_text


def _section_path(breadcrumb: str, title: str) -> str:
    parts = [p.strip() for p in breadcrumb.split(BREADCRUMB_SEPARATOR.strip()) if p.strip()]
    if parts and parts[0] == title.strip():
        parts = parts[1:]
    return BREADCRUMB_SEPARATOR.join(parts)


TYPE_WORDS = {NodeType.PARENT: "section", NodeType.CHILD: "text", NodeType.QUESTION_PROXY: "questions"}


def _clock(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def piece_type(node: "IndexNode") -> str:
    """What the piece is and where it sits: ``table · page 11``, ``video event · 00:14–00:19``."""
    words = TYPE_WORDS.get(node.node_type, str(node.node_type).replace("_", " "))
    if node.page_no is not None:
        pages = f"{node.page_no}–{node.page_end}" if node.page_end and node.page_end != node.page_no else ""
        where = f"pages {pages}" if pages else f"page {node.page_no}"
    elif node.node_type is NodeType.RUN_SUMMARY:  # stands for the whole recording: no position
        return words
    elif node.t_start_ms is not None:
        end = (
            f"–{_clock(node.t_end_ms)}"
            if node.t_end_ms is not None and node.t_end_ms > node.t_start_ms
            else ""
        )
        where = f"{_clock(node.t_start_ms)}{end}"
    elif node.line_start is not None:
        where = f"lines {node.line_start}–{node.line_end}" if node.line_end else f"line {node.line_start}"
    elif node.sheet_name and node.cell_range:
        where = f"{node.sheet_name}!{node.cell_range}"
    else:
        return words
    return f"{words} · {where}"


def test_line(document: DocumentFields) -> str | None:
    labels = [
        f"{word} {value}"
        for word, value in (
            ("plan", document.test_plan_id),
            ("run", document.test_run_id),
            ("hardware", document.hardware_item),
        )
        if value
    ]
    return "Test: " + " · ".join(labels) if labels else None


def contextual_header(
    document: DocumentFields,
    breadcrumb: str,
    entities: list[str],
    config: ChunkingConfig,
    count_tokens: TokenCounter,
    *,
    piece: str | None = None,
    about: str | None = None,
) -> str:
    """The English header of §4.2, at most `header_max_tokens`: what the file is (title, kind, origin, date),
    its test labels, what the piece is, where it sits, what the file is about, and the entities. Over the cap,
    the entities go first, then the About line, then the start of the path."""
    facts = [str(document.doc_kind)]
    if document.source_origin:
        facts.append("external" if document.source_origin == SourceOrigin.EXTERNAL_KEPT else "internal")
    if document.publisher and document.source_origin == SourceOrigin.EXTERNAL_KEPT:
        facts.append(document.publisher)
    if document.doc_date:
        facts.append(document.doc_date.isoformat())
    doc_line = f"Doc: {document.title} ({', '.join(facts)})"
    fixed = [line for line in (test_line(document), piece and f"Type: {piece}") if line]
    section = _section_path(breadcrumb, document.title)
    entities = list(entities)
    while True:
        lines = [doc_line, *fixed]
        if section:
            lines.append(f"Path: {section}")
        if about:
            lines.append(f"About: {about}")
        if entities:
            lines.append(f"Entities: {', '.join(entities)}")
        header = "\n".join(lines)
        if _count(count_tokens, [header])[0] <= config.header_max_tokens:
            return header
        if entities:
            entities.pop()
        elif about:
            about = None
        elif BREADCRUMB_SEPARATOR in section:
            section = section.split(BREADCRUMB_SEPARATOR, 1)[1]
        elif section:
            section = ""
        else:
            return fit_tokens("\n".join([doc_line, *fixed]), config.header_max_tokens, count_tokens)


def fit_tokens(text: str, budget: int, count_tokens: TokenCounter) -> str:
    """The longest word prefix of text within budget tokens (binary search over word count)."""
    if _count(count_tokens, [text])[0] <= budget:
        return text
    words = text.split(" ")
    low, high = 0, len(words)
    while low < high:
        mid = (low + high + 1) // 2
        if _count(count_tokens, [" ".join(words[:mid])])[0] <= budget:
            low = mid
        else:
            high = mid - 1
    return " ".join(words[:low])


def _embed_body(node: IndexNode, config: ChunkingConfig, count_tokens: TokenCounter) -> str:
    if node.node_type is NodeType.TABLE:
        summary = node.metadata.get("summary")
        rows = table_to_text(node.content) or node.content
        body = f"{summary}\n{rows}" if summary else rows
        return fit_tokens(body, config.table_max_tokens, count_tokens)
    return node.content


def build_embed_texts(
    nodes: list[IndexNode],
    document: DocumentFields,
    entities_by_ref: dict[str, list[str]] | None = None,
    config: ChunkingConfig | None = None,
    count_tokens: TokenCounter | None = None,
    about: str | None = None,
) -> list[IndexNode]:
    """Set embed_title, embed_text (header, '---', body; at most 8,000 tokens) and embed_text_hash.

    Only nodes with embed=True are touched.

    `entities_by_ref` holds the English canonical entity names per node ref (from enrichment, file 04 §3);
    a child without its own entry uses its parent's. The hash covers the exact model input, title included,
    so the commit can reuse a vector only when the embedding would be identical.
    """
    if count_tokens is None:
        from backend.llm_engine.local_models import count_tokens
    config = config or ChunkingConfig()
    entities_by_ref = entities_by_ref or {}
    for node in nodes:
        if not node.embed:
            continue
        entities = entities_by_ref.get(node.ref) or entities_by_ref.get(node.parent_ref or "", [])
        header = contextual_header(
            document, node.breadcrumb, entities, config, count_tokens, piece=piece_type(node), about=about
        )
        node.content_codes = content_codes(f"{header}\n{node.content}")
        section = _section_path(node.breadcrumb, document.title)
        node.embed_title = f"{document.title}{BREADCRUMB_SEPARATOR}{section}" if section else document.title
        head = f"{header}\n---\n"
        budget = MAX_EMBED_TEXT_TOKENS - _count(count_tokens, [head])[0]
        node.embed_text = head + fit_tokens(_embed_body(node, config, count_tokens), budget, count_tokens)
        model_input = format_document(node.embed_text, node.embed_title)
        node.embed_text_hash = hashlib.sha256(model_input.encode("utf-8")).hexdigest()
    return nodes
