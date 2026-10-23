"""The Route C time-series path (file 03 §C.1 steps 2–9), shared by every time-series source: LabJack
``.dat``, LabVIEW ``.tdms``, time-series ``.csv`` and workbook islands. An adapter describes its file as a
``SeriesSource`` (header lines, columns with time first in seconds, the units the file states, Arrow
batches); this module does the rest.

The rows are streamed into ``dcl-telemetry/{run_uuid}/raw.parquet`` (original names and units).
Channel resolution follows C.1 step 2: an operator rule (``channel_map``, most specific scope that names
the channel), else the unit the file itself states (header cell, TDMS ``unit_string``; quantity from the
unit's dimension), else unresolved → HARD ``UNIT_AMBIGUITY`` with the header lines, the folder ``.cfg``
scaling, sibling-file units and the channel's stats as evidence. Once every channel resolves,
``normalize.py`` writes ``normalized.parquet``, checks the sanity bounds and computes t0 and the metrics.
"""

import json
import re
import tempfile
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from backend.common.units import QUANTITY_DIMENSIONS, UnitError, has_dimension, parse_unit
from backend.dispatcher.contract import (
    ChannelStats,
    ConflictEvidence,
    ConflictSide,
    DocumentFields,
    Flag,
    FlagAnchor,
    ProcessedDocument,
    ProcessedNode,
    SanityBounds,
    SiblingUnit,
    TelemetryChannelRecord,
    TelemetryRunRecord,
    UnitTelemetryEvidence,
)
from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import (
    AmbientCondition,
    DocKind,
    FlagSeverity,
    FlagType,
    GaugeOrAbs,
    NodeSource,
    NodeType,
    Quantity,
    Route,
    RuleType,
    RunStatus,
    TelemetrySourceFormat,
)
from backend.review.rules import (
    ChannelMapBody,
    ChannelMapEntry,
    RuleRecord,
    RuleTarget,
    parse_body,
    resolve_where,
)
from backend.routes.c_telemetry.ljstream_cfg import LJStreamConfig
from backend.routes.c_telemetry.normalize import (
    ChannelPlan,
    ColumnResult,
    NormalizeConfig,
    NormalizedRun,
    PlanProblem,
    SanityRange,
    in_bounds,
    matching_range,
    normalize_run,
    plan_channel,
    voltage_plan,
)
from backend.storage.minio import BucketStore
from backend.storage.parquet import schema_with_metadata, telemetry_key, write_batches

PARSER_VERSION = 1
RUN_NAMESPACE = uuid.UUID("8f0b5c3e-2a64-4f4e-9d2b-6b8d1a1d7c01")
GAP_FACTOR = 1.5


def run_uuid_for(blob_sha256: str, run_key: str = "") -> uuid.UUID:
    """Stable per content (and per island of a workbook): re-processing writes the same run directory."""
    return uuid.uuid5(RUN_NAMESPACE, f"{blob_sha256}#{run_key}" if run_key else blob_sha256)


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
class FolderConfig:
    """The folder's LJStreamM ``.cfg`` (file 03 §C.0), when there is one."""

    file_name: str
    config: LJStreamConfig


@dataclass(frozen=True)
class RunInputs:
    blob_sha256: str
    name: str
    context: FolderContext
    target: RuleTarget
    folder_config: FolderConfig | None = None
    run_key: str = ""  # several runs in one file (workbook islands): part of the run uuid and CIR path
    label_suffix: str = ""


@dataclass(frozen=True)
class SeriesSource:
    """One time series as an adapter read it. ``columns[0]`` is the time column in seconds; every column
    is float64 in the batches. ``units`` holds the unit text the file states per channel."""

    source_format: TelemetrySourceFormat
    header_lines: list[str]
    columns: list[str]
    open_batches: Callable[[], Iterator[pa.RecordBatch]]
    started_at: datetime | None = None
    started_at_note: str | None = None
    date_source: str | None = None
    units: Mapping[str, str] = field(default_factory=dict)
    unit_source: str = "header"
    voltage: frozenset[str] = frozenset()
    sibling_units: Sequence[SiblingUnit] = ()
    failed: bool = False
    title: str | None = None

    @property
    def time_column(self) -> str:
        return self.columns[0]

    @property
    def channels(self) -> list[str]:
        return self.columns[1:]


