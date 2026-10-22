"""Tables of Route C (file 03 §C.3 "table", §C.4 steps 4–8): an HTML ``table`` node with ``table_row``
children that repeat the header (``Requirement R-12 | Cooling duct shall… | Verification: test``), so one
row is retrievable on its own.

Units: a header cell's trailing ``(bar)`` / ``[N]``, a ``Unit`` column, or a units row under the header
state them. A numeric column that states none is a SOFT ``UNIT_AMBIGUITY`` (matrix tables are indexed
anyway), except columns whose header is on the dimensionless list (FMEA and risk registers would flag on
every row otherwise).
"""

import hashlib
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from backend.common.units import UnitError, parse_unit
from backend.dispatcher.contract import ChannelStats, Flag, FlagAnchor, ProcessedNode, UnitTelemetryEvidence
from backend.postgres.enums import FlagSeverity, FlagType, NodeSource, NodeType

DIMENSIONLESS_HEADERS = (
    "s", "o", "d", "rpn", "severity", "occurrence", "detection", "score", "rank", "index", "count", "%",
    "sr no", "sr no.", "s.no", "sno", "no", "no.", "#", "id", "test no", "test no.", "sample", "edition",
    "revision", "rev", "qty", "quantity", "number",
)  # fmt: skip
HEADER_UNIT = re.compile(r"[\(\[]\s*([^\)\]]+?)\s*[\)\]]")
UNIT_COLUMN = re.compile(r"^units?$", re.IGNORECASE)
MAX_ROW_NODES = 2000


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return (
            value.isoformat(sep=" ", timespec="seconds")
            if value.time() != time(0)
            else value.date().isoformat()
        )
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value).strip()


def is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", "") if value.count(",") and "." in value else value.replace(",", "."))
        except ValueError:
            return False
        return bool(value.strip())
    return False


def header_unit(header: str) -> str | None:
    """The unit a header states in its last brackets, when pint reads it (``Pressure (Bar) [Gauge]``)."""
    for candidate in reversed(HEADER_UNIT.findall(header)):
        for spelling in dict.fromkeys((candidate, candidate.lower())):
            try:
                parse_unit(spelling)
            except UnitError:
                continue
            return spelling
    return None


def dimensionless(header: str, extra: Sequence[str] = ()) -> bool:
    name = HEADER_UNIT.sub("", header).strip().casefold()
    return name in DIMENSIONLESS_HEADERS or name in {e.casefold() for e in extra} or "%" in header


@dataclass
class Table:
    rows: list[list[Any]]  # first row is the header
    caption: str | None = None
    sheet: str | None = None
    cell_range: str | None = None
    hidden: bool = False
    page_note: str | None = None
    error_cells: list[str] = field(default_factory=list)

    @property
    def header(self) -> list[str]:
        return [cell_text(v) or f"column {i + 1}" for i, v in enumerate(self.rows[0])] if self.rows else []

    @property
    def body(self) -> list[list[Any]]:
        return self.rows[1:]

    def column_units(self) -> dict[int, str]:
        units = {i: u for i, h in enumerate(self.header) if (u := header_unit(h))}
        if self.body:
            row = [cell_text(v) for v in self.body[0]]
            parsed = {}
            for i, text in enumerate(row):
                if text and not is_number(text):
                    try:
                        parse_unit(text)
                        parsed[i] = text
                    except UnitError:
                        pass
            if parsed and len(parsed) >= max(1, len([t for t in row if t]) // 2):
                units.update({i: u for i, u in parsed.items() if i not in units})
                self.rows = [self.rows[0], *self.body[1:]]  # the units row is not data
        return units

    def has_unit_column(self) -> bool:
        return any(UNIT_COLUMN.match(h.strip()) for h in self.header)


def table_html(table: Table) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in table.header)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(cell_text(v))}</td>" for v in row) + "</tr>" for row in table.body
    )
    caption = f"<caption>{html.escape(table.caption)}</caption>" if table.caption else ""
    return f"<table>{caption}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def table_nodes(table: Table, ref: str, ordinal: int, breadcrumb: str) -> list[ProcessedNode]:
    """One ``table`` node and its ``table_row`` children (header repeated in every row)."""
    header = table.header
    units = table.column_units()
    title = " — ".join(p for p in (table.sheet, table.caption) if p)
    nodes = [
        ProcessedNode(
            ref=ref,
            node_type=NodeType.TABLE,
            ordinal=ordinal,
            breadcrumb=breadcrumb,
            content=table_html(table),
            sheet_name=table.sheet,
            cell_range=table.cell_range,
            source=NodeSource.STRUCTURED,
            metadata={
                k: v
                for k, v in {
                    "caption": table.caption,
                    "hidden": table.hidden or None,
                    "units": {header[i]: u for i, u in units.items()} or None,
                    "error_cells": table.error_cells or None,
                }.items()
                if v is not None
            },
        )
    ]
    for i, row in enumerate(table.body[:MAX_ROW_NODES]):
        cells = [
            f"{header[j] if j < len(header) else f'column {j + 1}'}: {cell_text(v)}"
            for j, v in enumerate(row)
            if cell_text(v)
        ]
        if not cells:
            continue
        nodes.append(
            ProcessedNode(
                ref=f"{ref}.r{i + 1}",
                parent_ref=ref,
                node_type=NodeType.TABLE_ROW,
                level=1,
                ordinal=ordinal + 1 + i,
                breadcrumb=breadcrumb,
                content=(f"{title} | " if title else "") + " | ".join(cells),
                sheet_name=table.sheet,
                source=NodeSource.STRUCTURED,
            )
        )
    return nodes


