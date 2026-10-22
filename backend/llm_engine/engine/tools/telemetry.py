"""T2 `query_telemetry` (file 07 §4): deterministic numbers from `normalized.parquet`.

1. Runs come from `telemetry_runs` joined to `documents` (run labels, or a test plan with optional run ids). A
   requested run whose document is HALTED has no catalog rows; it is reported with its open HARD review case
   keys instead of being skipped silently.
2. A semantic channel (`chamber_pressure`, …) resolves to the run's `telemetry_channels.canonical_name`s by
   physical quantity and the role globs of `config/sanity_ranges.yaml`; a run without one says so. A pressure
   channel is returned as stored (gauge and, when the ambient is known, its absolute twin).
3. SQL is built from one template: column names come only from `telemetry_channels` (checked against
   `[a-z0-9_]+` and quoted), every value is a bound parameter, and all (run, channel) pairs are one
   `UNION ALL` statement. DuckDB reads the Parquet URI as stored (`s3://` through httpfs in the stack).
4. Every number is written once with its unit, gauge/absolute, the exact window, t0 method, sampling rate,
   rows in the window and the Parquet URI.

The 50 ms peak reproduces Route C's metric exactly: a centred moving sum over round(50 ms / median dt)
samples divided by that count (missing samples count as zero), the maximum over the window. Windows: the whole
run; the stored steady window per channel; the longest valve-open pulse of the run's `valve_state` channel;
or a user window on `t_from_ignition_ms`. `steady_mean` is the stored steady window's mean for a whole-run
query and the window mean otherwise.
"""

import math
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import ARRAY, Text, bindparam, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from backend.indexing.anchors import NodeView, make_anchor
from backend.indexing.retrieval import NODE_COLUMNS, VISIBLE_STATUSES
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult
from backend.postgres.enums import AmbientCondition, NodeType, Quantity

NAME = "query_telemetry"
DESCRIPTION = "Compute telemetry metrics (peaks, means, durations) of test runs from the measured data."
PEAK_WINDOW_MS = 50.0
MAX_RUNS = 12
COLUMN = re.compile(r"[a-z0-9_]+")
SemanticChannel = Literal["chamber_pressure", "thrust", "bed_temperature", "mass_flow", "heater_power"]
Metric = Literal[
    "peak_raw",
    "peak_50ms",
    "steady_mean",
    "max",
    "min",
    "mean",
    "p99",
    "duration",
    "time_to_peak",
    "value_at_t",
    "window_stats",
]
WindowKind = Literal["run", "steady", "valve_open", "custom"]
ROLES: dict[str, tuple[Quantity, tuple[str, ...]]] = {
    "chamber_pressure": (Quantity.PRESSURE, ("*chamber*", "pc", "pc_*", "*_pc_*")),
    "thrust": (Quantity.FORCE, ("*",)),
    "bed_temperature": (Quantity.TEMPERATURE, ("*bed*", "*cat*")),
    "mass_flow": (Quantity.MASS_FLOW_RATE, ("*",)),
    "heater_power": (Quantity.POWER, ("*",)),
}
UNIT_LABEL = {"gauge": " g", "absolute": " abs"}


class TelemetryWindow(BaseModel):
    t_from_ignition_ms_start: float | None = None
    t_from_ignition_ms_end: float | None = None


class QueryTelemetryArgs(BaseModel):
    run_ids: list[str] = Field(default=[], description="run labels, e.g. TP07_T04")
    test_plan_id: str | None = None
    test_run_ids: list[str] = Field(default=[], description="run selector within the test plan, e.g. T04")
    channels: list[SemanticChannel] = Field(min_length=1)
    metrics: list[Metric] = ["peak_raw", "peak_50ms", "steady_mean"]
    window_kind: WindowKind = "run"
    window: TelemetryWindow | None = None
    at_t_from_ignition_ms: float | None = Field(default=None, description="time of value_at_t")
    compare_runs: bool = False
    plot: bool = False

    @model_validator(mode="after")
    def _custom_window(self) -> "QueryTelemetryArgs":
        if self.window is not None:
            self.window_kind = "custom"
        return self


class TelemetryRequest(BaseModel):
    """What the question asks (`telemetry_args.v1`); the run ids come from the query analysis."""

    channels: list[SemanticChannel] = []
    metrics: list[Metric] = []
    window_kind: WindowKind = "run"
    window: TelemetryWindow | None = None
    at_t_from_ignition_ms: float | None = None
    compare_runs: bool = False
    plot: bool = False