@dataclass
class Resolution:
    mapped: dict[str, ChannelMapEntry] = field(default_factory=dict)
    rule_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    bodies: dict[uuid.UUID, ChannelMapBody] = field(default_factory=dict)
    from_file: set[str] = field(default_factory=set)
    notes: dict[str, str] = field(default_factory=dict)

    def ambient(self) -> tuple[AmbientCondition, float | None]:
        """The run's ambient from the rules that mapped it (first one that states it)."""
        for rule_id in dict.fromkeys(self.rule_ids.values()):
            body = self.bodies[rule_id]
            if body.ambient_condition is not None or body.ambient_pressure_bar_abs is not None:
                condition = body.ambient_condition or AmbientCondition.AMBIENT_RECORDED
                return condition, body.ambient_pressure_bar_abs
        return AmbientCondition.UNKNOWN, None


QUANTITY_ORDER = [q for q in Quantity if QUANTITY_DIMENSIONS.get(q) and q not in (Quantity.RATIO,)]
SUFFIX = {
    Quantity.FORCE: "_n",
    Quantity.TEMPERATURE: "_k",
    Quantity.MASS_FLOW_RATE: "_g_s",
    Quantity.VOLTAGE: "_v",
    Quantity.POWER: "_w",
}
UNIT_IN_NAME = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]\s*$")


def slug(name: str) -> str:
    """``T1 - Upper Thermal Stdoff (°C)`` → ``t1_upper_thermal_stdoff``."""
    base = UNIT_IN_NAME.sub("", name).casefold()
    return re.sub(r"[^0-9a-z]+", "_", base).strip("_") or "channel"


def entry_from_unit(raw_name: str, unit_text: str) -> ChannelMapEntry | str:
    """A channel map entry from the unit the file states, or why there is none (C.1 step 2, "header")."""
    try:
        parsed = parse_unit(unit_text)
    except UnitError as exc:
        return f"stated unit {unit_text!r} is not a unit: {exc}"
    quantity = next((q for q in QUANTITY_ORDER if has_dimension(parsed, QUANTITY_DIMENSIONS[q])), None)
    if quantity is None:
        return f"stated unit {unit_text!r} measures no known quantity"
    if quantity == Quantity.PRESSURE:
        suffix = {GaugeOrAbs.GAUGE: "_bar_g", GaugeOrAbs.ABSOLUTE: "_bar_abs"}.get(
            parsed.gauge_or_abs, "_bar"
        )
    else:
        suffix = SUFFIX.get(quantity, "")
    return ChannelMapEntry(
        canonical_name=f"{slug(raw_name)}{suffix}",
        physical_quantity=quantity,
        unit=unit_text,
        gauge_or_abs=parsed.gauge_or_abs,
    )


def resolve_channels(
    channels: Sequence[str],
    rules: Sequence[RuleRecord],
    bodies: dict[uuid.UUID, dict],
    target: RuleTarget,
    units: Mapping[str, str] | None = None,
    voltage: frozenset[str] = frozenset(),
) -> Resolution:
    """C.1 step 2: operator rule → the unit the file states → unresolved. Voltage columns need neither."""
    resolution = Resolution()
    units = units or {}
    parsed = {rule_id: parse_body(RuleType.CHANNEL_MAP, body) for rule_id, body in bodies.items()}
    for channel in channels:
        if channel in voltage:
            continue
        rule = resolve_where(
            rules,
            target,
            RuleType.CHANNEL_MAP,
            lambda r, c=channel: c in getattr(parsed.get(r.rule_id), "channels", {}),
        )
        if rule is None:
            stated = units.get(channel, "").strip()
            entry = entry_from_unit(channel, stated) if stated else "the file states no unit"
            if isinstance(entry, ChannelMapEntry):
                resolution.mapped[channel] = entry
                resolution.from_file.add(channel)
            else:
                resolution.unresolved.append(channel)
                resolution.notes[channel] = entry
        else:
            resolution.mapped[channel] = parsed[rule.rule_id].channels[channel]
            resolution.rule_ids[channel] = rule.rule_id
            resolution.bodies[rule.rule_id] = parsed[rule.rule_id]
    used: set[str] = set()
    for channel, entry in list(resolution.mapped.items()):
        if channel in resolution.from_file and entry.canonical_name in used:
            resolution.mapped[channel] = entry.model_copy(
                update={"canonical_name": f"{entry.canonical_name}_{len(used)}"}
            )
        used.add(resolution.mapped[channel].canonical_name)
    return resolution


