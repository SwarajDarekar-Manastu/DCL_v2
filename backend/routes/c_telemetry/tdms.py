"""LabVIEW ``.tdms`` (file 03 §C.2): npTDMS reads groups and channels with their properties; the
properties supply units (``unit_string``) and the time base (``wf_increment``, ``wf_start_time``), and the
rest is the shared series path. ``.tdms_index`` is ignored (npTDMS rebuilds it).

One run per file: the group with the most samples. Time, in order: a channel named like time
(``TimeStamps``, ``Time``, ``t``), else the waveform increment, else the group's ``ScanRate``. A channel
with no ``unit_string`` stays unresolved (HARD ``UNIT_AMBIGUITY``) unless a rule maps it; the units of a
sibling export of the same run (a DAQ ``.csv``) are attached as evidence.
"""

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
from nptdms import TdmsFile

from backend.dispatcher.contract import SiblingUnit
from backend.postgres.enums import TelemetrySourceFormat
from backend.routes.c_telemetry.series import SeriesSource

TIME_NAMES = frozenset({"time", "timestamps", "timestamp", "t", "time_s", "time (s)"})
CHUNK_ROWS = 100_000
SKIP_PROPERTIES = frozenset({"UISettings"})
MAX_PROPERTY_CHARS = 200


def can_handle(head: bytes, name: str) -> bool:
    return head.startswith(b"TDSm")


def _properties(prefix: str, properties) -> list[str]:
    lines = []
    for key, value in properties.items():
        text = str(value)
        if key in SKIP_PROPERTIES or len(text) > MAX_PROPERTY_CHARS:
            continue
        lines.append(f"{prefix}{key}: {text}")
    return lines


def _start(value) -> datetime | None:
    if value is None:
        return None
    try:
        stamp = np.datetime64(value, "us").astype(datetime)
    except (TypeError, ValueError):
        return None
    return stamp.replace(tzinfo=UTC) if isinstance(stamp, datetime) else None


def tdms_source(path: Path, name: str, sibling_units: Sequence[SiblingUnit] = ()) -> SeriesSource:
    tdms = TdmsFile.open(path)
    try:
        groups = [g for g in tdms.groups() if g.channels()]
        if not groups:
            raise ValueError(f"{name} has no channels")
        group = max(groups, key=lambda g: max(len(c) for c in g.channels()))
        channels = [c for c in group.channels() if np.issubdtype(c.dtype, np.number) or c.dtype.kind == "M"]
        length = max(len(c) for c in channels)
        time_channel = next((c for c in channels if c.name.strip().casefold() in TIME_NAMES), None)
        data_channels = [
            c for c in channels if c is not time_channel and c.dtype.kind != "M" and len(c) == length
        ]
        increment = next(
            (c.properties.get("wf_increment") for c in data_channels if c.properties.get("wf_increment")),
            None,
        )
        rate = group.properties.get("ScanRate") or group.properties.get("wf_samples_per_second")
        if time_channel is not None:
            time_name, time_note = time_channel.name, f"channel {time_channel.name}"
        elif increment:
            time_name, time_note = "time_s", f"wf_increment {increment} s"
        elif rate:
            time_name, time_note = "time_s", f"group ScanRate {rate} Hz"
        else:
            raise ValueError(f"{name}: no time channel, waveform increment or scan rate")
        header_lines = [
            f"file: {name}",
            *_properties("file.", tdms.properties),
            f"group: {group.name}",
            *_properties("group.", group.properties),
            f"time: {time_note}",
        ]
        for channel in data_channels:
            header_lines += _properties(f"{channel.name}.", channel.properties)
        units = {}
        for c in data_channels:
            stated = str(c.properties.get("unit_string", "")).strip()
            if stated:
                units[c.name] = stated  # NI spellings ("Deg C") are aliases in config/units.txt
        started = _start(group.properties.get("StartTime")) or _start(
            next(
                (
                    c.properties.get("wf_start_time")
                    for c in data_channels
                    if c.properties.get("wf_start_time")
                ),
                None,
            )
        )
        columns = [time_name, *[c.name for c in data_channels]]
    finally:
        tdms.close()

    def open_batches() -> Iterator[pa.RecordBatch]:
        with TdmsFile.open(path) as handle:
            source_group = handle[group.name]
            for offset in range(0, length, CHUNK_ROWS):
                n = min(CHUNK_ROWS, length - offset)
                if time_channel is not None:
                    raw_time = source_group[time_channel.name][offset : offset + n]
                    if raw_time.dtype.kind == "M":
                        first = source_group[time_channel.name][0]
                        raw_time = (raw_time - first) / np.timedelta64(1, "us") / 1e6
                    t = np.asarray(raw_time, dtype=np.float64)
                elif increment:
                    t = (np.arange(offset, offset + n) * float(increment)).astype(np.float64)
                else:
                    t = (np.arange(offset, offset + n) / float(rate)).astype(np.float64)
                arrays = [pa.array(t)]
                for channel in data_channels:
                    values = np.asarray(source_group[channel.name][offset : offset + n], dtype=np.float64)
                    arrays.append(pa.array(values, from_pandas=True))
                yield pa.RecordBatch.from_arrays(arrays, names=columns)

    return SeriesSource(
        source_format=TelemetrySourceFormat.TDMS,
        header_lines=header_lines,
        columns=columns,
        open_batches=open_batches,
        started_at=started,
        started_at_note="TDMS StartTime, UTC" if started else None,
        date_source="tdms properties" if started else None,
        units=units,
        unit_source="tdms_props",
        sibling_units=sibling_units,
    )