def args_for(
    request: TelemetryRequest, test_plan_ids: list[str], test_run_ids: list[str]
) -> QueryTelemetryArgs | None:
    """None when the question names no measured quantity or no test plan (runs are only unique per plan)."""
    if not request.channels or not test_plan_ids:
        return None
    values = request.model_dump(exclude_none=True)
    if not values.get("metrics"):
        values.pop("metrics", None)
    return QueryTelemetryArgs(test_plan_id=test_plan_ids[0], test_run_ids=test_run_ids, **values)


@dataclass
class Run:
    run_uuid: uuid.UUID
    run_label: str
    doc_id: uuid.UUID
    title: str | None
    uri: str | None
    ambient: str
    rate_hz: float | None
    duration_s: float | None
    n_rows: int | None
    t0_ms: float | None
    t0_method: str | None
    channels: list[Any] = field(default_factory=list)
    anchor: str | None = None


@dataclass
class Pair:
    key: int
    run: Run
    asked: str
    channel: Any
    lo: float | None
    hi: float | None
    window_text: str
    steady: tuple[float, float] | None
    rolling_n: int = 1
    at_rel: float | None = None


def _runs(session: Session, args: QueryTelemetryArgs) -> list[Run]:
    statement = text(
        "SELECT r.run_uuid, r.run_label, r.doc_id, d.title, r.normalized_parquet_uri AS uri, "
        "r.ambient_condition AS ambient, "
        "coalesce(r.sampling_rate_hz_actual, r.sampling_rate_hz_nominal) AS rate, "
        "r.duration_s, r.n_rows, r.t0_ignition_ms AS t0, r.t0_method "
        "FROM telemetry_runs r JOIN documents d ON d.doc_id = r.doc_id "
        "WHERE d.status = ANY(:statuses) AND (r.run_label = ANY(:labels) OR (CAST(:plan AS text) IS NOT NULL "
        "AND d.test_plan_id = :plan AND (cardinality(:runs) = 0 OR d.test_run_id = ANY(:runs)))) "
        "ORDER BY r.run_label LIMIT :limit"
    ).bindparams(
        bindparam("statuses", type_=ARRAY(Text)),
        bindparam("labels", type_=ARRAY(Text)),
        bindparam("runs", type_=ARRAY(Text)),
    )
    rows = session.execute(
        statement,
        {
            "statuses": [str(s) for s in VISIBLE_STATUSES],
            "labels": args.run_ids,
            "plan": args.test_plan_id,
            "runs": args.test_run_ids,
            "limit": MAX_RUNS + 1,
        },
    )
    runs = [
        Run(
            run_uuid=r.run_uuid,
            run_label=r.run_label,
            doc_id=r.doc_id,
            title=r.title,
            uri=r.uri,
            ambient=r.ambient,
            rate_hz=r.rate,
            duration_s=r.duration_s,
            n_rows=r.n_rows,
            t0_ms=float(r.t0) if r.t0 is not None else None,
            t0_method=r.t0_method,
        )
        for r in rows
    ]
    if not runs:
        return runs
    channels = session.execute(
        text(
            "SELECT * FROM telemetry_channels WHERE run_uuid = ANY(:ids) ORDER BY canonical_name"
        ).bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True)))),
        {"ids": [r.run_uuid for r in runs]},
    )
    by_run: dict[uuid.UUID, list] = {}
    for channel in channels:
        by_run.setdefault(channel.run_uuid, []).append(channel)
    summaries = session.execute(
        text(
            f"SELECT {NODE_COLUMNS} FROM document_nodes WHERE doc_id = ANY(:docs) AND node_type = :t "  # noqa: S608
            "ORDER BY ordinal"
        ).bindparams(bindparam("docs", type_=ARRAY(UUID(as_uuid=True)))),
        {"docs": [r.doc_id for r in runs], "t": str(NodeType.RUN_SUMMARY)},
    )
    anchors: dict[uuid.UUID, str] = {}
    for node in summaries:
        anchors.setdefault(node.doc_id, make_anchor(node.doc_id, NodeView.from_row(node)).serialize())
    for run in runs:
        run.channels = by_run.get(run.run_uuid, [])
        run.anchor = anchors.get(run.doc_id)
    return runs