def _run_label(context: FolderContext, name: str) -> str:
    prefix = context.test_plan_id or context.hardware_item
    run = context.test_run_id
    if prefix and run:
        return f"{prefix}_{run}"
    return PurePosixPath(name).stem


def process_series(
    source: SeriesSource,
    inputs: RunInputs,
    rules: Sequence[RuleRecord],
    rule_bodies: dict[uuid.UUID, dict],
    telemetry: BucketStore,
    cir: BucketStore,
    normalize_config: NormalizeConfig | None = None,
    sanity: Sequence[SanityRange] = (),
    raw_parquet: Path | None = None,
) -> ProcessedDocument:
    header = source
    run_id = run_uuid_for(inputs.blob_sha256, inputs.run_key)
    label = _run_label(inputs.context, inputs.name) + inputs.label_suffix
    failed = source.failed
    resolution = resolve_channels(
        header.channels, rules, rule_bodies, inputs.target, source.units, source.voltage
    )

    raw_schema = _raw_schema(source, run_id, label, inputs.blob_sha256)
    running = {c: _Running() for c in header.channels}
    timebase = _TimeBase()

    def observe(batch: pa.RecordBatch) -> pa.RecordBatch:
        timebase.add(batch.column(0))
        for i, channel in enumerate(header.channels, start=1):
            running[channel].add(batch.column(i))
        return batch

    def batches():
        for batch in source.open_batches():
            yield observe(batch)

    with tempfile.TemporaryDirectory(prefix="dcl-route-c-") as workdir:
        if raw_parquet is None:
            path = Path(workdir) / "raw.parquet"
            write_batches(path, raw_schema, batches())
            raw_uri = telemetry.put_file(
                telemetry_key(str(run_id), "raw"), str(path), "application/vnd.apache.parquet"
            )
        else:  # resume: the run's own raw.parquet, the .dat is not parsed again (file 06 §1.6)
            path = raw_parquet
            for batch in pq.ParquetFile(path).iter_batches(columns=header.columns):
                observe(batch)
            raw_uri = f"s3://{telemetry.bucket}/{telemetry_key(str(run_id), 'raw')}"
        quantiles = _quantiles(path, header.channels)
        previews = raw_preview(path, header.columns)
        outcome = (
            _normalize(
                path,
                Path(workdir) / "normalized.parquet",
                header,
                resolution,
                {"run_uuid": str(run_id), "run_label": label, "source_blob_sha256": inputs.blob_sha256},
                source.voltage,
                normalize_config or NormalizeConfig(),
                sanity,
            )
            if not resolution.unresolved
            else _Outcome()
        )
        if outcome.clean:
            outcome.uri = telemetry.put_file(
                telemetry_key(str(run_id), "normalized"),
                str(Path(workdir) / "normalized.parquet"),
                "application/vnd.apache.parquet",
            )

    stats = {c: running[c].stats(*quantiles[c]) for c in header.channels}
    base = f"{inputs.blob_sha256}/{Route.C}/v{PARSER_VERSION}"
    prefix = f"{base}/{slug(inputs.run_key)}" if inputs.run_key else base
    schema_doc = {
        "header_lines": header.header_lines,
        "columns": header.columns,
        "source_format": str(source.source_format),
        "unit_source": source.unit_source,
        "date_source": source.date_source,
        "failed": source.failed,
        "title": source.title,
        "time_column": {"name": header.time_column, "unit": "s"},
        "started_at": header.started_at.isoformat() if header.started_at else None,
        "started_at_note": source.started_at_note,
        "stated_units": dict(source.units),
        "folder_config": (
            {
                "file": inputs.folder_config.file_name,
                "scan_rate_hz": inputs.folder_config.config.scan_rate_hz,
                "scaling_disabled": inputs.folder_config.config.scaling_disabled,
                "equations": inputs.folder_config.config.equations,
            }
            if inputs.folder_config
            else None
        ),
        "channels": {
            c: (
                {"quantity": "voltage", "unit": "V", "source": "voltage column"}
                if c in source.voltage
                else {
                    **resolution.mapped[c].model_dump(mode="json", exclude_none=True),
                    "source": source.unit_source if c in resolution.from_file else "rule",
                }
                if c in resolution.mapped
                else {"unresolved": True, "note": resolution.notes.get(c)}
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

    channels = (
        [_normalized_record(r) for r in outcome.run.columns]
        if outcome.clean
        else [_channel_record(c, stats[c], resolution, source) for c in header.channels]
    )
    flags = [
        Flag(
            flag_type=FlagType.UNIT_AMBIGUITY,
            severity=FlagSeverity.HARD,
            anchor=FlagAnchor(channel=c),
            evidence=UnitTelemetryEvidence(
                channel=c,
                raw_unit=source.units.get(c) or None,
                header_lines=header.header_lines,
                scaling_equation=_equation(inputs.folder_config, c),
                scaling_source=inputs.folder_config.file_name if _equation(inputs.folder_config, c) else None,
                stats=stats[c],
                sibling_units=list(source.sibling_units),
                note=resolution.notes.get(c, ""),
            ),
        )
        for c in resolution.unresolved
    ]
    flags += [_with_header(f, header.header_lines, inputs.folder_config) for f in outcome.flags]
    flags = [with_preview(f, previews) for f in flags]
    ambient, ambient_value = resolution.ambient()
    t0 = outcome.run.t0 if outcome.clean else None
    rate = timebase.actual_rate_hz
    record = TelemetryRunRecord(
        run_uuid=run_id,
        run_label=label,
        source_format=source.source_format,
        run_status=RunStatus.FAILED_RUN if failed else RunStatus.UNKNOWN,
        sampling_rate_hz_nominal=1 / timebase.nominal_dt if timebase.nominal_dt else None,
        sampling_rate_hz_actual=rate,
        duration_s=timebase.duration_s,
        n_rows=timebase.rows,
        n_gaps=timebase.gaps,
        n_duplicate_ts=timebase.duplicates,
        raw_parquet_uri=raw_uri,
        normalized_parquet_uri=outcome.uri,
        schema_uri=schema_uri,
        ambient_condition=ambient,
        ambient_pressure_bar_abs=ambient_value,
        t0_ignition_ms=int(round(t0.t_ms)) if t0 else None,
        t0_method=t0.method if t0 else None,
        t0_confidence=t0.confidence if t0 else None,
        recorded_at=header.started_at,
        channel_map_rule_id=next(iter(resolution.rule_ids.values()), None),
        channels=channels,
    )
    summary = _summary(label, inputs.name, source, timebase, failed, resolution, outcome)
    return ProcessedDocument(
        blob_sha256=inputs.blob_sha256,
        route=Route.C,
        parser_version=PARSER_VERSION,
        cir_uri=f"s3://dcl-cir/{base}/",
        document=DocumentFields(
            title=source.title or PurePosixPath(inputs.name).stem,
            doc_kind=DocKind.TELEMETRY_RUN,
            source_origin=inputs.context.source_origin,
            trust_tier=1,
            test_plan_id=inputs.context.test_plan_id,
            test_run_id=inputs.context.test_run_id,
            hardware_item=inputs.context.hardware_item,
            doc_date=header.started_at.date() if header.started_at else None,
            date_source=source.date_source if header.started_at else None,
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


@dataclass
class _Outcome:
    """Normalization result: the run when it went through, and the flags it raised."""

    run: NormalizedRun | None = None
    flags: list[Flag] = field(default_factory=list)
    uri: str | None = None

    @property
    def clean(self) -> bool:
        return self.run is not None and not any(f.severity == FlagSeverity.HARD for f in self.flags)


def _unit_flag(channel: str, stats: ChannelStats, note: str, sanity: SanityBounds | None = None) -> Flag:
    return Flag(
        flag_type=FlagType.UNIT_AMBIGUITY,
        severity=FlagSeverity.HARD,
        anchor=FlagAnchor(channel=channel),
        evidence=UnitTelemetryEvidence(channel=channel, stats=stats, note=note, sanity=sanity),
    )


def _with_header(flag: Flag, header_lines: list[str], folder_config: FolderConfig | None) -> Flag:
    evidence = flag.evidence
    if not isinstance(evidence, UnitTelemetryEvidence):
        return flag
    equation = _equation(folder_config, evidence.channel)
    return flag.model_copy(
        update={
            "evidence": evidence.model_copy(
                update={
                    "header_lines": header_lines,
                    "scaling_equation": equation,
                    "scaling_source": folder_config.file_name if equation else None,
                }
            )
        }
    )


def _normalize(
    raw_path: Path,
    out_path: Path,
    header: SeriesSource,
    resolution: Resolution,
    file_metadata: dict[str, object],
    voltage: frozenset[str],
    config: NormalizeConfig,
    sanity: Sequence[SanityRange],
) -> _Outcome:
    ambient, recorded = resolution.ambient()
    plans: list[ChannelPlan] = []
    outcome = _Outcome()
    for channel in header.channels:
        if channel in voltage:
            plans.append(voltage_plan(channel))
            continue
        plan = plan_channel(channel, resolution.mapped[channel], ambient, recorded)
        if isinstance(plan, PlanProblem):
            outcome.flags.append(_unit_flag(channel, ChannelStats(), plan.reason))
        else:
            plans.append(plan)
    if outcome.flags:
        return outcome
    outcome.run = normalize_run(raw_path, header.time_column, plans, out_path, config, file_metadata)
    by_column = {r.column: r for r in outcome.run.columns}
    for plan in plans:
        if plan.quantity == "voltage":
            continue
        bounds = matching_range(sanity, plan.quantity, plan.canonical_name)
        checked = by_column.get(plan.abs_column or plan.canonical_name) or by_column[plan.canonical_name]
        p99 = checked.stats.get("p99")
        if bounds is None or p99 is None or in_bounds(p99, bounds, plan.unit_si):
            continue
        outcome.flags.append(
            _unit_flag(
                plan.raw_name,
                _stats(checked),
                f"p99 {p99:.4g} {checked.plan.unit_si if checked.column == plan.canonical_name else 'bar'} "
                f"of {checked.column} is outside the {bounds.id} range after conversion",
                SanityBounds(quantity=bounds.quantity, unit=bounds.unit, min=bounds.min, max=bounds.max),
            )
        )
    t0 = outcome.run.t0
    if t0 is not None and t0.confidence < config.t0_weak_confidence:
        raw_name = next((p.raw_name for p in plans if p.canonical_name == t0.channel), t0.channel)
        outcome.flags.append(
            Flag(
                flag_type=FlagType.CONFLICT,
                severity=FlagSeverity.SOFT,
                anchor=FlagAnchor(channel=raw_name),
                evidence=ConflictEvidence(
                    subject=f"t0 alignment for {t0.channel}",
                    a=ConflictSide(
                        label="detected",
                        value=f"t0 at {t0.t_ms:.0f} ms, confidence {t0.confidence:.2f}",
                        provenance=t0.method,
                    ),
                    b=ConflictSide(
                        label="expected",
                        value=f"a sharp edge (confidence >= {config.t0_weak_confidence:g})",
                        provenance="file 03 §C.6",
                    ),
                ),
            )
        )
    return outcome


def _stats(result: ColumnResult) -> ChannelStats:
    return ChannelStats(n=result.n, **result.stats)


def _normalized_record(result: ColumnResult) -> TelemetryChannelRecord:
    plan = result.plan
    absolute = result.column != plan.canonical_name
    metrics = result.metrics
    total = result.n + result.nulls
    return TelemetryChannelRecord(
        canonical_name=result.column,
        raw_name=plan.raw_name,
        raw_unit=plan.raw_unit or plan.rule_unit,
        quantity=str(plan.quantity),
        unit_si="bar" if absolute else plan.unit_si,
        gauge_or_abs=GaugeOrAbs.ABSOLUTE if absolute else plan.gauge_or_abs,
        conversion=plan.conversion,
        sensor_tag=plan.sensor_tag,
        range_min=plan.range_min_si,
        range_max=plan.range_max_si,
        stat_min=result.stats.get("min"),
        stat_max=result.stats.get("max"),
        stat_mean=result.stats.get("mean"),
        stat_p50=result.stats.get("p50"),
        stat_p99=result.stats.get("p99"),
        stat_std=result.stats.get("std"),
        peak_raw=metrics.peak_raw,
        peak_50ms=metrics.peak_50ms,
        steady_mean=metrics.steady_mean,
        steady_window_ms=metrics.steady_window_ms,
        saturated=result.saturated,
        null_fraction=result.nulls / total if total else None,
    )


def _summary(
    label: str,
    name: str,
    header: SeriesSource,
    timebase: "_TimeBase",
    failed: bool,
    resolution: Resolution,
    outcome: _Outcome,
) -> str:
    """The run summary node (file 03 §C.7): what a semantic question needs to reach this run."""
    parts = [f"Run {label} ({name})"]
    if header.started_at:
        parts.append(f"recorded {header.started_at:%Y-%m-%d %H:%M} local")
    if timebase.actual_rate_hz:
        parts.append(f"{timebase.actual_rate_hz:.0f} Hz")
    if timebase.duration_s is not None:
        parts.append(f"{timebase.duration_s:.1f} s")
    parts.append(f"{timebase.rows} rows")
    text = ", ".join(parts)
    if outcome.clean:
        described = []
        for result in outcome.run.columns:
            if result.plan.quantity == "voltage":
                continue
            unit = "bar abs" if result.column != result.plan.canonical_name else result.plan.unit_si
            bits = [unit]
            if result.metrics.peak_50ms is not None:
                bits.append(f"peak {result.metrics.peak_50ms:.4g}")
            elif result.stats.get("max") is not None:
                bits.append(f"max {result.stats['max']:.4g}")
            if result.metrics.steady_mean is not None:
                bits.append(f"steady {result.metrics.steady_mean:.4g}")
            described.append(f"{result.column} {result.plan.quantity} ({', '.join(bits)})")
        voltages = sum(1 for r in outcome.run.columns if r.plan.quantity == "voltage")
        text += f"; channels: {'; '.join(described) or 'none mapped'}; {voltages} raw voltage channels"
        t0 = outcome.run.t0
        text += f"; t0 at {t0.t_ms / 1000:.2f} s" if t0 else "; no ignition edge detected"
    else:
        waiting = len(resolution.unresolved) + sum(
            1 for f in outcome.flags if f.flag_type == FlagType.UNIT_AMBIGUITY
        )
        text += f", {len(header.channels)} channels; {waiting} channels await unit confirmation"
    status = "FAILED_RUN" if failed else "not yet classified"
    return f"{text}; status {status}."


def _equation(folder_config: FolderConfig | None, channel: str) -> str | None:
    return folder_config.config.equations.get(channel) if folder_config else None


def _raw_schema(source: SeriesSource, run_id: uuid.UUID, label: str, sha: str) -> pa.Schema:
    base = pa.schema([pa.field(c, pa.float64()) for c in source.columns])
    field_meta = {source.time_column: {"raw_name": source.time_column, "raw_unit": "s"}}
    field_meta.update(
        {
            c: {"raw_name": c, "raw_unit": "V" if c in source.voltage else source.units.get(c, "")}
            for c in source.channels
        }
    )
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


def _channel_record(
    channel: str, stats: ChannelStats, resolution: Resolution, source: SeriesSource
) -> TelemetryChannelRecord:
    if channel in source.voltage:
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
        raw_unit="V" if channel in source.voltage else source.units.get(channel) or None,
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


def source_from_schema(schema: Mapping, name: str) -> SeriesSource:
    """The ``SeriesSource`` of a processed run, rebuilt from its ``schema.json`` (resume: the rows come from
    the run's own ``raw.parquet``, the original file is not read). Schemas written before the generic path
    (LabJack, step 1) have no ``source_format``; they are LabJack runs."""
    columns = list(schema["columns"])
    channels = schema.get("channels", {})
    fmt = schema.get("source_format")
    if fmt is None:
        voltage = frozenset(c for c in columns[1:] if re.fullmatch(r"v\d+", c))
        failed = name.casefold().endswith(".dat_fail")
        fmt = TelemetrySourceFormat.LABJACK_DAT
    else:
        voltage = frozenset(c for c, v in channels.items() if v.get("source") == "voltage column")
        failed = bool(schema.get("failed"))
    started = schema.get("started_at")

    def no_batches() -> Iterator[pa.RecordBatch]:
        raise RuntimeError("a resumed run reads its raw.parquet")

    return SeriesSource(
        source_format=TelemetrySourceFormat(fmt),
        header_lines=list(schema.get("header_lines") or []),
        columns=columns,
        open_batches=no_batches,
        started_at=datetime.fromisoformat(started) if started else None,
        started_at_note=schema.get("started_at_note") or schema.get("started_at_zone"),
        date_source=schema.get("date_source")
        or ("labjack header" if fmt == TelemetrySourceFormat.LABJACK_DAT else None),
        units=dict(schema.get("stated_units") or {}),
        unit_source=schema.get("unit_source") or "header",
        voltage=voltage,
        failed=failed,
        title=schema.get("title"),
    )


# ---------------------------------------------------------------- evidence preview (Review UI)

SAMPLE_ROWS = 20
SERIES_POINTS = 200


def _cell(value) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return None if value != value else float(f"{value:.6g}")
    if isinstance(value, int):
        return value
    return str(value)[:64]


def raw_preview(path: Path, columns: Sequence[str]) -> dict:
    """What the Review UI draws for a channel flag: the first rows of the file as parsed and about
    ``SERIES_POINTS`` evenly spaced ``[t_rel_s, value]`` points per channel, streamed from raw.parquet."""
    parquet = pq.ParquetFile(path)
    names = [c for c in columns if c in parquet.schema_arrow.names]
    total = parquet.metadata.num_rows
    wanted = (
        sorted({round(i * (total - 1) / (SERIES_POINTS - 1)) for i in range(SERIES_POINTS)}) if total else []
    )
    rows: list[list] = []
    picked: dict[str, list] = {c: [] for c in names}
    start, cursor = 0, 0
    for batch in parquet.iter_batches(columns=names, batch_size=65_536):
        data = {c: batch.column(i).to_pylist() for i, c in enumerate(names)}
        if len(rows) < SAMPLE_ROWS:
            for j in range(min(SAMPLE_ROWS - len(rows), batch.num_rows)):
                rows.append([_cell(data[c][j]) for c in names])
        end = start + batch.num_rows
        while cursor < len(wanted) and wanted[cursor] < end:
            j = wanted[cursor] - start
            for c in names:
                picked[c].append(data[c][j])
            cursor += 1
        start = end
    time_column = names[0] if names else None
    t0 = next((t for t in picked.get(time_column, []) if t is not None), 0.0) if time_column else 0.0
    times = [None if t is None else float(f"{t - t0:.6g}") for t in picked.get(time_column, [])]
    series = {
        c: [
            (t, _cell(v) if not isinstance(_cell(v), str) else None)
            for t, v in zip(times, picked[c], strict=True)
            if t is not None
        ]
        for c in names[1:]
    }
    return {"columns": names, "rows": rows, "time_column": time_column, "series": series}


def with_preview(flag: Flag, preview: dict) -> Flag:
    """The flag with the preview of its channel, when it is a telemetry unit flag on a column of the file."""
    evidence = flag.evidence
    channel = flag.anchor.channel
    if not isinstance(evidence, UnitTelemetryEvidence) or channel not in preview.get("series", {}):
        return flag
    update = {
        "columns": preview["columns"],
        "column_index": preview["columns"].index(channel),
        "sample_rows": preview["rows"],
        "time_column": preview["time_column"],
        "series": preview["series"][channel],
    }
    return flag.model_copy(update={"evidence": evidence.model_copy(update=update)})
