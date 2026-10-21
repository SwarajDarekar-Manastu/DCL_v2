"""HTML tables for the chunker (file 03 §A1.4 step 6, file 04 §4.1): rows, rowspan groups, row blocks.

A table up to the token cap stays whole; a longer one becomes row blocks with the header repeated, and a
block never cuts a row or a rowspan group. `table_to_text` is the plain form used for embedding.
"""

import html
import math
import re
from collections.abc import Callable

TokenCounter = Callable[[list[str]], list[int]]

ROW = re.compile(r"<tr\b.*?</tr>", re.DOTALL | re.IGNORECASE)
THEAD = re.compile(r"<thead\b.*?</thead>", re.DOTALL | re.IGNORECASE)
TABLE_OPEN = re.compile(r"<table\b[^>]*>", re.IGNORECASE)
ROWSPAN = re.compile(r"rowspan\s*=\s*[\"']?(\d+)", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
CELL_END = re.compile(r"</t[dh]>", re.IGNORECASE)


def table_rows(table_html: str) -> tuple[list[str], list[str]]:
    """(header rows, body rows) as `<tr>…</tr>` strings; the header is `<thead>` or a first all-`<th>` row."""
    thead = THEAD.search(table_html)
    header = ROW.findall(thead.group(0)) if thead else []
    body_html = table_html[: thead.start()] + table_html[thead.end() :] if thead else table_html
    body = ROW.findall(body_html)
    if not header and body and "<td" not in body[0].lower():
        header, body = body[:1], body[1:]
    return header, body


def row_groups(rows: list[str]) -> list[list[str]]:
    """Rows bound together by rowspans: a block may end only where no span is still open."""
    groups: list[list[str]] = []
    open_until = -1
    for i, row in enumerate(rows):
        if i > open_until:
            groups.append([])
        groups[-1].append(row)
        spans = [int(n) for n in ROWSPAN.findall(row)]
        open_until = max(open_until, i + max(spans, default=1) - 1)
    return groups


def table_to_text(table_html: str) -> str:
    """Plain rows for embedding: cells joined by ' | ', rows by newlines (tags cost tokens, not meaning)."""
    lines = []
    for row in ROW.findall(table_html):
        cells = [html.unescape(TAG.sub("", c)).strip() for c in CELL_END.split(row)]
        lines.append(" | ".join(c for c in cells if c))
    return "\n".join(line for line in lines if line)


def split_table(table_html: str, max_tokens: int, count_tokens: TokenCounter) -> list[str]:
    """The whole table when it fits, else row blocks of whole rows with the header repeated in each."""
    if count_tokens([table_html])[0] <= max_tokens:
        return [table_html]
    header, body = table_rows(table_html)
    groups = ["".join(g) for g in row_groups(body)]
    if len(groups) <= 1:
        return [table_html]
    opening = TABLE_OPEN.search(table_html)
    open_tag = opening.group(0) if opening else "<table>"
    head = f"<thead>{''.join(header)}</thead>" if header else ""
    budget = max(1, max_tokens - count_tokens([open_tag + head])[0])
    blocks = _balanced_blocks(groups, count_tokens(groups), budget)
    return [f"{open_tag}{head}<tbody>{''.join(block)}</tbody></table>" for block in blocks]


def _balanced_blocks(groups: list[str], sizes: list[int], budget: int) -> list[list[str]]:
    """ceil(total / budget) blocks of about equal size; a block closes before it would exceed budget."""
    target = sum(sizes) / max(1, math.ceil(sum(sizes) / budget))
    blocks: list[list[str]] = [[]]
    size = 0
    for group, tokens in zip(groups, sizes, strict=True):
        if blocks[-1] and (size + tokens > budget or size >= target):
            blocks.append([])
            size = 0
        blocks[-1].append(group)
        size += tokens
    return blocks