def _halted(session: Session, args: QueryTelemetryArgs, found: set[str]) -> list[str]:
    """Requested runs whose telemetry document is HALTED, with their open HARD review cases."""
    statement = text(
        "SELECT d.title, d.test_plan_id, d.test_run_id, "
        "(SELECT array_agg(DISTINCT f.case_key) FROM review_flags f WHERE f.doc_id = d.doc_id "
        " AND f.status = 'OPEN' AND f.severity = 'HARD') AS case_keys "
        "FROM documents d WHERE d.route = 'C' AND d.status = 'HALTED' AND ("
        " (d.test_plan_id || '_' || d.test_run_id) = ANY(:labels) OR (CAST(:plan AS text) IS NOT NULL "
        " AND d.test_plan_id = :plan AND (cardinality(:runs) = 0 OR d.test_run_id = ANY(:runs)))) "
        "ORDER BY d.title"
    ).bindparams(bindparam("labels", type_=ARRAY(Text)), bindparam("runs", type_=ARRAY(Text)))
    rows = session.execute(
        statement, {"labels": args.run_ids, "plan": args.test_plan_id, "runs": args.test_run_ids}
    )
    out = []
    for row in rows:
        label = f"{row.test_plan_id}_{row.test_run_id}" if row.test_plan_id and row.test_run_id else row.title
        if label in found:
            continue
        cases = ", ".join(row.case_keys or []) or "no open case key"
        out.append(f"run {label} ({row.title}) is halted for review ({cases}); its telemetry is not answered")
    return out


def channels_for(run: Run, asked: str) -> list[Any]:
    quantity, globs = ROLES[asked]
    return [
        c
        for c in run.channels
        if c.quantity == quantity and any(fnmatchcase(c.canonical_name.casefold(), g) for g in globs)
    ]


def _column(name: str) -> str:
    if not COLUMN.fullmatch(name):
        raise ValueError(f"unexpected column name {name!r} in telemetry_channels")
    return f'"{name}"'


def _valve_column(run: Run) -> str | None:
    return next((c.canonical_name for c in run.channels if c.quantity == Quantity.VALVE_STATE), None)


def valve_pulses(con, run: Run) -> list[tuple[float, float]]:
    """(first, last) t_rel_ms of every valve-open pulse, longest first (gaps and islands)."""
    valve = _column(_valve_column(run))
    rows = con.execute(
        "SELECT min(t_rel_ms), max(t_rel_ms) FROM ("  # noqa: S608 — quoted catalog column, bound values
        f" SELECT t_rel_ms, {valve} >= 0.5 AS open, row_number() OVER (ORDER BY t_rel_ms)"
        f" - row_number() OVER (PARTITION BY {valve} >= 0.5 ORDER BY t_rel_ms) AS grp"
        " FROM read_parquet(?)) WHERE open GROUP BY grp ORDER BY max(t_rel_ms) - min(t_rel_ms) DESC",
        [run.uri],
    ).fetchall()
    return [(float(a), float(b)) for a, b in rows]


def median_dt_ms(con, run: Run) -> float:
    (dt,) = con.execute(
        "SELECT median(d) FROM (SELECT t_rel_ms - lag(t_rel_ms) OVER (ORDER BY t_rel_ms) AS d "
        "FROM read_parquet(?))",
        [run.uri],
    ).fetchone()
    return float(dt) if dt else 1.0


def _ms(value: float) -> str:
    return f"{value / 1000:.3f} s"