def unit_flags(table: Table, extra_dimensionless: Sequence[str] = ()) -> list[Flag]:
    """SOFT ``UNIT_AMBIGUITY`` for numeric columns that state no unit (C.4 step 8, matrix tables)."""
    if not table.body or table.has_unit_column():
        return []
    header = table.header
    units = table.column_units()
    flags = []
    for j, name in enumerate(header):
        values = [row[j] for row in table.body if j < len(row) and cell_text(row[j])]
        if not values or j in units or dimensionless(name, extra_dimensionless):
            continue
        numbers = [float(v) for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
        if len(numbers) < max(1, int(0.8 * len(values))):
            continue
        anchor_key = hashlib.sha256(f"{table.sheet}|{table.cell_range}|{name}".encode()).hexdigest()[:16]
        flags.append(
            Flag(
                flag_type=FlagType.UNIT_AMBIGUITY,
                severity=FlagSeverity.SOFT,
                anchor=FlagAnchor(sheet=table.sheet, column=name, content_sha256=anchor_key),
                evidence=UnitTelemetryEvidence(
                    channel=name,
                    header_lines=[" | ".join(header)],
                    stats=ChannelStats(
                        n=len(numbers), min=min(numbers), max=max(numbers), mean=sum(numbers) / len(numbers)
                    )
                    if numbers
                    else ChannelStats(),
                    note=f"numeric column {name!r} in {table.sheet or 'the table'} states no unit",
                ),
            )
        )
    return flags


def table_document(
    blob_sha256: str,
    name: str,
    context,
    tables: Sequence[Table],
    flags: Sequence[Flag],
    doc_kind,
    cir_put,
    parser_version: int,
    catalog: dict[str, Any] | None = None,
):
    """A Route C document made of tables (CSV below the series threshold, workbook islands)."""
    import json
    from pathlib import PurePosixPath

    from backend.dispatcher.contract import DocumentFields, ProcessedDocument
    from backend.postgres.enums import Route

    prefix = f"{blob_sha256}/{Route.C}/v{parser_version}"
    breadcrumb = " › ".join(context.breadcrumb)
    nodes: list[ProcessedNode] = []
    for i, table in enumerate(tables):
        nodes += table_nodes(table, f"t{i + 1}", len(nodes), breadcrumb)
    cir_put(
        f"{prefix}/tables.json",
        json.dumps(
            [
                {
                    "sheet": t.sheet,
                    "range": t.cell_range,
                    "caption": t.caption,
                    "hidden": t.hidden,
                    "rows": [[cell_text(v) for v in row] for row in t.rows],
                }  # fmt: skip
                for t in tables
            ],
            indent=1,
        ).encode(),
    )
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.C,
        parser_version=parser_version,
        cir_uri=f"s3://dcl-cir/{prefix}/",
        document=DocumentFields(
            title=PurePosixPath(name).stem,
            doc_kind=doc_kind,
            source_origin=context.source_origin,
            trust_tier=context.trust_tier,
            test_plan_id=context.test_plan_id,
            test_run_id=context.test_run_id,
            hardware_item=context.hardware_item,
            unit_count=len({t.sheet for t in tables if t.sheet}) or len(tables),
            catalog=catalog,
        ),
        nodes=nodes,
        flags=list(flags),
    )
