"""Route C normalization (file 03 §C.1 steps 3–7, §C.6): from ``raw.parquet`` and a resolved channel map
to ``normalized.parquet``, t0, sanity bounds and the three-tier metrics.

- Every channel becomes ``si = a * f(raw) + b`` where ``f`` is the rule's scaling (``slope``/``offset``)
  or expression over ``val``, and ``a``/``b`` convert the rule's unit to the canonical unit of its
  dimension (bar, N, K, g/s, W, else base SI). LabJack ``v*`` columns stay volts.
- A gauge pressure gets a separate absolute column (``*_bar_abs``) when the ambient is known; the gauge
  column is never overwritten. A pressure channel whose gauge/absolute is unknown is ``UNIT_AMBIGUITY``.
- ``t_rel_ms`` is milliseconds from the first sample (float, sub-millisecond kept); ``t_from_ignition_ms``
  is ``t_rel_ms - t0`` and null when no t0 was found.
- t0: the first time a pressure channel's slope stays above ``t0.pressure_slope_bar_s`` for 20 ms, else
  a ``valve_state`` rising edge, else a temperature slope; the edge sharpness is the confidence, and a
  weak edge is a SOFT ``CONFLICT``.
- Pressure and force channels get the instantaneous peak, the 50 ms rolling-mean peak, and the steady
  mean over the plateau window (valve open and ``t > t0 + 1 s``, else the longest low-slope window near
  the top after ``t0 + 1 s``); the window is stored so the answer can state it.
- Sanity bounds (S5's ``sanity_ranges``): a channel whose p99 (absolute value for pressure, when known)
  falls outside its range is ``UNIT_AMBIGUITY`` HARD.

Columns are read one at a time from Parquet, so a long run stays within the queue's memory limit.
"""

import ast
import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from backend.common.units import UnitError, ambient_bar_abs, parse_unit, to_canonical
from backend.postgres.enums import AmbientCondition, GaugeOrAbs, Quantity
from backend.review.rules import ChannelMapEntry
from backend.storage.parquet import schema_with_metadata, write_batches

PEAK_WINDOW_MS = 50.0
T0_SUSTAIN_MS = 20.0
T0_SMOOTH_MS = 5.0
STEADY_SMOOTH_MS = 100.0
STEADY_AFTER_T0_MS = 1000.0
STEADY_MIN_MS = 500.0
STEADY_NEAR_TOP = 0.5
SATURATION_SAMPLES = 20
DEFAULT_VALVE_OPEN = 0.5


