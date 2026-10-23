"""Route C ``.csv`` / ``.tsv`` (file 03 §C.3).

- Encoding (UTF-8 with or without BOM, else cp1252), delimiter (``,`` ``;`` tab ``|``), decimal comma
  (with ``;`` delimiters) and quoting are sniffed. Lines before the header row (a DAQ export's ``Device:``,
  ``Scan Rate:``, ``Start Time:``) are kept verbatim as header lines; trailing rows that break the
  numeric pattern are footer metadata.
- The header row is the first row with mostly non-numeric cells followed by a mostly numeric row; a units
  row under it is read as units. Units otherwise come from header cells (``T1 - flange (°C)``).
- Triage: a time column (named like time, monotonic) and at least ``SERIES_MIN_ROWS`` rows → time series
  (the shared series path); otherwise a table document (HTML table node + row children).
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa

from backend.postgres.enums import TelemetrySourceFormat
from backend.routes.c_telemetry.series import SeriesSource
from backend.routes.c_telemetry.tables import Table, header_unit, is_number

SERIES_MIN_ROWS = 100
DELIMITERS = ",;\t|"
TIME_HEADER = re.compile(
    r"^(time|t|timestamp|timestamps|date\s*/\s*time|datetime|date time|elapsed.*|time\s*[\(\[].*)$", re.I
)
INDEX_HEADER = re.compile(r"^(sample|samples|index|#|no\.?|sr\.?\s*no\.?)$", re.I)
SCAN_RATE = re.compile(r"scan\s*rate\s*[:=]\s*([0-9.]+)", re.I)
START_TIME = re.compile(r"start\s*time\s*[:=]\s*(.+)$", re.I)
CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")
DATE_FORMATS = (
    "%d-%m-%Y %H:%M:%S.%f",
    "%d-%m-%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
)
LAB_TIMEZONE = ZoneInfo("Asia/Kolkata")


@dataclass
class Delimited:
    preamble: list[str]
    header: list[str]
    rows: list[list[str]]
    footer: list[list[str]] = field(default_factory=list)
    delimiter: str = ","
    decimal_comma: bool = False
    header_lines: tuple[int, int] | None = None  # (first, last) file line of the header record
    row_lines: list[tuple[int, int]] = field(default_factory=list)  # parallel to ``rows``

    def number(self, text: str) -> float:
        text = text.strip()
        if self.decimal_comma:
            text = text.replace(".", "").replace(",", ".")
        return float(text) if text else float("nan")


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _numeric(cells: list[str]) -> int:
    return sum(1 for c in cells if is_number(c))


def read_delimited(data: bytes) -> Delimited:
    text = decode(data).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    sample = "\n".join(lines[:60])
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=DELIMITERS).delimiter
    except csv.Error:
        delimiter = max(DELIMITERS, key=sample.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: list[list[str]] = []
    spans: list[tuple[int, int]] = []  # file lines of each record (a quoted cell may span lines)
    last_line = 0
    for row in reader:
        rows.append([cell.strip() for cell in row])
        spans.append((last_line + 1, reader.line_num))
        last_line = reader.line_num
    while rows and not any(rows[-1]):
        rows.pop()
        spans.pop()
    header_index = None
    for i, row in enumerate(rows[:-1]):
        filled = [c for c in row if c]
        following = [c for c in rows[i + 1] if c]
        if (
            len(filled) >= 2
            and _numeric(filled) <= len(filled) // 2
            and following
            and _numeric(following) >= len(following) / 2
        ):
            header_index = i
            break
    if header_index is None:
        header_index = 0
    preamble = [
        line.strip().strip(delimiter) for line in lines[:header_index] if line.strip().strip(delimiter)
    ]
    preamble = [line.replace('"', "") for line in preamble]
    header = rows[header_index] if rows else []
    kept = [
        (r, span)
        for r, span in zip(rows[header_index + 1 :], spans[header_index + 1 :], strict=True)
        if any(r)
    ]
    body = [r for r, _ in kept]
    body_lines = [span for _, span in kept]
    numeric_columns = sum(
        1 for j in range(len(header)) if body and is_number(body[0][j] if j < len(body[0]) else "")
    )
    footer: list[list[str]] = []
    while body and numeric_columns and _numeric(body[-1]) < numeric_columns:
        footer.insert(0, body.pop())
        body_lines.pop()
    decimal_comma = delimiter == ";" and any(re.fullmatch(r"-?\d+,\d+", c) for r in body[:20] for c in r)
    return Delimited(
        preamble,
        header,
        body,
        footer,
        delimiter,
        decimal_comma,
        header_lines=spans[header_index] if rows else None,
        row_lines=body_lines,
    )


def _seconds(values: list[str]) -> np.ndarray | None:
    """Seconds from numbers, datetimes or clock strings (``45:10.6``, ``13:25:17.6``); None if unreadable."""
    try:
        return np.array([float(v) for v in values], dtype=np.float64)
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            stamps = [datetime.strptime(v, fmt) for v in values]
        except ValueError:
            continue
        return np.array([(s - stamps[0]).total_seconds() for s in stamps], dtype=np.float64)
    clocks = [CLOCK.match(v) for v in values]
    if all(clocks):
        raw = np.array(
            [int(m[1] or 0) * 3600 + int(m[2]) * 60 + float(m[3]) for m in clocks], dtype=np.float64
        )
        period = 3600.0 if all(m[1] is None for m in clocks) else 86400.0
        steps = np.concatenate([[0.0], np.cumsum(np.diff(raw) < 0) * period])  # the clock wrapped
        return raw + steps
    return None


def _scan_rate(preamble: list[str]) -> float | None:
    for line in preamble:
        if match := SCAN_RATE.search(line):
            return float(match[1]) or None
    return None


def _start_time(preamble: list[str]) -> datetime | None:
    for line in preamble:
        if match := START_TIME.search(line):
            value = match[1].strip()
            for fmt in DATE_FORMATS:
                try:
                    return datetime.strptime(value, fmt).replace(tzinfo=LAB_TIMEZONE)
                except ValueError:
                    continue
    return None


@dataclass(frozen=True)
class SeriesPlan:
    time: np.ndarray
    time_note: str
    channels: list[int]


def series_plan(table: Delimited) -> SeriesPlan | None:
    """The time base and the numeric channel columns, when the file is a time series (C.3 triage)."""
    if len(table.rows) < SERIES_MIN_ROWS:
        return None
    columns = list(zip(*[r + [""] * (len(table.header) - len(r)) for r in table.rows], strict=False))
    time_index = next((j for j, h in enumerate(table.header) if TIME_HEADER.match(h.strip())), None)
    time_values = list(columns[time_index]) if time_index is not None else []
    if table.decimal_comma:
        time_values = [f"{table.number(v):.12g}" if is_number(v) else v for v in time_values]
    time = _seconds(time_values) if time_index is not None else None
    note = f"column {table.header[time_index]}" if time is not None else ""
    index_column = next((j for j, h in enumerate(table.header) if INDEX_HEADER.match(h.strip())), None)
    if time is None:
        rate = _scan_rate(table.preamble)
        if rate is None:
            return None
        time = np.arange(len(table.rows), dtype=np.float64) / rate
        note = f"row index / Scan Rate {rate:g} Hz"
    if len(time) > 1 and np.any(np.diff(time) < 0):
        return None
    skip = {time_index, index_column}
    channels = [
        j
        for j in range(len(table.header))
        if j not in skip and sum(1 for v in columns[j] if is_number(v)) >= 0.9 * len(table.rows)
    ]
    return SeriesPlan(time, note, channels) if channels else None


def delimited_source(table: Delimited, plan: SeriesPlan, name: str) -> SeriesSource:
    names = [table.header[j] or f"column_{j + 1}" for j in plan.channels]
    columns = ["time_s", *names]
    units = {names[i]: unit for i, j in enumerate(plan.channels) if (unit := header_unit(table.header[j]))}
    started = _start_time(table.preamble)
    header_lines = [*table.preamble, table.delimiter.join(table.header), f"time: {plan.time_note}"]
    header_lines += [f"footer: {table.delimiter.join(r)}" for r in table.footer]

    def open_batches() -> Iterator[pa.RecordBatch]:
        arrays = [pa.array(plan.time)]
        for j in plan.channels:
            values = [
                table.number(r[j]) if j < len(r) and is_number(r[j]) else float("nan") for r in table.rows
            ]
            arrays.append(pa.array(np.asarray(values, dtype=np.float64), from_pandas=True))
        yield pa.RecordBatch.from_arrays(arrays, names=columns)

    return SeriesSource(
        source_format=TelemetrySourceFormat.CSV,
        header_lines=header_lines,
        columns=columns,
        open_batches=open_batches,
        started_at=started,
        started_at_note="preamble Start Time, zone assumed Asia/Kolkata" if started else None,
        date_source="csv preamble" if started else None,
        units=units,
        unit_source="header",
        title=PurePosixPath(name).stem,
    )


def as_table(table: Delimited, name: str) -> Table:
    return Table(
        rows=[table.header, *table.rows],
        caption=PurePosixPath(name).stem,
        page_note="; ".join(table.preamble) or None,
        row_lines=[table.header_lines, *table.row_lines] if table.header_lines else None,
    )


def can_handle(head: bytes, name: str) -> bool:
    return name.casefold().endswith((".csv", ".tsv")) and b"\x00" not in head[:4096]
