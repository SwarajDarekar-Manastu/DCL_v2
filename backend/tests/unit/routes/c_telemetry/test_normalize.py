"""Normalization on a synthetic firing (no services): conversion, t0, three-tier metrics, bounds."""

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.postgres.enums import AmbientCondition, GaugeOrAbs, Quantity
from backend.review.rules import ChannelMapEntry
from backend.routes.c_telemetry.normalize import (
    ExpressionError,
    NormalizeConfig,
    PlanProblem,
    compile_expression,
    in_bounds,
    is_saturated,
    matching_range,
    normalize_run,
    plan_channel,
    sanity_ranges_from,
    voltage_plan,
)

RATE = 1000.0
IGNITION_S, SHUTDOWN_S, END_S = 1.0, 4.0, 5.0


def firing(noise: float = 0.02):
    """Chamber pressure (bar g): 0, a 50 ms rise to 10 bar at 1 s, plateau, shutdown at 4 s."""
    t = np.arange(0, END_S, 1 / RATE)
    p = np.clip((t - IGNITION_S) / 0.05, 0, 1) * 10.0
    p[t > SHUTDOWN_S] = np.clip(10.0 - (t[t > SHUTDOWN_S] - SHUTDOWN_S) / 0.05 * 10.0, 0, None)
    p += np.random.default_rng(3).normal(0, noise, len(t))
    valve = ((t >= IGNITION_S) & (t <= SHUTDOWN_S)).astype(float)
    return t, p, valve


def write_raw(path, **columns):
    pq.write_table(pa.table({name: pa.array(values) for name, values in columns.items()}), path)


def entry(**values) -> ChannelMapEntry:
    return ChannelMapEntry.model_validate(values)


CHAMBER = entry(
    canonical_name="pt_101_chamber_bar_g", physical_quantity="pressure", unit="bar", gauge_or_abs="gauge"
)


def test_t0_metrics_absolute_column_and_time_axes(tmp_path):
    t, p, _ = firing()
    write_raw(tmp_path / "raw.parquet", Time=t, y0=p, v0=p / 25)
    plan = plan_channel("y0", CHAMBER, AmbientCondition.SEA_LEVEL, None)
    run = normalize_run(
        tmp_path / "raw.parquet",
        "Time",
        [voltage_plan("v0"), plan],
        tmp_path / "n.parquet",
        NormalizeConfig(),
        {},
    )

    assert run.rows == len(t)
    assert run.t0.t_ms == pytest.approx(IGNITION_S * 1000, abs=10)
    assert run.t0.confidence > 0.5 and run.t0.channel == "pt_101_chamber_bar_g"
    table = pq.read_table(tmp_path / "n.parquet")
    assert table.column_names == [
        "t_rel_ms",
        "t_from_ignition_ms",
        "v0_v",
        "pt_101_chamber_bar_g",
        "pt_101_chamber_bar_abs",
    ]
    np.testing.assert_allclose(table["t_rel_ms"].to_numpy(), t * 1000)
    np.testing.assert_allclose(table["t_from_ignition_ms"].to_numpy(), t * 1000 - run.t0.t_ms)
    np.testing.assert_allclose(table["pt_101_chamber_bar_abs"].to_numpy(), p + 1.01325)
    assert table.schema.field("pt_101_chamber_bar_abs").metadata[b"gauge_or_abs"] == b"absolute"

    by = {r.column: r for r in run.columns}
    gauge = by["pt_101_chamber_bar_g"]
    assert gauge.metrics.peak_raw == pytest.approx(p.max())
    assert gauge.metrics.peak_50ms == pytest.approx(10.0, abs=0.05)
    assert gauge.metrics.steady_mean == pytest.approx(10.0, abs=0.02)
    start, end = gauge.metrics.steady_window_ms
    assert start >= (IGNITION_S + 1.0) * 1000 - 1 and end <= SHUTDOWN_S * 1000
    assert by["pt_101_chamber_bar_abs"].metrics.steady_mean == pytest.approx(11.01325, abs=0.02)
    assert by["v0_v"].metrics.peak_raw is None  # voltages get stats only
    assert gauge.stats["p99"] == pytest.approx(np.percentile(p, 99))