@dataclass(frozen=True)
class NormalizeConfig:
    """``pipeline_config`` ``telemetry.*`` values with the manual's defaults."""

    t0_pressure_slope_bar_s: float = 10.0
    t0_temperature_slope_k_s: float = 50.0
    t0_weak_confidence: float = 0.5
    steady_max_slope_fraction_s: float = 0.05

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "NormalizeConfig":
        known = {k: float(v) for k, v in values.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class ExpressionError(ValueError):
    pass


_OPS: dict[type, Callable] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def compile_expression(expression: str) -> Callable[[np.ndarray], np.ndarray]:
    """A custom conversion over ``val`` (``val * 0.0689476 + 1.01325``): numbers, ``val``, + - * / ** only."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"cannot parse {expression!r}") from exc

    def check(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            check(node.body)
        elif isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            check(node.left)
            check(node.right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            check(node.operand)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | float)
            and not isinstance(node.value, bool)
        ):
            return
        elif isinstance(node, ast.Name) and node.id == "val":
            return
        else:
            raise ExpressionError(f"{expression!r}: only numbers, val and + - * / ** are allowed")

    check(tree)

    def evaluate(node: ast.AST, val: np.ndarray):
        if isinstance(node, ast.Expression):
            return evaluate(node.body, val)
        if isinstance(node, ast.BinOp):
            return _OPS[type(node.op)](evaluate(node.left, val), evaluate(node.right, val))
        if isinstance(node, ast.UnaryOp):
            return _OPS[type(node.op)](evaluate(node.operand, val))
        if isinstance(node, ast.Constant):
            return node.value
        return val

    return lambda values: np.asarray(evaluate(tree, values), dtype=np.float64) * np.ones_like(values)


# ---------------------------------------------------------------- channel plans


@dataclass(frozen=True)
class ChannelPlan:
    """How one raw column becomes one (or, for gauge pressure, two) normalized columns."""

    raw_name: str
    canonical_name: str
    quantity: Quantity
    unit_si: str
    gauge_or_abs: GaugeOrAbs
    raw_unit: str | None
    to_si_slope: float = 1.0
    to_si_offset: float = 0.0
    scaling_slope: float = 1.0
    scaling_offset: float = 0.0
    expression: str | None = None
    abs_column: str | None = None
    ambient_bar_abs: float | None = None
    sensor_tag: str | None = None
    range_min_si: float | None = None
    range_max_si: float | None = None
    rule_unit: str | None = None
    open_threshold: float | None = None

    def convert(self, raw: np.ndarray) -> np.ndarray:
        """SI values; a ``valve_state`` channel becomes 1 (open) / 0 (closed) at ``open_threshold``."""
        value = compile_expression(self.expression)(raw) if self.expression else raw * self.scaling_slope
        if not self.expression:
            value = value + self.scaling_offset
        if self.quantity == Quantity.VALVE_STATE:
            threshold = DEFAULT_VALVE_OPEN if self.open_threshold is None else self.open_threshold
            return np.where(np.isnan(value), np.nan, (value >= threshold).astype(np.float64))
        return value * self.to_si_slope + self.to_si_offset

    @property
    def conversion(self) -> dict[str, object]:
        """``telemetry_channels.conversion``: everything needed to reproduce the column from raw."""
        out: dict[str, object] = {"rule_unit": self.rule_unit, "to_si": [self.to_si_slope, self.to_si_offset]}
        if self.expression:
            out["expression"] = self.expression
        elif (self.scaling_slope, self.scaling_offset) != (1.0, 0.0):
            out["scaling"] = [self.scaling_slope, self.scaling_offset]
        if self.quantity == Quantity.VALVE_STATE:
            out["open_threshold"] = DEFAULT_VALVE_OPEN if self.open_threshold is None else self.open_threshold
        if self.abs_column:
            out["abs_column"] = self.abs_column
            out["ambient_bar_abs"] = self.ambient_bar_abs
        return out


def voltage_plan(raw_name: str) -> ChannelPlan:
    return ChannelPlan(
        raw_name=raw_name,
        canonical_name=f"{raw_name}_v",
        quantity=Quantity.VOLTAGE,
        unit_si="V",
        gauge_or_abs=GaugeOrAbs.NOT_APPLICABLE,
        raw_unit="V",
        rule_unit="V",
    )


def _abs_name(canonical: str) -> str:
    """``pt_101_bar_g`` → ``pt_101_bar_abs``; ``pt_g`` → ``pt_abs``; otherwise ``…_abs`` is appended."""
    for suffix, replacement in (("_bar_g", "_bar_abs"), ("_barg", "_bar_abs"), ("_g", "_abs")):
        if canonical.endswith(suffix):
            return canonical[: -len(suffix)] + replacement
    return f"{canonical}_abs"


@dataclass(frozen=True)
class PlanProblem:
    raw_name: str
    reason: str


def plan_channel(
    raw_name: str, entry: ChannelMapEntry, ambient: AmbientCondition | None, ambient_recorded: float | None
) -> ChannelPlan | PlanProblem:
    """The plan for a rule-mapped channel, or why it cannot be normalized (→ ``UNIT_AMBIGUITY``)."""
    try:
        parsed = parse_unit(entry.unit)
    except UnitError as exc:
        return PlanProblem(raw_name, str(exc))
    from backend.common.units import fits_quantity

    if not fits_quantity(parsed, entry.physical_quantity):
        return PlanProblem(raw_name, f"unit {entry.unit!r} does not measure {entry.physical_quantity}")
    zero, unit_si = to_canonical(0.0, parsed)
    one, _ = to_canonical(1.0, parsed)
    slope, offset = one - zero, zero
    gauge = entry.gauge_or_abs
    if (
        gauge in (GaugeOrAbs.UNKNOWN, GaugeOrAbs.NOT_APPLICABLE)
        and parsed.gauge_or_abs != GaugeOrAbs.NOT_APPLICABLE
    ):
        gauge = parsed.gauge_or_abs
    if entry.physical_quantity == Quantity.PRESSURE and gauge not in (GaugeOrAbs.GAUGE, GaugeOrAbs.ABSOLUTE):
        return PlanProblem(raw_name, "pressure without gauge/absolute")
    abs_column = ambient_value = None
    if gauge == GaugeOrAbs.GAUGE:
        try:
            ambient_value = ambient_bar_abs(ambient, ambient_recorded)
            abs_column = _abs_name(entry.canonical_name)
        except UnitError:
            ambient_value = None  # gauge only; the absolute column follows once the ambient is known
    scaling = entry.scaling
    return ChannelPlan(
        raw_name=raw_name,
        canonical_name=entry.canonical_name,
        quantity=entry.physical_quantity,
        unit_si=unit_si,
        gauge_or_abs=gauge,
        raw_unit=None,
        to_si_slope=slope,
        to_si_offset=offset,
        scaling_slope=scaling.slope if scaling else 1.0,
        scaling_offset=scaling.offset if scaling else 0.0,
        expression=entry.expression,
        abs_column=abs_column,
        ambient_bar_abs=ambient_value,
        sensor_tag=entry.sensor_tag,
        range_min_si=entry.range_min * slope + offset if entry.range_min is not None else None,
        range_max_si=entry.range_max * slope + offset if entry.range_max is not None else None,
        rule_unit=entry.unit,
        open_threshold=entry.open_threshold,
    )


# ---------------------------------------------------------------- t0 and windows


@dataclass(frozen=True)
class T0:
    t_ms: float
    method: str
    confidence: float
    channel: str


def _moving_mean(values: np.ndarray, samples: int) -> np.ndarray:
    if samples <= 1 or len(values) < samples:
        return values.astype(np.float64)
    clean = np.where(np.isnan(values), 0.0, values)
    kernel = np.ones(samples) / samples
    return np.convolve(clean, kernel, mode="same")


def _span_slope(smooth: np.ndarray, t_ms: np.ndarray, half: int) -> np.ndarray:
    """Slope per second across ``2 * half`` samples (robust against sample-to-sample noise)."""
    if half < 1 or len(smooth) <= 2 * half:
        return np.gradient(smooth, t_ms / 1000.0)
    slope = np.empty_like(smooth)
    rise = smooth[2 * half :] - smooth[: -2 * half]
    run = (t_ms[2 * half :] - t_ms[: -2 * half]) / 1000.0
    slope[half:-half] = rise / run
    slope[:half], slope[-half:] = slope[half], slope[-half - 1]
    return slope


def _samples(ms: float, dt_ms: float) -> int:
    return max(1, int(round(ms / dt_ms))) if dt_ms > 0 else 1


ONSET_FRACTION = 0.1  # coarse data: the rise starts where the slope first exceeds this share of the threshold


def _sustained_rise(t_ms: np.ndarray, x: np.ndarray, threshold_per_s: float) -> tuple[int, float] | None:
    """Index of the first sample whose smoothed slope stays above ``threshold`` for 20 ms (at least two
    samples), and the steepest slope in that window. On coarse data (20 ms shorter than two samples, e.g. a
    2 Hz logger) the index moves back to the first sample of the rise whose slope is still above
    ``ONSET_FRACTION * threshold``: t0 marks where the rise begins, not its steep part."""
    if len(x) < 3:
        return None
    dt_ms = float(np.median(np.diff(t_ms)))
    smooth = _moving_mean(x, _samples(T0_SMOOTH_MS, dt_ms))
    slope = np.gradient(smooth, t_ms / 1000.0)
    above = slope > threshold_per_s
    window = max(2, _samples(T0_SUSTAIN_MS, dt_ms))
    if window > len(above):
        return None
    runs = np.convolve(above.astype(np.int32), np.ones(window, dtype=np.int32), mode="valid")
    hits = np.flatnonzero(runs == window)
    if not len(hits):
        return None
    start = int(hits[0])
    peak = float(slope[start : start + window].max())
    if T0_SUSTAIN_MS < 2 * dt_ms:
        while start > 0 and slope[start - 1] > ONSET_FRACTION * threshold_per_s:
            start -= 1
    return start, peak


def detect_t0(
    t_ms: np.ndarray, channels: Mapping[str, tuple[ChannelPlan, np.ndarray]], config: NormalizeConfig
) -> T0 | None:
    """t0 per file 03 §C.6, in ``t_rel_ms``."""
    pressure = sorted(
        (name for name, (plan, _) in channels.items() if plan.quantity == Quantity.PRESSURE),
        key=lambda name: (0 if "chamber" in name else 1 if "feed" in name else 2, name),
    )
    best: T0 | None = None
    for name in pressure:
        found = _sustained_rise(t_ms, channels[name][1], config.t0_pressure_slope_bar_s)
        if found is None:
            continue
        index, peak_slope = found
        confidence = min(1.0, peak_slope / (5.0 * config.t0_pressure_slope_bar_s))
        candidate = T0(
            float(t_ms[index]),
            f"pressure slope > {config.t0_pressure_slope_bar_s:g} bar/s for 20 ms",
            confidence,
            name,
        )
        if best is None or candidate.t_ms < best.t_ms:
            best = candidate
    if best is not None:
        return best
    for name, (plan, values) in channels.items():
        if plan.quantity == Quantity.VALVE_STATE:
            edges = np.flatnonzero((values[:-1] < 0.5) & (values[1:] >= 0.5))
            if len(edges):
                return T0(float(t_ms[edges[0] + 1]), "valve_state rising edge", 1.0, name)
    for name, (plan, values) in sorted(channels.items()):
        if plan.quantity == Quantity.TEMPERATURE:
            found = _sustained_rise(t_ms, values, config.t0_temperature_slope_k_s)
            if found is not None:
                index, peak_slope = found
                confidence = min(1.0, peak_slope / (5.0 * config.t0_temperature_slope_k_s))
                return T0(
                    float(t_ms[index]),
                    f"temperature slope > {config.t0_temperature_slope_k_s:g} K/s for 20 ms",
                    confidence,
                    name,
                )
    return None


def _longest_true(mask: np.ndarray) -> tuple[int, int] | None:
    """``[start, end)`` of the longest run of True."""
    if not mask.any():
        return None
    padded = np.concatenate([[False], mask, [False]]).astype(np.int8)
    changes = np.flatnonzero(np.diff(padded))
    starts, ends = changes[0::2], changes[1::2]
    i = int(np.argmax(ends - starts))
    return int(starts[i]), int(ends[i])


@dataclass(frozen=True)
class Metrics:
    peak_raw: float | None = None
    peak_50ms: float | None = None
    steady_mean: float | None = None
    steady_window_ms: list[int] | None = None


def three_tier_metrics(
    t_ms: np.ndarray,
    x: np.ndarray,
    t0_ms: float | None,
    valve_open: np.ndarray | None,
    config: NormalizeConfig,
) -> Metrics:
    valid = ~np.isnan(x)
    if not valid.any():
        return Metrics()
    dt_ms = float(np.median(np.diff(t_ms))) if len(t_ms) > 1 else 1.0
    peak_raw = float(np.nanmax(x))
    rolling = _moving_mean(x, _samples(PEAK_WINDOW_MS, dt_ms))
    peak_50ms = float(np.nanmax(rolling)) if len(x) >= _samples(PEAK_WINDOW_MS, dt_ms) else peak_raw
    after = t_ms > (t0_ms + STEADY_AFTER_T0_MS) if t0_ms is not None else np.ones_like(valid)
    if valve_open is not None:
        candidate = after & valve_open & valid
    else:
        window = _samples(STEADY_SMOOTH_MS, dt_ms)
        smooth = _moving_mean(x, window)
        slope = np.abs(_span_slope(smooth, t_ms, window // 2))
        spread = float(np.nanpercentile(x, 99) - np.nanpercentile(x, 1)) or 1.0
        candidate = (
            after
            & valid
            & (slope < config.steady_max_slope_fraction_s * spread)
            & (smooth >= STEADY_NEAR_TOP * peak_50ms)
        )
    window = _longest_true(candidate)
    if window is None or (t_ms[window[1] - 1] - t_ms[window[0]]) < STEADY_MIN_MS:
        return Metrics(peak_raw=peak_raw, peak_50ms=peak_50ms)
    start, end = window
    return Metrics(
        peak_raw=peak_raw,
        peak_50ms=peak_50ms,
        steady_mean=float(np.nanmean(x[start:end])),
        steady_window_ms=[int(round(t_ms[start])), int(round(t_ms[end - 1]))],
    )


def is_saturated(x: np.ndarray, range_max: float | None) -> bool:
    """Flat top at the sensor's range limit (only when the range is known)."""
    if range_max is None or not len(x):
        return False
    at_limit = np.nan_to_num(x, nan=-np.inf) >= range_max * 0.999 if range_max > 0 else x >= range_max
    run = _longest_true(at_limit)
    return run is not None and run[1] - run[0] >= SATURATION_SAMPLES


# ---------------------------------------------------------------- sanity bounds


@dataclass(frozen=True)
class SanityRange:
    id: str
    quantity: str
    glob: str
    unit: str
    min: float
    max: float


def sanity_ranges_from(config: Mapping[str, object] | None) -> list[SanityRange]:
    ranges = []
    for item in (config or {}).get("ranges", []) or []:
        ranges.append(
            SanityRange(
                id=item["id"],
                quantity=item["physical_quantity"],
                glob=item.get("canonical_name_glob", "*"),
                unit=item["unit"],
                min=float(item["min"]),
                max=float(item["max"]),
            )
        )
    return ranges


def matching_range(ranges: Sequence[SanityRange], quantity: str, canonical_name: str) -> SanityRange | None:
    """S5's rule: the first range whose quantity equals and whose glob matches (case-insensitive)."""
    name = canonical_name.casefold()
    return next((r for r in ranges if r.quantity == quantity and fnmatchcase(name, r.glob.casefold())), None)


def in_bounds(value: float, sanity: SanityRange, unit_si: str) -> bool:
    low, _ = to_canonical(sanity.min, sanity.unit)
    high, _ = to_canonical(sanity.max, sanity.unit)
    return low <= value <= high


# ---------------------------------------------------------------- the normalized file


@dataclass
class ColumnResult:
    plan: ChannelPlan
    column: str
    n: int = 0
    nulls: int = 0
    stats: dict[str, float | None] = field(default_factory=dict)
    metrics: Metrics = field(default_factory=Metrics)
    saturated: bool = False


@dataclass
class NormalizedRun:
    rows: int
    t0: T0 | None
    columns: list[ColumnResult]


def _time_ms(raw: pa.Table, time_column: str) -> np.ndarray:
    t = raw.column(time_column).to_numpy()
    return (t - t[0]) * 1000.0 if len(t) else t


def normalize_run(
    raw_path: Path,
    time_column: str,
    plans: Sequence[ChannelPlan],
    out_path: Path,
    config: NormalizeConfig,
    file_metadata: Mapping[str, object],
) -> NormalizedRun:
    """Write ``normalized.parquet`` and return t0, per-column stats and metrics (all in SI)."""
    t_ms = _time_ms(pq.read_table(raw_path, columns=[time_column]), time_column)
    converted: dict[str, tuple[ChannelPlan, np.ndarray]] = {}
    for plan in plans:
        if plan.quantity in (Quantity.PRESSURE, Quantity.VALVE_STATE, Quantity.TEMPERATURE):
            raw = pq.read_table(raw_path, columns=[plan.raw_name]).column(0).to_numpy(zero_copy_only=False)
            converted[plan.canonical_name] = (plan, plan.convert(raw))
    t0 = detect_t0(t_ms, converted, config)
    del converted

    names = ["t_rel_ms", "t_from_ignition_ms"]
    field_meta: dict[str, dict[str, str]] = {
        "t_rel_ms": {"unit": "ms", "note": "from the first sample"},
        "t_from_ignition_ms": {"unit": "ms", "note": "null when no t0 was detected"},
    }
    for plan in plans:
        names.append(plan.canonical_name)
        field_meta[plan.canonical_name] = {
            "raw_name": plan.raw_name,
            "unit": plan.unit_si,
            "quantity": str(plan.quantity),
            "gauge_or_abs": str(plan.gauge_or_abs),
        }
        if plan.abs_column:
            names.append(plan.abs_column)
            field_meta[plan.abs_column] = {
                "raw_name": plan.raw_name,
                "unit": "bar",
                "quantity": str(Quantity.PRESSURE),
                "gauge_or_abs": str(GaugeOrAbs.ABSOLUTE),
                "ambient_bar_abs": str(plan.ambient_bar_abs),
            }
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"two channels map to {sorted(duplicates)}")
    schema = schema_with_metadata(
        pa.schema([pa.field(n, pa.float64()) for n in names]),
        field_meta,
        {**file_metadata, "t0_ignition_ms": t0.t_ms if t0 else None},
    )
    parquet = pq.ParquetFile(raw_path)
    offset = 0
    t0_ms = t0.t_ms if t0 else None

    def batches():
        nonlocal offset
        for batch in parquet.iter_batches(columns=[time_column, *[p.raw_name for p in plans]]):
            n = batch.num_rows
            t = t_ms[offset : offset + n]
            offset += n
            arrays = [
                pa.array(t),
                pa.array(t - t0_ms if t0_ms is not None else np.full(n, np.nan), from_pandas=True),
            ]
            for plan in plans:
                values = plan.convert(batch.column(plan.raw_name).to_numpy(zero_copy_only=False))
                arrays.append(pa.array(values, from_pandas=True))
                if plan.abs_column:
                    arrays.append(pa.array(values + plan.ambient_bar_abs, from_pandas=True))
            yield pa.RecordBatch.from_arrays(arrays, schema=schema)

    rows = write_batches(out_path, schema, batches())

    valve = next(
        (
            pq.read_table(out_path, columns=[p.canonical_name]).column(0).to_numpy(zero_copy_only=False)
            >= 0.5
            for p in plans
            if p.quantity == Quantity.VALVE_STATE
        ),
        None,
    )
    results: list[ColumnResult] = []
    for plan in plans:
        for column in [plan.canonical_name, *([plan.abs_column] if plan.abs_column else [])]:
            x = pq.read_table(out_path, columns=[column]).column(0).to_numpy(zero_copy_only=False)
            result = ColumnResult(plan=plan, column=column)
            valid = x[~np.isnan(x)]
            result.n, result.nulls = len(valid), len(x) - len(valid)
            if len(valid):
                result.stats = {
                    "min": float(valid.min()),
                    "max": float(valid.max()),
                    "mean": float(valid.mean()),
                    "std": float(valid.std()),
                    "p50": float(np.percentile(valid, 50)),
                    "p99": float(np.percentile(valid, 99)),
                }
            if plan.quantity in (Quantity.PRESSURE, Quantity.FORCE):
                result.metrics = three_tier_metrics(t_ms, x, t0_ms, valve, config)
            result.saturated = is_saturated(x, plan.range_max_si) if column == plan.canonical_name else False
            results.append(result)
    return NormalizedRun(rows=rows, t0=t0, columns=results)