def _window(
    con, run: Run, channel, args: QueryTelemetryArgs, warnings: list[str]
) -> tuple[float | None, float | None, str] | None:
    """(lo, hi) in t_rel_ms (None = open) and how the answer names the window; None when it cannot exist."""
    t0 = run.t0_ms
    rel = (lambda t: f"t0{'+' if t - t0 >= 0 else '−'}{_ms(abs(t - t0))}") if t0 is not None else _ms

    def named(lo: float, hi: float, what: str) -> str:
        origin = "t_from_ignition" if t0 is not None else "t_rel (no t0 found)"
        return f"{what} {rel(lo)} … {rel(hi)} ({origin})"

    if args.window_kind == "run":
        return None, None, "whole run"
    if args.window_kind == "steady":
        if not channel.steady_window_ms:
            warnings.append(f"run {run.run_label}: {channel.canonical_name} has no steady plateau")
            return None
        lo, hi = (float(v) for v in channel.steady_window_ms)
        return lo, hi, named(lo, hi, "steady window")
    if args.window_kind == "valve_open":
        if _valve_column(run) is None:
            warnings.append(f"run {run.run_label} has no valve-state channel; no valve-open window")
            return None
        pulses = valve_pulses(con, run)
        if not pulses:
            warnings.append(f"run {run.run_label}: the valve never opens in the data")
            return None
        if len(pulses) > 1:
            warnings.append(f"run {run.run_label}: {len(pulses)} valve-open pulses; the longest is used")
        lo, hi = pulses[0]
        return lo, hi, named(lo, hi, "valve open")
    window = args.window or TelemetryWindow()
    if t0 is None:
        warnings.append(
            f"run {run.run_label}: no ignition time (t0) was found, so a window from ignition is undefined"
        )
        return None
    lo = window.t_from_ignition_ms_start + t0 if window.t_from_ignition_ms_start is not None else None
    hi = window.t_from_ignition_ms_end + t0 if window.t_from_ignition_ms_end is not None else None
    start = rel(lo) if lo is not None else "start of run"
    end = rel(hi) if hi is not None else "end of run"
    return lo, hi, f"window {start} … {end} (t_from_ignition)"


def _select(pair: Pair) -> tuple[str, list]:
    c = _column(pair.channel.canonical_name)
    n = pair.rolling_n
    preceding, following = n // 2, (n - 1) // 2
    steady_lo, steady_hi = pair.steady or (None, None)
    sql = (
        f"SELECT {pair.key} AS key,"  # noqa: S608 — quoted catalog columns and ints; values are bound
        f" count({c}) AS n, count(*) AS rows, min({c}) AS min, max({c}) AS max, "
        f"avg({c}) AS mean, quantile_cont({c}, 0.99) AS p99, stddev_pop({c}) AS std, "
        f"arg_max(t_rel_ms, {c}) AS t_peak, min(t_rel_ms) AS t_first, max(t_rel_ms) AS t_last, "
        f"arg_min({c}, abs(t_rel_ms - ?)) AS value_at, arg_min(t_rel_ms, abs(t_rel_ms - ?)) AS t_at, "
        f"max(roll) AS peak_50ms, avg({c}) FILTER (WHERE t_rel_ms BETWEEN ? AND ?) AS steady "
        f"FROM (SELECT t_rel_ms, {c}, sum(coalesce({c}, 0)) OVER (ORDER BY t_rel_ms "
        f"ROWS BETWEEN {preceding} PRECEDING AND {following} FOLLOWING) / {n} AS roll "
        "FROM read_parquet(?) WHERE t_rel_ms BETWEEN ? AND ?)"
    )
    at = pair.at_rel if pair.at_rel is not None else 0.0
    params = [
        at,
        at,
        steady_lo if steady_lo is not None else -math.inf,
        steady_hi if steady_hi is not None else math.inf,
        pair.run.uri,
        pair.lo if pair.lo is not None else -math.inf,
        pair.hi if pair.hi is not None else math.inf,
    ]
    return sql, params


def fmt(value: float) -> str:
    """Five significant digits, positional (no exponent), so the answer can quote the string."""
    import numpy as np

    return np.format_float_positional(value, precision=5, unique=False, fractional=False, trim="-")


def _unit(channel) -> str:
    unit = channel.unit_si or ""
    return unit + UNIT_LABEL.get(channel.gauge_or_abs, "") if channel.quantity == Quantity.PRESSURE else unit


def _value(value: float, channel) -> str:
    text_ = f"{fmt(value)} {_unit(channel)}".strip()
    if channel.quantity == Quantity.TEMPERATURE and channel.unit_si in ("K", "kelvin"):
        text_ += f" ({fmt(value - 273.15)} °C)"
    return text_


