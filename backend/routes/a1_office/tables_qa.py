"""A1.4 tables (file 03 §A1.4): units per column, QA checks, and the VLM A/B comparison.

Docling serializes each table as HTML with spans. Units in header cells (`Pressure (bar)`, `Thrust [N]`) are
parsed with S1's registry into `metadata.units_by_column`; the HTML keeps the source's look. A table is
suspicious when its rows are ragged after span accounting, when a numeric-dense table has no header, when
more than half its cells are empty, or when it was OCR'd on a page whose `ocr_score` is below 0.75. A
suspicious table is read again from its crop by `read_table_image`: if both versions agree in shape (±1 row
or column) and in ≥ 90% of the sampled numeric cells, the version with the higher confidence is kept and
its source recorded; otherwise the table keeps the TableFormer version, the node is marked for review and a
LOW_CONFIDENCE_EXTRACTION flag (SOFT) carries both versions.
"""

import html as html_lib
import re
from dataclasses import dataclass, field

from backend.common.units import UnitError, parse_unit
from backend.dispatcher.contract import Flag, FlagAnchor, LowConfidenceEvidence, ProcessedNode
from backend.llm_engine.gemini_types import Image
from backend.postgres.enums import FlagSeverity, FlagType, NodeSource, NodeType
from backend.routes.a1_office.preflight import render_crop

