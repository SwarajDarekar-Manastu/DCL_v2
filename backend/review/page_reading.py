"""The page check (review screen for a page read whole): the page reader's output as blocks the console draws.

The page reader writes Markdown with HTML tables, kept as ``pages/{n}.reading.json``
(routes/a1_office/handwriting.py ``reading_record``). The console never receives HTML from a model: a table
becomes a grid of plain-text cells, ``<br>`` a line break, every other tag is dropped, and crossed-out text
(``~~x~~``) is kept apart so it can be drawn struck through.

A block is one paragraph of the reading, the same split as the route's nodes (``vlm/p{page}/{i}``,
route.py), and its key is the hash of its source text: a correction made on it names that key, so it lands
on the same text on the next run, and on nothing once the reading has changed.
"""

import hashlib
import html
import re
from dataclasses import dataclass, field

STRUCK = re.compile(r"~~(.+?)~~")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
TABLE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
TAG = re.compile(r"<[^>]+>")


@dataclass
class Cell:
    text: str
    struck: list[str] = field(default_factory=list)
    span_of: tuple[int, int] | None = None  # a position a rowspan/colspan covers points at its origin cell


@dataclass
class Part:
    kind: str  # "heading", "text" or "table"
    text: str | None = None
    struck: list[str] = field(default_factory=list)
    rows: list[list[Cell]] | None = None


@dataclass
class Block:
    key: str
    source: str  # the paragraph as the reader wrote it; a text correction replaces it whole
    parts: list[Part]


def block_key(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def paragraphs(markdown: str) -> list[str]:
    """The reading split as the route splits it into nodes (route.py)."""
    return [p.strip() for p in markdown.split("\n\n") if p.strip()]


def _plain(fragment: str) -> tuple[str, list[str]]:
    text = html.unescape(TAG.sub("", re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)))
    return STRUCK.sub(r"\1", text).strip(), STRUCK.findall(text)


ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
CELL = re.compile(r"<(t[dh])\b([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
SPAN = re.compile(r"""\b(rowspan|colspan)\s*=\s*["']?(\d+)""", re.IGNORECASE)


@dataclass
class CellAt:
    """An origin cell of a table: its grid position, spans, and where its content sits in the table's HTML."""

    row: int
    col: int
    rowspan: int
    colspan: int
    start: int
    end: int
    inner: str


def table_cells(table_html: str) -> list[CellAt]:
    """The origin cells of one HTML table in reading order, rowspan/colspan expanded into grid positions."""
    taken: set[tuple[int, int]] = set()
    out = []
    for r, row in enumerate(ROW.finditer(table_html)):
        c = 0
        for cell in CELL.finditer(row.group(1)):
            spans = {name.lower(): max(1, int(value)) for name, value in SPAN.findall(cell.group(2))}
            while (r, c) in taken:
                c += 1
            rowspan, colspan = spans.get("rowspan", 1), spans.get("colspan", 1)
            taken |= {(r + dr, c + dc) for dr in range(rowspan) for dc in range(colspan)}
            base = row.start(1) + cell.start(3)
            out.append(CellAt(r, c, rowspan, colspan, base, base + len(cell.group(3)), cell.group(3)))
            c += colspan
    return out


def _table(html_table: str) -> list[list[Cell]]:
    """The table as a grid: every position a span covers points at its origin cell."""
    cells = table_cells(html_table)
    if not cells:
        return []
    grid: dict[tuple[int, int], Cell] = {}
    for at in cells:
        text, struck = _plain(at.inner)
        grid[(at.row, at.col)] = Cell(text, struck)
        for dr in range(at.rowspan):
            for dc in range(at.colspan):
                if dr or dc:
                    grid[(at.row + dr, at.col + dc)] = Cell("", span_of=(at.row, at.col))
    height = max(r for r, _ in grid) + 1
    width = max(c for _, c in grid) + 1
    return [[grid.get((r, c), Cell("")) for c in range(width)] for r in range(height)]


def set_cell(source: str, table: int, row: int, col: int, old: str, value: str) -> str | None:
    """``source`` with the cell's text replaced by ``value``, or None when that cell no longer reads ``old``
    (the reading changed since the person decided: the correction is not applied blind)."""
    tables = list(TABLE.finditer(source))
    if table >= len(tables):
        return None
    found = tables[table]
    at = next((a for a in table_cells(found.group(0)) if (a.row, a.col) == (row, col)), None)
    if at is None or _plain(at.inner)[0] != old:
        return None
    begin = found.start() + at.start
    return source[:begin] + html.escape(value, quote=False) + source[found.start() + at.end :]


def set_text(source: str, old: str, text: str) -> str | None:
    """``source`` with the line ``old`` (outside its tables) replaced by ``text``, or None when it is gone."""
    at = 0
    for found in [*TABLE.finditer(source), None]:
        stop = found.start() if found else len(source)
        segment = source[at:stop]
        lines = segment.split("\n")
        for i, line in enumerate(lines):
            if line.strip() and _plain(HEADING.sub(r"\2", line.strip()))[0] == old:
                lines[i] = line.replace(line.strip(), _keep_heading(line.strip(), text), 1)
                return source[:at] + "\n".join(lines) + source[stop:]
        at = found.end() if found else stop
    return None


def _keep_heading(line: str, text: str) -> str:
    match = HEADING.match(line)
    return f"{match.group(1)} {text}" if match else text


def _text_parts(text: str) -> list[Part]:
    parts = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if match := HEADING.match(line.strip()):
            plain, struck = _plain(match.group(2))
            parts.append(Part("heading", plain, struck))
        else:
            plain, struck = _plain(line)
            if parts and parts[-1].kind == "text":
                parts[-1].text = f"{parts[-1].text}\n{plain}"
                parts[-1].struck += struck
            else:
                parts.append(Part("text", plain, struck))
    return parts


def parse_block(source: str, key: str | None = None) -> Block:
    """One paragraph as headings, text and tables; ``key`` keeps the key of the text as first read when
    ``source`` carries corrections already."""
    parts: list[Part] = []
    at = 0
    for match in TABLE.finditer(source):
        parts += _text_parts(source[at : match.start()])
        parts.append(Part("table", rows=_table(match.group(0))))
        at = match.end()
    parts += _text_parts(source[at:])
    return Block(key or block_key(source), source, parts)


def parse_reading(markdown: str) -> list[Block]:
    """The reading as blocks of headings, text and tables, in reading order."""
    return [parse_block(source) for source in paragraphs(markdown)]


def locate(blocks: list[Block], label: str | None, value: str | None) -> dict | None:
    """Where an unsure entry sits: the cell in its label's row when the label is a cell, else the first
    cell or text holding the value. None when the value is not found."""
    needle = value or "[illegible]"
    fallback = None
    for block in blocks:
        tables = [p for p in block.parts if p.kind == "table"]
        for t, part in enumerate(tables):
            for r, row in enumerate(part.rows or []):
                labelled = bool(label) and any(cell.text.strip() == label.strip() for cell in row)
                for c, cell in enumerate(row):
                    if cell.span_of is None and needle in cell.text:
                        found = {"block_key": block.key, "table": t, "cell": [r, c]}
                        if labelled:
                            return found
                        fallback = fallback or found
        if fallback is None and any(p.kind != "table" and needle in (p.text or "") for p in block.parts):
            fallback = {"block_key": block.key, "table": None, "cell": None}
    return fallback
