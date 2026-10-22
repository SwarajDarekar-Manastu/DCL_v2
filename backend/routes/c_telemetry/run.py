"""Route C for one LabJack run (file 03 §C.1), step 1: raw Parquet, stats, channel resolution, flags.

The raw file is streamed into ``dcl-telemetry/{run_uuid}/raw.parquet`` (original names and units).
Every channel needs a physical quantity and unit: ``v*`` columns are channel voltages (V); every other
channel is resolved through ``channel_map`` rules (most specific rule that names it). An unresolved
channel raises a HARD ``UNIT_AMBIGUITY`` with the header lines and the channel's stats as evidence.
Normalized Parquet, t0 alignment and the three-tier metrics follow once every channel resolves.
"""

import json
import tempfile
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from backend.dispatcher.contract import (
    ChannelStats,
    DocumentFields,
    Flag,
    FlagAnchor,
    ProcessedDocument,
    ProcessedNode,
    TelemetryChannelRecord,
    TelemetryRunRecord,
    UnitTelemetryEvidence,
)
from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import (
    DocKind,
    FlagSeverity,
    FlagType,
    GaugeOrAbs,
    NodeSource,
    NodeType,
    Route,
    RuleType,
    RunStatus,
    TelemetrySourceFormat,
)
from backend.review.rules import ChannelMapEntry, RuleRecord, RuleTarget, parse_body, resolve_where
from backend.routes.c_telemetry.labjack import LabJackHeader, is_voltage, parse_header, read_batches
from backend.storage.minio import BucketStore
from backend.storage.parquet import schema_with_metadata, telemetry_key, write_batches

PARSER_VERSION = 1
RUN_NAMESPACE = uuid.UUID("8f0b5c3e-2a64-4f4e-9d2b-6b8d1a1d7c01")
GAP_FACTOR = 1.5


def run_uuid_for(blob_sha256: str) -> uuid.UUID:
    """Stable per content: re-processing the same bytes writes the same run directory."""
    return uuid.uuid5(RUN_NAMESPACE, blob_sha256)


@dataclass
class _Running:
    n: int = 0
    nulls: int = 0
    total: float = 0.0
    total_sq: float = 0.0
    minimum: float = float("inf")
    maximum: float = float("-inf")

    def add(self, column: pa.Array) -> None:
        values = column.to_numpy(zero_copy_only=False)
        valid = values[~np.isnan(values)]
        self.nulls += len(values) - len(valid)
        if len(valid):
            self.n += len(valid)
            self.total += float(valid.sum())
            self.total_sq += float(np.square(valid).sum())
            self.minimum = min(self.minimum, float(valid.min()))
            self.maximum = max(self.maximum, float(valid.max()))

    def stats(self, p50: float | None, p99: float | None) -> ChannelStats:
        if not self.n:
            return ChannelStats(n=0)
        mean = self.total / self.n
        variance = max(self.total_sq / self.n - mean * mean, 0.0)
        return ChannelStats(
            n=self.n, min=self.minimum, max=self.maximum, mean=mean, std=variance**0.5, p50=p50, p99=p99
        )


@dataclass
class _TimeBase:
    first: float | None = None
    last: float | None = None
    nominal_dt: float | None = None
    gaps: int = 0
    duplicates: int = 0
    backwards: int = 0
    rows: int = 0

    def add(self, column: pa.Array) -> None:
        t = column.to_numpy(zero_copy_only=False)
        if not len(t):
            return
        series = t if self.last is None else np.concatenate([[self.last], t])
        diffs = np.diff(series)
        if self.nominal_dt is None and len(diffs):
            positive = diffs[diffs > 0]
            self.nominal_dt = float(np.median(positive)) if len(positive) else None
        self.first = float(t[0]) if self.first is None else self.first
        self.last = float(t[-1])
        self.rows += len(t)
        self.duplicates += int((diffs == 0).sum())
        self.backwards += int((diffs < 0).sum())
        if self.nominal_dt:
            self.gaps += int((diffs > GAP_FACTOR * self.nominal_dt).sum())

    @property
    def duration_s(self) -> float | None:
        return None if self.first is None or self.last is None else self.last - self.first

    @property
    def actual_rate_hz(self) -> float | None:
        duration = self.duration_s
        return (self.rows - 1) / duration if duration else None


@dataclass(frozen=True)
class RunInputs:
    blob_sha256: str
    name: str
    context: FolderContext
    target: RuleTarget


@dataclass
class Resolution:
    mapped: dict[str, ChannelMapEntry] = field(default_factory=dict)
    rule_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)


