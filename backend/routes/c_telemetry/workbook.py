"""Route C ``.xlsx`` (and ``.xls`` through LibreOffice), file 03 §C.4.

1. Cached values (``data_only=True``) and formulas (``data_only=False``). A formula without a cached value
   or any error cell (``#REF!``, ``#DIV/0!``, ``#VALUE!``, ``#N/A`` …) → LibreOffice recalculation
   (``backend.common.office.convert``, S4) and the values are read again; errors that persist are a SOFT
   ``CONFLICT`` on the sheet, and the cells stay marked in the table.
2. Hidden and very hidden sheets are processed and tagged ``hidden``.
3. Islands: regions separated by two or more blank rows or columns are separate tables; a single cell on
   the first row of an island (or a bold cell just above it) is its caption.
4. Triage per island: a time column, ≥ 100 rows and numeric density > 0.9 → time series (shared series
   path); everything else → table (HTML table node + row children).
5. Merged cells are expanded; dates come as dates; percent-formatted numbers read as ``25%``.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

import numpy as np
import openpyxl
import pyarrow as pa
from openpyxl.utils import get_column_letter

from backend.postgres.enums import TelemetrySourceFormat
from backend.routes.c_telemetry.delimited import SERIES_MIN_ROWS, TIME_HEADER
from backend.routes.c_telemetry.series import SeriesSource
from backend.routes.c_telemetry.tables import Table, cell_text, header_unit, is_number

ERROR_VALUES = frozenset({"#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NUM!", "#NULL!"})
ISLAND_GAP = 2
NUMERIC_DENSITY = 0.9


@dataclass
class SeriesIsland:
    sheet: str
    cell_range: str
    header: list[str]
    rows: list[list[Any]]
    time_index: int
    hidden: bool = False


@dataclass
class Workbook:
    tables: list[Table] = field(default_factory=list)
    series: list[SeriesIsland] = field(default_factory=list)
    recalculated: bool = False
    recalc_note: str | None = None
    error_sheets: dict[str, list[str]] = field(default_factory=dict)
    sheets: list[str] = field(default_factory=list)


def _needs_recalc(values, formulas) -> bool:
    for ws in formulas.worksheets:
        vs = values[ws.title]
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cached = vs[cell.coordinate].value
                    if cached is None or (isinstance(cached, str) and cached.strip() in ERROR_VALUES):
                        return True
    return False


def _grid(ws) -> dict[tuple[int, int], Any]:
    grid: dict[tuple[int, int], Any] = {}
    for row in ws.iter_rows():
        for cell in row:
            value = cell.value
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and "%" in (cell.number_format or "")
            ):
                value = f"{value * 100:g}%"
            grid[(cell.row, cell.column)] = value
    for merged in ws.merged_cells.ranges:
        top = grid.get((merged.min_row, merged.min_col))
        if top is None:
            continue
        for r in range(merged.min_row, merged.max_row + 1):
            for c in range(merged.min_col, merged.max_col + 1):
                grid[(r, c)] = top
    return grid


def _runs(indices: list[int]) -> list[tuple[int, int]]:
    """Consecutive index runs, joined across gaps shorter than ``ISLAND_GAP``."""
    runs: list[tuple[int, int]] = []
    for i in sorted(set(indices)):
        if runs and i - runs[-1][1] <= ISLAND_GAP:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs


def islands(grid: dict[tuple[int, int], Any]) -> list[tuple[int, int, int, int]]:
    """``(min_row, min_col, max_row, max_col)`` of each island, top to bottom, left to right."""
    out = []
    for r0, r1 in _runs([r for r, _ in grid]):
        cols = [c for r, c in grid if r0 <= r <= r1]
        for c0, c1 in _runs(cols):
            if any((r, c) in grid for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)):
                out.append((r0, c0, r1, c1))
    return out


def _range(r0: int, c0: int, r1: int, c1: int) -> str:
    return f"{get_column_letter(c0)}{r0}:{get_column_letter(c1)}{r1}"


def _seconds(values: list[Any]) -> np.ndarray | None:
    if all(isinstance(v, int | float) and not isinstance(v, bool) for v in values):
        return np.asarray(values, dtype=np.float64)
    if all(isinstance(v, datetime) for v in values):
        return np.asarray([(v - values[0]).total_seconds() for v in values], dtype=np.float64)
    return None


def read_workbook(data: bytes, recalc: Callable[[bytes], bytes] | None = None) -> Workbook:
    book = Workbook()
    values = openpyxl.load_workbook(BytesIO(data), data_only=True)
    formulas = openpyxl.load_workbook(BytesIO(data), data_only=False)
    if recalc is not None and _needs_recalc(values, formulas):
        try:
            values = openpyxl.load_workbook(BytesIO(recalc(data)), data_only=True)
            book.recalculated = True
        except Exception as exc:  # the cached values are still usable; the conflict below says why
            book.recalc_note = f"recalculation failed: {exc}"
    for ws in values.worksheets:
        book.sheets.append(ws.title)
        hidden = ws.sheet_state != "visible"
        grid = _grid(ws)
        errors = sorted(
            f"{get_column_letter(c)}{r}"
            for (r, c), v in grid.items()
            if isinstance(v, str) and v.strip() in ERROR_VALUES
        )
        if errors:
            book.error_sheets[ws.title] = errors
        for r0, c0, r1, c1 in islands(grid):
            matrix = [[grid.get((r, c)) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
            caption = None
            first = [v for v in matrix[0] if v is not None]
            if len(matrix) > 2 and len({cell_text(v) for v in first}) == 1:  # one cell, or one merged title
                caption, matrix, r0 = cell_text(first[0]), matrix[1:], r0 + 1
            matrix = [row for row in matrix if any(v is not None for v in row)]
            if not matrix:
                continue
            cell_range = _range(r0, c0, r1, c1)
            header = [cell_text(v) for v in matrix[0]]
            body = matrix[1:]
            time_index = next((j for j, h in enumerate(header) if TIME_HEADER.match(h.strip())), None)
            if time_index is not None and len(body) >= SERIES_MIN_ROWS:
                cells = [v for row in body for v in row]
                density = sum(1 for v in cells if is_number(v) or isinstance(v, datetime)) / max(
                    1, len(cells)
                )
                times = _seconds([row[time_index] for row in body])
                if density > NUMERIC_DENSITY and times is not None and not np.any(np.diff(times) < 0):
                    book.series.append(SeriesIsland(ws.title, cell_range, header, body, time_index, hidden))
                    continue
            book.tables.append(
                Table(
                    rows=matrix,
                    caption=caption,
                    sheet=ws.title,
                    cell_range=cell_range,
                    hidden=hidden,
                    error_cells=[e for e in errors if _inside(e, r0, c0, r1, c1)],
                )
            )
    return book


def _inside(coordinate: str, r0: int, c0: int, r1: int, c1: int) -> bool:
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

    letters, row = coordinate_from_string(coordinate)
    column = column_index_from_string(letters)
    return r0 <= row <= r1 and c0 <= column <= c1


def island_source(island: SeriesIsland, name: str) -> SeriesSource:
    channels = [
        j
        for j in range(len(island.header))
        if j != island.time_index
        and sum(1 for row in island.rows if is_number(row[j])) >= NUMERIC_DENSITY * len(island.rows)
    ]
    names = [island.header[j] or f"column_{j + 1}" for j in channels]
    columns = ["time_s", *names]
    units = {names[i]: unit for i, j in enumerate(channels) if (unit := header_unit(island.header[j]))}
    times = _seconds([row[island.time_index] for row in island.rows])

    def open_batches() -> Iterator[pa.RecordBatch]:
        arrays = [pa.array(times)]
        for j in channels:
            values = [float(row[j]) if is_number(row[j]) else float("nan") for row in island.rows]
            arrays.append(pa.array(np.asarray(values, dtype=np.float64), from_pandas=True))
        yield pa.RecordBatch.from_arrays(arrays, names=columns)

    return SeriesSource(
        source_format=TelemetrySourceFormat.XLSX_SHEET,
        header_lines=[
            f"workbook: {name}",
            f"sheet: {island.sheet}",
            f"range: {island.cell_range}",
            " | ".join(island.header),
        ],
        columns=columns,
        open_batches=open_batches,
        units=units,
        unit_source="header",
        title=f"{PurePosixPath(name).stem} — {island.sheet}",
    )


def can_handle(head: bytes, name: str) -> bool:
    return name.casefold().endswith((".xlsx", ".xlsm", ".xls"))