def query_telemetry(
    session: Session, args: QueryTelemetryArgs, *, connect: Callable[[], Any] | None
) -> ToolResult:
    warnings: list[str] = []
    runs = _runs(session, args)
    if len(runs) > MAX_RUNS:
        warnings.append(f"more than {MAX_RUNS} runs match; the first {MAX_RUNS} by label are used")
        runs = runs[:MAX_RUNS]
    warnings += _halted(session, args, {r.run_label for r in runs})
    if args.plot:
        warnings.append("plots of telemetry are not available yet; the numbers are below")
    if connect is None:
        warnings.append("the telemetry store is not configured on this server")
        runs = []
    asked_runs = args.run_ids or (
        [f"{args.test_plan_id} {', '.join(args.test_run_ids)}"] if args.test_plan_id else []
    )
    if not runs:
        return ToolResult(
            tool=NAME,
            result={"runs": []},
            warnings=warnings,
            display="No telemetry run found for " + (", ".join(asked_runs) or "the request") + ".",
        )
    con = connect()
    try:
        pairs = _pairs(con, runs, args, warnings)
        rows = _execute(con, pairs, warnings)
    finally:
        con.close()
    return _result(runs, pairs, rows, args, warnings)


def _pairs(con, runs: list[Run], args: QueryTelemetryArgs, warnings: list[str]) -> list[Pair]:
    pairs: list[Pair] = []
    for run in runs:
        if not run.uri:
            warnings.append(f"run {run.run_label} has no normalized Parquet")
            continue
        dt = median_dt_ms(con, run)
        for asked in args.channels:
            matched = channels_for(run, asked)
            if not matched:
                warnings.append(f"run {run.run_label} has no {asked.replace('_', ' ')} channel")
                continue
            for channel in matched:
                window = _window(con, run, channel, args, warnings)
                if window is None:
                    continue
                lo, hi, window_text = window
                steady = None
                if args.window_kind == "run" and channel.steady_window_ms:
                    steady = tuple(float(v) for v in channel.steady_window_ms)
                elif args.window_kind != "run":
                    steady = (lo if lo is not None else -math.inf, hi if hi is not None else math.inf)
                pair = Pair(
                    key=len(pairs),
                    run=run,
                    asked=asked,
                    channel=channel,
                    lo=lo,
                    hi=hi,
                    window_text=window_text,
                    steady=steady,
                    rolling_n=max(1, round(PEAK_WINDOW_MS / dt)) if dt > 0 else 1,
                )
                if args.at_t_from_ignition_ms is not None and run.t0_ms is not None:
                    pair.at_rel = args.at_t_from_ignition_ms + run.t0_ms
                pairs.append(pair)
                _channel_warnings(run, channel, warnings)
    return pairs


def _channel_warnings(run: Run, channel, warnings: list[str]) -> None:
    name = f"run {run.run_label}: {channel.canonical_name}"
    if channel.saturated:
        warnings.append(f"{name}: sensor saturated at range limit")
    if channel.quantity == Quantity.PRESSURE and channel.gauge_or_abs == "gauge":
        has_abs = any(c.raw_name == channel.raw_name and c.gauge_or_abs == "absolute" for c in run.channels)
        if not has_abs and run.ambient == AmbientCondition.UNKNOWN:
            warnings.append(
                f"{name} is gauge pressure; absolute values are not computed because the ambient condition "
                "of the run is unknown"
            )


def _execute(con, pairs: list[Pair], warnings: list[str]) -> dict[int, dict]:
    if not pairs:
        return {}
    selects = [_select(p) for p in pairs]
    sql = " UNION ALL ".join(f"({s})" for s, _ in selects)
    params = [v for _, ps in selects for v in ps]
    try:
        cursor = con.execute(sql, params)
    except Exception as exc:  # noqa: BLE001 — duckdb.Error and IO errors become a warning, not a crash
        warnings.append(f"telemetry query failed: {str(exc)[:240]}")
        return {}
    names = [d[0] for d in cursor.description]
    return {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}