def resolve_channels(
    channels: Sequence[str], rules: Sequence[RuleRecord], bodies: dict[uuid.UUID, dict], target: RuleTarget
) -> Resolution:
    resolution = Resolution()
    parsed = {rule_id: parse_body(RuleType.CHANNEL_MAP, body) for rule_id, body in bodies.items()}
    for channel in channels:
        if is_voltage(channel):
            continue
        rule = resolve_where(
            rules,
            target,
            RuleType.CHANNEL_MAP,
            lambda r, c=channel: c in getattr(parsed.get(r.rule_id), "channels", {}),
        )
        if rule is None:
            resolution.unresolved.append(channel)
        else:
            resolution.mapped[channel] = parsed[rule.rule_id].channels[channel]
            resolution.rule_ids[channel] = rule.rule_id
    return resolution


def _run_label(context: FolderContext, name: str) -> str:
    prefix = context.test_plan_id or context.hardware_item
    run = context.test_run_id
    if prefix and run:
        return f"{prefix}_{run}"
    return PurePosixPath(name).stem


def process_labjack(
    open_stream: Callable[[], BinaryIO],
    inputs: RunInputs,
    rules: Sequence[RuleRecord],
    rule_bodies: dict[uuid.UUID, dict],
    telemetry: BucketStore,
    cir: BucketStore,
    head: bytes,
) -> ProcessedDocument:
    header = parse_header(head.decode("utf-8", "replace"))
    if header is None:
        raise ValueError(f"{inputs.name} is not an LJStreamM file")
    run_id = run_uuid_for(inputs.blob_sha256)
    label = _run_label(inputs.context, inputs.name)
    failed = inputs.name.casefold().endswith(".dat_fail")
    resolution = resolve_channels(header.channels, rules, rule_bodies, inputs.target)

    raw_schema = _raw_schema(header, run_id, label, inputs.blob_sha256)
    running = {c: _Running() for c in header.channels}
    timebase = _TimeBase()

    def batches():
        stream = open_stream()
        try:
            for batch in read_batches(stream, header):
                timebase.add(batch.column(0))
                for i, channel in enumerate(header.channels, start=1):
                    running[channel].add(batch.column(i))
                yield batch
        finally:
            close = getattr(stream, "release_conn", None)
            stream.close()
            if close:
                close()

    with tempfile.TemporaryDirectory(prefix="dcl-route-c-") as workdir:
        path = Path(workdir) / "raw.parquet"
        write_batches(path, raw_schema, batches())
        quantiles = _quantiles(path, header.channels)
        raw_uri = telemetry.put_file(
            telemetry_key(str(run_id), "raw"), str(path), "application/vnd.apache.parquet"
        )

    stats = {c: running[c].stats(*quantiles[c]) for c in header.channels}
    prefix = f"{inputs.blob_sha256}/{Route.C}/v{PARSER_VERSION}"
    schema_doc = {
        "header_lines": header.header_lines,
        "columns": header.columns,
        "time_column": {"name": header.time_column, "unit": "s"},
        "started_at": header.started_at.isoformat() if header.started_at else None,
        "started_at_zone": "assumed Asia/Kolkata",
        "channels": {
            c: (
                {"quantity": "voltage", "unit": "V", "source": "labjack voltage column"}
                if is_voltage(c)
                else resolution.mapped[c].model_dump(mode="json")
                if c in resolution.mapped
                else {"unresolved": True}
            )
            for c in header.channels
        },
    }
    schema_uri = cir.put(
        f"{prefix}/schema.json", json.dumps(schema_doc, indent=1).encode(), "application/json"
    )
    cir.put(
        f"{prefix}/stats.json",
        json.dumps(
            {
                "rows": timebase.rows,
                "duration_s": timebase.duration_s,
                "nominal_dt_s": timebase.nominal_dt,
                "actual_rate_hz": timebase.actual_rate_hz,
                "gaps": timebase.gaps,
                "duplicate_timestamps": timebase.duplicates,
                "backward_timestamps": timebase.backwards,
                "channels": {c: s.model_dump(mode="json") for c, s in stats.items()},
            },
            indent=1,
        ).encode(),
        "application/json",
    )

    channels = [_channel_record(c, stats[c], resolution) for c in header.channels]
    flags = [
        Flag(
            flag_type=FlagType.UNIT_AMBIGUITY,
            severity=FlagSeverity.HARD,
            anchor=FlagAnchor(channel=c),
            evidence=UnitTelemetryEvidence(channel=c, header_lines=header.header_lines, stats=stats[c]),
        )
        for c in resolution.unresolved
    ]
    rate = timebase.actual_rate_hz
    record = TelemetryRunRecord(
        run_uuid=run_id,
        run_label=label,
        source_format=TelemetrySourceFormat.LABJACK_DAT,
        run_status=RunStatus.FAILED_RUN if failed else RunStatus.UNKNOWN,
        sampling_rate_hz_nominal=1 / timebase.nominal_dt if timebase.nominal_dt else None,
        sampling_rate_hz_actual=rate,
        duration_s=timebase.duration_s,
        n_rows=timebase.rows,
        n_gaps=timebase.gaps,
        n_duplicate_ts=timebase.duplicates,
        raw_parquet_uri=raw_uri,
        schema_uri=schema_uri,
        recorded_at=header.started_at,
        channel_map_rule_id=next(iter(resolution.rule_ids.values()), None),
        channels=channels,
    )
    summary = (
        f"Run {label} ({inputs.name}), recorded {header.started_at:%Y-%m-%d %H:%M} local, "
        f"{rate:.0f} Hz, {timebase.duration_s:.1f} s, {timebase.rows} rows, {len(header.channels)} channels; "
        f"status {'FAILED_RUN' if failed else 'not yet classified'}; "
        f"{len(resolution.unresolved)} channels await unit confirmation."
        if header.started_at and rate and timebase.duration_s is not None
        else f"Run {label} ({inputs.name}), {timebase.rows} rows, {len(header.channels)} channels."
    )
    return ProcessedDocument(
        blob_sha256=inputs.blob_sha256,
        route=Route.C,
        parser_version=PARSER_VERSION,
        cir_uri=f"s3://dcl-cir/{prefix}/",
        document=DocumentFields(
            title=PurePosixPath(inputs.name).stem,
            doc_kind=DocKind.TELEMETRY_RUN,
            source_origin=inputs.context.source_origin,
            trust_tier=1,
            test_plan_id=inputs.context.test_plan_id,
            test_run_id=inputs.context.test_run_id,
            hardware_item=inputs.context.hardware_item,
            doc_date=header.started_at.date() if header.started_at else None,
            date_source="labjack header" if header.started_at else None,
            unit_count=len(header.channels),
        ),
        nodes=[
            ProcessedNode(
                ref="run",
                node_type=NodeType.RUN_SUMMARY,
                ordinal=0,
                breadcrumb=" › ".join(inputs.context.breadcrumb),
                content=summary,
                t_start_ms=0,
                source=NodeSource.STRUCTURED,
                metadata={"run_uuid": str(run_id)},
            )
        ],
        telemetry_runs=[record],
        flags=flags,
    )