def test_the_valve_column_defines_the_steady_window(tmp_path):
    t, p, valve = firing()
    write_raw(tmp_path / "raw.parquet", Time=t, y0=p, y1=valve)
    plans = [
        plan_channel("y0", CHAMBER, None, None),
        plan_channel(
            "y1",
            entry(canonical_name="valve_state", physical_quantity="valve_state", unit="dimensionless"),
            None,
            None,
        ),
    ]
    run = normalize_run(
        tmp_path / "raw.parquet", "Time", plans, tmp_path / "n.parquet", NormalizeConfig(), {}
    )
    gauge = run.columns[0]
    assert (
        run.columns[0].column == "pt_101_chamber_bar_g" and len(run.columns) == 2
    )  # no ambient: no abs column
    start, end = gauge.metrics.steady_window_ms
    assert start == pytest.approx(run.t0.t_ms + 1000, abs=1.5) and end == 4000


def test_no_edge_no_t0_and_a_null_ignition_axis(tmp_path):
    t = np.arange(0, 2, 0.001)
    write_raw(tmp_path / "raw.parquet", Time=t, y0=np.full(len(t), 3.0))
    run = normalize_run(
        tmp_path / "raw.parquet",
        "Time",
        [plan_channel("y0", CHAMBER, None, None)],
        tmp_path / "n.parquet",
        NormalizeConfig(),
        {},
    )
    assert run.t0 is None
    assert pq.read_table(tmp_path / "n.parquet")["t_from_ignition_ms"].null_count == len(t)


def test_unit_conversion_gauge_from_spelling_and_problems():
    psig = plan_channel(
        "y0",
        entry(canonical_name="pt_g", physical_quantity="pressure", unit="psig"),
        AmbientCondition.SEA_LEVEL,
        None,
    )
    assert psig.gauge_or_abs == GaugeOrAbs.GAUGE and psig.unit_si == "bar"
    assert psig.convert(np.array([100.0]))[0] == pytest.approx(6.894757, rel=1e-6)
    assert psig.abs_column == "pt_abs"
    celsius = plan_channel(
        "y1", entry(canonical_name="tc_k", physical_quantity="temperature", unit="degC"), None, None
    )
    assert celsius.convert(np.array([0.0, 100.0])) == pytest.approx([273.15, 373.15])
    scaled = plan_channel(
        "y2",
        entry(
            canonical_name="thrust_n",
            physical_quantity="force",
            unit="N",
            scaling={"slope": 50.044, "offset": -1},
        ),
        None,
        None,
    )
    assert scaled.convert(np.array([2.0]))[0] == pytest.approx(99.088)
    expr = plan_channel(
        "y3",
        entry(
            canonical_name="pt_abs",
            physical_quantity="pressure",
            unit="bar",
            gauge_or_abs="absolute",
            expression="val * 0.0689476 + 1.01325",
        ),
        None,
        None,
    )
    assert expr.convert(np.array([100.0]))[0] == pytest.approx(7.90801)

    assert isinstance(
        plan_channel("y4", entry(canonical_name="p", physical_quantity="pressure", unit="bar"), None, None),
        PlanProblem,
    )
    assert isinstance(
        plan_channel("y5", entry(canonical_name="p", physical_quantity="pressure", unit="K"), None, None),
        PlanProblem,
    )
    gauge_no_ambient = plan_channel("y6", CHAMBER, AmbientCondition.UNKNOWN, None)
    assert gauge_no_ambient.abs_column is None  # gauge kept; absolute waits for the ambient
    recorded = plan_channel("y7", CHAMBER, AmbientCondition.AMBIENT_RECORDED, 0.95)
    assert recorded.ambient_bar_abs == 0.95 and recorded.abs_column == "pt_101_chamber_bar_abs"