def _metrics(pair: Pair, row: dict, args: QueryTelemetryArgs) -> tuple[dict[str, float | None], list[str]]:
    run, channel = pair.run, pair.channel
    values: dict[str, float | None] = {}
    lines: list[str] = []
    wanted = list(dict.fromkeys(args.metrics))
    if "window_stats" in wanted:
        wanted = [m for m in wanted if m != "window_stats"] + ["min", "max", "mean", "p99"]
        wanted = list(dict.fromkeys(wanted))
    peak_50 = row["peak_50ms"] if row["rows"] >= pair.rolling_n else row["max"]
    t0 = run.t0_ms
    for metric in wanted:
        if metric in ("peak_raw", "max"):
            value = row["max"]
        elif metric == "peak_50ms":
            value = peak_50
        elif metric in ("min", "mean", "p99"):
            value = row[metric]
        elif metric == "steady_mean":
            value = row["steady"] if pair.steady is not None else None
            if value is None:
                lines.append(f"steady_mean: no steady plateau stored for {channel.canonical_name}")
                values[metric] = None
                continue
            if args.window_kind == "run":
                lo, hi = pair.steady
                where = (
                    f"t0+{_ms(lo - t0)} … t0+{_ms(hi - t0)}" if t0 is not None else f"{_ms(lo)} … {_ms(hi)}"
                )
                lines.append(f"steady_mean {_value(value, channel)} (stored steady window {where})")
                values[metric] = value
                continue
        elif metric == "duration":
            value = (row["t_last"] - row["t_first"]) / 1000 if row["t_first"] is not None else None
            values[metric] = value
            if value is not None:
                lines.append(f"duration {fmt(value)} s")
            continue
        elif metric == "time_to_peak":
            if row["t_peak"] is None:
                values[metric] = None
                continue
            origin = t0 if t0 is not None else row["t_first"]
            value = (row["t_peak"] - origin) / 1000
            values[metric] = value
            after = "ignition (t0)" if t0 is not None else "the window start"
            lines.append(f"time_to_peak {fmt(value)} s after {after}")
            continue
        elif metric == "value_at_t":
            if pair.at_rel is None:
                lines.append("value_at_t: needs a time from ignition and a run with t0")
                values[metric] = None
                continue
            value = row["value_at"]
            values[metric] = value
            if value is not None:
                lines.append(f"value_at_t {_value(value, channel)} at t0+{_ms(row['t_at'] - t0)}")
            continue
        else:
            continue
        values[metric] = value
        if value is not None:
            lines.append(f"{metric} {_value(value, channel)}")
    return values, lines


def _result(
    runs: list[Run], pairs: list[Pair], rows: dict[int, dict], args: QueryTelemetryArgs, warnings: list[str]
) -> ToolResult:
    out_runs: dict[str, dict] = {}
    display: list[str] = []
    for pair in pairs:
        row = rows.get(pair.key)
        if row is None:
            continue
        run, channel = pair.run, pair.channel
        values, lines = _metrics(pair, row, args)
        rate = f"{fmt(run.rate_hz)} Hz" if run.rate_hz else "rate unknown"
        head = (
            f"Run {run.run_label} · {pair.asked} → {channel.canonical_name} ({_unit(channel)}, "
            f"{channel.gauge_or_abs}); {pair.window_text}; t0_method {run.t0_method or 'none'}; {rate}; "
            f"{row['n']} samples in the window; {run.uri}"
        )
        display.append(head + ": " + "; ".join(lines))
        entry = out_runs.setdefault(
            run.run_label,
            {
                "run_label": run.run_label,
                "doc_id": str(run.doc_id),
                "ambient_condition": run.ambient,
                "t0_method": run.t0_method,
                "sampling_rate_hz": run.rate_hz,
                "n_rows": run.n_rows,
                "parquet_uri": run.uri,
                "channels": [],
            },
        )
        entry["channels"].append(
            {
                "quantity": pair.asked,
                "canonical_name": channel.canonical_name,
                "unit": _unit(channel),
                "gauge_or_abs": channel.gauge_or_abs,
                "window": {
                    "kind": args.window_kind,
                    "t_rel_ms": [pair.lo, pair.hi],
                    "text": pair.window_text,
                },
                "n_in_window": row["n"],
                "saturated": channel.saturated,
                "metrics": values,
            }
        )
    used = {p.run.run_label for p in pairs if p.key in rows}
    provenance = [
        Source(
            doc_id=run.doc_id,
            anchor=run.anchor,
            title=run.title,
            label=f"Run {run.run_label} (measured telemetry)",
            provenance=Provenance.MEASURED,
        )
        for run in runs
        if run.run_label in used
    ]
    if warnings:
        display.append("Warnings: " + " | ".join(warnings))
    return ToolResult(
        tool=NAME,
        result={"runs": list(out_runs.values()), "compare_runs": args.compare_runs},
        provenance=provenance,
        warnings=warnings,
        display="\n".join(display) or "No telemetry values could be computed.",
    )
