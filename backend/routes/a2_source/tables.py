"""``tabular``-family environments → HTML tables (file 03 §A2.2 step 4; the indexer's format, A1.4).

Rows end at ``\\\\``, cells at ``&``; ``\\multicolumn`` and ``\\multirow`` become ``colspan``/``rowspan``.
The first row is a header when every non-empty cell is bold, the row is coloured (``\\rowcolor``), or a
``\\midrule`` follows it. ``longtable`` rows before ``\\endfirsthead`` are the header, the repeated head
(``\\endhead``) and the foot sections are dropped.
"""

import html
from collections.abc import Callable
from dataclasses import dataclass, field

from pylatexenc.latexwalker import LatexCharsNode, LatexCommentNode, LatexGroupNode, LatexMacroNode

BOLD = frozenset({"textbf", "bfseries", "bf"})


@dataclass
class Cell:
    text: str
    colspan: int = 1
    rowspan: int = 1
    bold: bool = False


@dataclass
class Table:
    rows: list[list[Cell]]
    header_rows: int

    def html(self, caption: str | None) -> str:
        out = ["<table>"]
        if caption:
            out.append(f"<caption>{html.escape(caption)}</caption>")
        sections = [
            ("thead", "th", self.rows[: self.header_rows]),
            ("tbody", "td", self.rows[self.header_rows :]),
        ]
        for wrapper, tag, rows in sections:
            if not rows:
                continue
            out.append(f"<{wrapper}>")
            for row in rows:
                cells = []
                for cell in row:
                    attrs = (f' colspan="{cell.colspan}"' if cell.colspan > 1 else "") + (
                        f' rowspan="{cell.rowspan}"' if cell.rowspan > 1 else ""
                    )
                    cells.append(f"<{tag}{attrs}>{html.escape(cell.text)}</{tag}>")
                out.append("<tr>" + "".join(cells) + "</tr>")
            out.append(f"</{wrapper}>")
        out.append("</table>")
        return "".join(out)

    def grid(self) -> list[list[str]]:
        return [[cell.text for cell in row] for row in self.rows]


def _significant(nodes: list) -> list:
    return [
        n
        for n in nodes
        if not (isinstance(n, LatexCharsNode) and not n.chars.strip()) and not isinstance(n, LatexCommentNode)
    ]


def _arg(node, index: int):
    argd = getattr(node, "nodeargd", None)
    if argd is None or index >= len(argd.argnlist):
        return None
    return argd.argnlist[index]


def _int(node, default: int = 1) -> int:
    if node is None:
        return default
    text = "".join(n.latex_verbatim() for n in node.nodelist) if isinstance(node, LatexGroupNode) else ""
    try:
        return max(abs(int(text.strip())), 1)
    except ValueError:
        return default


def _content(node) -> list:
    if node is None:
        return []
    return list(node.nodelist) if isinstance(node, LatexGroupNode) else [node]


def _bold(nodes: list) -> bool:
    significant = _significant(nodes)
    if not significant:
        return False
    first = significant[0]
    if isinstance(first, LatexMacroNode) and first.macroname in BOLD:
        return True
    if isinstance(first, LatexGroupNode):
        return _bold(first.nodelist)
    if isinstance(first, LatexMacroNode) and first.macroname in ("multicolumn", "multirow"):
        return _bold(_content(_arg(first, 2 if first.macroname == "multicolumn" else 5)))
    return False


@dataclass
class TableBuilder:
    rows: list[list[Cell]] = field(default_factory=list)
    current: list[Cell] = field(default_factory=list)
    colored_rows: set[int] = field(default_factory=set)
    midrule_after: set[int] = field(default_factory=set)
    caption: str | None = None
    number: str | None = None
    labels: list[str] = field(default_factory=list)
    header_end: int | None = None
    segment_start: int = 0

    def add_cell(self, nodes: list, render: Callable[[list], str]) -> None:
        significant = _significant(nodes)
        colspan = rowspan = 1
        content = nodes
        if significant and isinstance(significant[0], LatexMacroNode):
            first = significant[0]
            if first.macroname == "multicolumn":
                colspan, content = _int(_arg(first, 0)), _content(_arg(first, 2))
                inner = _significant(content)
                if inner and isinstance(inner[0], LatexMacroNode) and inner[0].macroname == "multirow":
                    rowspan, content = _int(_arg(inner[0], 1)), _content(_arg(inner[0], 5))
            elif first.macroname == "multirow":
                rowspan, content = _int(_arg(first, 1)), _content(_arg(first, 5))
        self.current.append(Cell(render(content), colspan, rowspan, _bold(nodes)))

    def end_row(self) -> None:
        cells, self.current = self.current, []
        if not any(c.text for c in cells) and all(c.colspan == 1 for c in cells) and len(cells) <= 1:
            return
        self.rows.append(cells)

    def rule(self, name: str) -> None:
        if name == "midrule" and self.rows:
            self.midrule_after.add(len(self.rows) - 1)

    def row_colored(self) -> None:
        self.colored_rows.add(len(self.rows))

    def marker(self, name: str) -> None:
        """A longtable marker closes the rows since the previous marker: the first head is kept as the
        header, a repeated head and the feet are dropped."""
        if self.current:
            self.end_row()
        start = self.segment_start
        if name == "endfirsthead" or (name == "endhead" and self.header_end is None):
            self.header_end = len(self.rows)
        else:
            del self.rows[start:]
        self.segment_start = len(self.rows)

    def build(self) -> Table | None:
        rows = [row for row in self.rows if any(c.text for c in row) or len(row) > 1]
        if not rows:
            return None
        if self.header_end:
            header = self.header_end
        else:
            first = [c for c in rows[0] if c.text]
            header = int(
                len(rows) > 1
                and (
                    (first and all(c.bold for c in first))
                    or 0 in self.colored_rows
                    or 0 in self.midrule_after
                )
            )
        return Table(rows, header)