def _raw_schema(header: LabJackHeader, run_id: uuid.UUID, label: str, sha: str) -> pa.Schema:
    base = pa.schema([pa.field(c, pa.float64()) for c in header.columns])
    field_meta = {header.time_column: {"raw_name": header.time_column, "raw_unit": "s"}}
    field_meta.update({c: {"raw_name": c, "raw_unit": "V" if is_voltage(c) else ""} for c in header.channels})
    file_meta = {
        "run_uuid": str(run_id),
        "run_label": label,
        "source_blob_sha256": sha,
        "parser_version": PARSER_VERSION,
    }
    return schema_with_metadata(base, field_meta, file_meta)


def _quantiles(path: Path, channels: Sequence[str]) -> dict[str, tuple[float | None, float | None]]:
    out = {}
    for channel in channels:
        column = pq.read_table(path, columns=[channel]).column(0)
        valid = pc.drop_null(pc.if_else(pc.is_nan(column), None, column))
        if len(valid) == 0:
            out[channel] = (None, None)
            continue
        q = pc.quantile(valid, q=[0.5, 0.99]).to_pylist()
        out[channel] = (q[0], q[1])
    return out


def _channel_record(channel: str, stats: ChannelStats, resolution: Resolution) -> TelemetryChannelRecord:
    if is_voltage(channel):
        quantity, unit, canonical, gauge = "voltage", "V", f"{channel}_v", GaugeOrAbs.NOT_APPLICABLE
    elif channel in resolution.mapped:
        entry = resolution.mapped[channel]
        quantity, unit, canonical, gauge = (
            entry.physical_quantity,
            entry.unit,
            entry.canonical_name,
            entry.gauge_or_abs,
        )
    else:
        quantity, unit, canonical, gauge = None, None, channel, GaugeOrAbs.UNKNOWN
    return TelemetryChannelRecord(
        canonical_name=canonical,
        raw_name=channel,
        raw_unit="V" if is_voltage(channel) else None,
        quantity=quantity,
        unit_si=unit,
        gauge_or_abs=gauge,
        stat_min=stats.min,
        stat_max=stats.max,
        stat_mean=stats.mean,
        stat_p50=stats.p50,
        stat_p99=stats.p99,
        stat_std=stats.std,
    )
