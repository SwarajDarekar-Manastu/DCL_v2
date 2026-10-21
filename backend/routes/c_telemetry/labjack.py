"""LabJack LJStreamM ``.dat`` / ``.dat_fail`` files (file 03 §C.1), in the layout found by the crawl:

    29-12-2025          date (dd-mm-yyyy)
    14:18:41            time
    (blank lines)
    Time\\tv0\\tv1…\\ty0\\ty1…   tab-separated header; v* = channel voltages, y* = scaled values
    0.000000\\t0.796947…  data, time in seconds from the start

The header lines are kept verbatim for the CIR and the review evidence. Data is read in Arrow
batches (never one big DataFrame); the time column must be numeric.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.csv as pacsv

DATE_LINE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
TIME_LINE = re.compile(r"^\d{1,2}:\d{2}:\d{2}(\.\d+)?$")
HEADER_SCAN_LINES = 20
VOLTAGE_COLUMN = re.compile(r"^v\d+$")
LAB_TIMEZONE = ZoneInfo("Asia/Kolkata")  # the header has no zone; the test cells run on IST
READ_BLOCK_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class LabJackHeader:
    header_lines: list[str]
    columns: list[str]
    data_start_line: int
    started_at: datetime | None

    @property
    def time_column(self) -> str:
        return self.columns[0]

    @property
    def channels(self) -> list[str]:
        return self.columns[1:]


def parse_header(text: str) -> LabJackHeader | None:
    """The header of an LJStreamM file, or None when the text is not one."""
    lines = text.splitlines()[:HEADER_SCAN_LINES]
    nonblank = [(i, line.strip()) for i, line in enumerate(lines) if line.strip()]
    if len(nonblank) < 3 or not DATE_LINE.match(nonblank[0][1]) or not TIME_LINE.match(nonblank[1][1]):
        return None
    index, header = nonblank[2]
    columns = header.split("\t")
    if len(columns) < 2 or columns[0].strip().casefold() != "time":
        return None
    try:
        started = datetime.strptime(f"{nonblank[0][1]} {nonblank[1][1].split('.')[0]}", "%d-%m-%Y %H:%M:%S")
        started_at = started.replace(tzinfo=LAB_TIMEZONE)
    except ValueError:
        started_at = None
    return LabJackHeader(
        header_lines=lines[: index + 1],
        columns=[c.strip() for c in columns],
        data_start_line=index + 1,
        started_at=started_at,
    )


def can_handle(head: bytes, name: str) -> bool:
    return (
        name.casefold().endswith((".dat", ".dat_fail"))
        and parse_header(head.decode("utf-8", "replace")) is not None
    )


def is_voltage(column: str) -> bool:
    return VOLTAGE_COLUMN.match(column) is not None


def read_batches(stream: BinaryIO, header: LabJackHeader) -> Iterator[pa.RecordBatch]:
    reader = pacsv.open_csv(
        pa.PythonFile(stream, mode="r"),
        read_options=pacsv.ReadOptions(
            skip_rows=header.data_start_line, column_names=header.columns, block_size=READ_BLOCK_BYTES
        ),
        parse_options=pacsv.ParseOptions(delimiter="\t", ignore_empty_lines=True),
        convert_options=pacsv.ConvertOptions(column_types={c: pa.float64() for c in header.columns}),
    )
    yield from reader