ROW = re.compile(r"<tr\b.*?</tr>", re.DOTALL | re.IGNORECASE)
CELL = re.compile(r"<t([dh])\b([^>]*)>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
SPAN = re.compile(r"(rowspan|colspan)\s*=\s*[\"']?(\d+)", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
UNIT_IN_HEADER = re.compile(r"[\(\[]\s*([^\)\]]{1,15})\s*[\)\]]\s*$|(?:\bin\s+)([A-Za-z°/%²³]+)\s*$")
NUMBER = re.compile(r"^[-+−]?\d[\d.,\s']*$")
LOW_TABLE_OCR = 0.75
NUMERIC_HEADERLESS = 0.8
EMPTY_MAX = 0.5
AGREEMENT_MIN = 0.9


@dataclass
class Cell:
    text: str
    header: bool
    rowspan: int = 1
    colspan: int = 1


def parse_cells(table_html: str) -> list[list[Cell]]:
    rows = []
    for row in ROW.findall(table_html):
        cells = []
        for tag, attrs, inner in CELL.findall(row):
            spans = {k.lower(): int(v) for k, v in SPAN.findall(attrs)}
            text = html_lib.unescape(TAG.sub("", inner)).strip()
            cells.append(Cell(text, tag.lower() == "h", spans.get("rowspan", 1), spans.get("colspan", 1)))
        rows.append(cells)
    return rows


def grid(rows: list[list[Cell]]) -> list[list[str | None]]:
    """The expanded grid: spanned cells repeat their text; ragged rows stay short (None-free)."""
    out: list[list[str | None]] = []
    carry: dict[tuple[int, int], str] = {}
    for r, row in enumerate(rows):
        line: list[str | None] = []
        c = 0
        for cell in row:
            while (r, c) in carry:
                line.append(carry.pop((r, c)))
                c += 1
            for dc in range(cell.colspan):
                line.append(cell.text)
                for dr in range(1, cell.rowspan):
                    carry[(r + dr, c + dc)] = cell.text
            c += cell.colspan
        while (r, c) in carry:
            line.append(carry.pop((r, c)))
            c += 1
        out.append(line)
    return out


def units_by_column(rows: list[list[Cell]]) -> list[str | None]:
    header = next((row for row in rows if row and all(cell.header for cell in row)), rows[0] if rows else [])
    units: list[str | None] = []
    for cell in header:
        match = UNIT_IN_HEADER.search(cell.text)
        unit = None
        if match:
            candidate = (match.group(1) or match.group(2) or "").strip()
            try:
                parse_unit(candidate)
                unit = candidate
            except UnitError:
                unit = None
        units.extend([unit] * cell.colspan)
    return units


def qa_reasons(table_html: str, page_ocr_score: float | None) -> list[str]:
    rows = parse_cells(table_html)
    if not rows:
        return ["empty_table"]
    expanded = grid(rows)
    reasons = []
    if len({len(r) for r in expanded}) > 1:
        reasons.append("ragged_rows")
    values = [v for row in expanded for v in row if v is not None]
    if values:
        numeric = sum(1 for v in values if NUMBER.match(v)) / len(values)
        has_header = any(cell.header for cell in rows[0])
        if numeric > NUMERIC_HEADERLESS and not has_header:
            reasons.append("numeric_without_header")
        if sum(1 for v in values if not v) / len(values) > EMPTY_MAX:
            reasons.append("mostly_empty")
    if page_ocr_score is not None and page_ocr_score < LOW_TABLE_OCR:
        reasons.append("low_ocr_page")
    return reasons


def _numbers(expanded: list[list[str | None]]) -> list[str]:
    return [re.sub(r"\s", "", v) for row in expanded for v in row if v and NUMBER.match(v)]


def agreement(a_html: str, b_html: str) -> tuple[bool, float]:
    """(shapes agree within ±1 row and column, share of A's numeric cells found in the same place in B)."""
    a, b = grid(parse_cells(a_html)), grid(parse_cells(b_html))
    rows_ok = abs(len(a) - len(b)) <= 1
    cols_ok = abs(max(map(len, a), default=0) - max(map(len, b), default=0)) <= 1
    numbers_a, numbers_b = _numbers(a), _numbers(b)
    if not numbers_a:
        return rows_ok and cols_ok, 1.0
    matched = sum(1 for x, y in zip(numbers_a, numbers_b, strict=False) if x == y)
    return rows_ok and cols_ok, matched / len(numbers_a)


@dataclass
class TableQA:
    nodes: list[ProcessedNode]
    flags: list[Flag] = field(default_factory=list)
    checked: int = 0


def check_tables(
    nodes: list[ProcessedNode],
    *,
    pdf_bytes: bytes,
    page_ocr: dict[int, float | None],
    vision,
    context: str,
    doc_id: str | None,
    cloud_allowed: bool,
) -> TableQA:
    out: list[ProcessedNode] = []
    result = TableQA(nodes=out)
    for node in nodes:
        if node.node_type != NodeType.TABLE or node.metadata.get("from_image"):
            out.append(node)
            continue
        rows = parse_cells(node.content)
        metadata = {**node.metadata, "units_by_column": units_by_column(rows)}
        reasons = qa_reasons(node.content, page_ocr.get(node.page_no or 0))
        if not reasons or not cloud_allowed or not node.bboxes:
            out.append(node.model_copy(update={"metadata": {**metadata, "qa": reasons}}))
            continue
        result.checked += 1
        box = node.bboxes[0]
        output = vision.read_table_image(
            Image(render_crop(pdf_bytes, box), "image/png"),
            caption=node.metadata.get("caption"),
            context=context,
            doc_id=doc_id,
            anchor=f"page:{node.page_no}:",
        )
        vlm = output.reading
        same_shape, share = agreement(node.content, vlm.html_table)
        page_score = page_ocr.get(node.page_no or 0)
        tableformer_confidence = page_score if page_score is not None else 0.9
        if same_shape and share >= AGREEMENT_MIN:
            if vlm.confidence > tableformer_confidence:
                out.append(
                    node.model_copy(
                        update={
                            "content": vlm.html_table,
                            "source": NodeSource.VLM,
                            "confidence": vlm.confidence,
                            "metadata": {**metadata, "qa": reasons, "chosen": "vlm", "agreement": share},
                        }
                    )
                )
            else:
                out.append(
                    node.model_copy(
                        update={
                            "metadata": {
                                **metadata,
                                "qa": reasons,
                                "chosen": "tableformer",
                                "agreement": share,
                            }
                        }
                    )
                )
            continue
        out.append(
            node.model_copy(
                update={
                    "metadata": {
                        **metadata,
                        "qa": reasons,
                        "chosen": "tableformer",
                        "agreement": share,
                        "needs_review": True,
                    }
                }
            )
        )
        result.flags.append(
            Flag(
                flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
                severity=FlagSeverity.SOFT,
                anchor=FlagAnchor(page=node.page_no, bbox=box.model_dump(exclude={"page_no"})),
                evidence=LowConfidenceEvidence(table_a_html=node.content, table_b_html=vlm.html_table),
            )
        )
    return result
