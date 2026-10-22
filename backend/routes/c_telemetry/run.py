"""Route C for one LabJack LJStreamM run (file 03 §C.1): the ``.dat`` as a ``SeriesSource``.

``v*`` columns are channel voltages (V); ``y*`` columns are the logger's scaled values, whose quantity and
unit the file never states, so they resolve only through ``channel_map`` rules. ``.dat_fail`` →
``FAILED_RUN``. Everything after reading is the shared series path (``series.py``).
"""

import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import BinaryIO

from backend.dispatcher.contract import ProcessedDocument
from backend.postgres.enums import TelemetrySourceFormat
from backend.review.rules import RuleRecord
from backend.routes.c_telemetry.labjack import is_voltage, parse_header, read_batches
from backend.routes.c_telemetry.normalize import NormalizeConfig, SanityRange
from backend.routes.c_telemetry.series import (
    PARSER_VERSION,
    FolderConfig,
    Resolution,
    RunInputs,
    SeriesSource,
    process_series,
    resolve_channels,
    run_uuid_for,
)
from backend.storage.minio import BucketStore

__all__ = [
    "PARSER_VERSION",
    "FolderConfig",
    "Resolution",
    "RunInputs",
    "labjack_source",
    "process_labjack",
    "resolve_channels",
    "run_uuid_for",
]


def labjack_source(open_stream: Callable[[], BinaryIO], head: bytes, name: str) -> SeriesSource:
    header = parse_header(head.decode("utf-8", "replace"))
    if header is None:
        raise ValueError(f"{name} is not an LJStreamM file")

    def open_batches():
        stream = open_stream()
        try:
            yield from read_batches(stream, header)
        finally:
            close = getattr(stream, "release_conn", None)
            stream.close()
            if close:
                close()

    return SeriesSource(
        source_format=TelemetrySourceFormat.LABJACK_DAT,
        header_lines=header.header_lines,
        columns=header.columns,
        open_batches=open_batches,
        started_at=header.started_at,
        started_at_note="header date and time, zone assumed Asia/Kolkata",
        date_source="labjack header",
        voltage=frozenset(c for c in header.channels if is_voltage(c)),
        failed=name.casefold().endswith(".dat_fail"),
    )


def process_labjack(
    open_stream: Callable[[], BinaryIO],
    inputs: RunInputs,
    rules: Sequence[RuleRecord],
    rule_bodies: dict[uuid.UUID, dict],
    telemetry: BucketStore,
    cir: BucketStore,
    head: bytes,
    normalize_config: NormalizeConfig | None = None,
    sanity: Sequence[SanityRange] = (),
    raw_parquet: Path | None = None,
) -> ProcessedDocument:
    return process_series(
        labjack_source(open_stream, head, inputs.name),
        inputs,
        rules,
        rule_bodies,
        telemetry,
        cir,
        normalize_config,
        sanity,
        raw_parquet,
    )