@pytest.mark.parametrize("bad", ["__import__('os')", "val.real", "open('x')", "val if val else 1", "[val]"])
def test_expressions_allow_arithmetic_only(bad):
    with pytest.raises(ExpressionError):
        compile_expression(bad)
    assert compile_expression("-val ** 2 / 4 + 3")(np.array([2.0]))[0] == pytest.approx(2.0)
    assert compile_expression("5")(np.array([1.0, 2.0])).tolist() == [5.0, 5.0]


def test_saturation_needs_a_flat_top_at_the_range():
    x = np.concatenate([np.linspace(0, 99.95, 100), np.full(30, 100.0)])
    assert is_saturated(x, 100.0)
    assert not is_saturated(x[:110], 100.0)
    assert not is_saturated(x, None)


def test_sanity_ranges_first_match_wins():
    ranges = sanity_ranges_from(
        {
            "ranges": [
                {
                    "id": "chamber_pressure",
                    "physical_quantity": "pressure",
                    "canonical_name_glob": "*chamber*",
                    "unit": "bar",
                    "min": 0,
                    "max": 150,
                },
                {
                    "id": "pressure_general",
                    "physical_quantity": "pressure",
                    "canonical_name_glob": "*",
                    "unit": "bar",
                    "min": 0,
                    "max": 700,
                },
                {
                    "id": "mass_flow",
                    "physical_quantity": "mass_flow_rate",
                    "canonical_name_glob": "*",
                    "unit": "kg/s",
                    "min": 0,
                    "max": 5,
                },
            ]
        }
    )
    assert matching_range(ranges, Quantity.PRESSURE, "PT_101_Chamber_bar_abs").id == "chamber_pressure"
    assert matching_range(ranges, Quantity.PRESSURE, "pt_feed").id == "pressure_general"
    assert matching_range(ranges, Quantity.FORCE, "thrust_n") is None
    flow = matching_range(ranges, Quantity.MASS_FLOW_RATE, "mdot_g_s")
    assert in_bounds(4999.0, flow, "gram / second") and not in_bounds(5001.0, flow, "gram / second")


def test_a_valve_signal_is_open_at_its_threshold(tmp_path):
    """S5 measured the logged signal near 5.3 when open with ramped edges; 2.5 matches the SME window."""
    t = np.arange(0, 3, 0.001)
    signal = np.interp(t, [0, 0.999, 1.0, 1.003, 2.0, 2.003, 3], [0, 0, 1.5, 5.3, 5.3, 2.3, 0])
    write_raw(tmp_path / "raw.parquet", Time=t, y7=signal)
    valve = entry(
        canonical_name="valve_signal",
        physical_quantity="valve_state",
        unit="dimensionless",
        open_threshold=2.5,
    )
    plan = plan_channel("y7", valve, None, None)
    run = normalize_run(
        tmp_path / "raw.parquet", "Time", [plan], tmp_path / "n.parquet", NormalizeConfig(), {}
    )
    state = pq.read_table(tmp_path / "n.parquet")["valve_signal"].to_numpy()
    opened = t[state == 1.0]
    assert set(np.unique(state)) == {0.0, 1.0}
    assert opened[0] == pytest.approx(1.001, abs=0.0011) and opened[-1] == pytest.approx(2.002, abs=0.0005)
    assert run.t0.method == "valve_state rising edge" and run.t0.t_ms == pytest.approx(opened[0] * 1000)
    assert plan.conversion["open_threshold"] == 2.5
    with pytest.raises(ValueError, match="valve_state channels only"):
        entry(
            canonical_name="p",
            physical_quantity="pressure",
            unit="bar",
            gauge_or_abs="gauge",
            open_threshold=1,
        )
