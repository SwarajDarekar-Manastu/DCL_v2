"""T2 query_telemetry on real catalog rows and a real Parquet file (DuckDB reads a local path the same way it
reads s3:// in the stack). Needs DCL_TEST_DATABASE_URL (an empty ParadeDB 0.26.2 database).

Expected values come from numpy on the same arrays, and the stored three-tier metrics from Route C's own
`three_tier_metrics`, so the tool must reproduce Route C exactly."""

import os
import uuid
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

duckdb = pytest.importorskip("duckdb")

from backend.llm_engine.engine.tools import Provenance  # noqa: E402
from backend.llm_engine.engine.tools.telemetry import QueryTelemetryArgs, fmt, query_telemetry  # noqa: E402
from backend.postgres.enums import DocumentStatus  # noqa: E402
from backend.postgres.models import Blob, Document, ReviewFlag, TelemetryChannel, TelemetryRun  # noqa: E402
from backend.postgres.session import normalize_url  # noqa: E402
from backend.routes.c_telemetry.normalize import NormalizeConfig, three_tier_metrics  # noqa: E402

ALEMBIC_INI = Path(__file__).resolve().parents[4] / "postgres" / "alembic.ini"
T0 = 1000.0


def series(seed: int, level: float):
    """10 s at 1 kHz: ignition at 1 s, plateau at `level` bar g with noise, a 2 ms spike, valve 1–9 s."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, 10_000, 1.0)
    p = np.where(t < T0, 0.02, level * (1 - np.exp(-(t - T0) / 80.0))) + rng.normal(0, 0.05, t.size)
    p[(t >= 1500) & (t < 1502)] = level * 4
    p[t >= 9000] = 0.02
    thrust = 2.0 * p + rng.normal(0, 0.1, t.size)
    valve = ((t >= T0) & (t < 9000)).astype(np.float64)
    return t, p, thrust, valve


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    url = normalize_url(url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        config = Config(str(ALEMBIC_INI))
        command.upgrade(config, "head")
        eng = create_engine(url)
        yield eng
        eng.dispose()
        command.downgrade(config, "base")


@pytest.fixture(scope="module")
def data(engine, tmp_path_factory):
    out = {}
    folder = tmp_path_factory.mktemp("telemetry")
    with Session(engine) as s:

        def add_run(label, run_id, seed, level, ambient="UNKNOWN"):
            sha = uuid.uuid4().hex + uuid.uuid4().hex
            s.add(Blob(sha256=sha, size_bytes=1, minio_uri=f"s3://dcl-raw/{sha}"))
            d = Document(
                route="C",
                status=DocumentStatus.ACTIVE,
                title=f"{label}.dat",
                doc_kind="telemetry_run",
                test_plan_id="TP07",
                test_run_id=run_id,
            )
            s.add(d)
            s.flush()
            t, p, thrust, valve = series(seed, level)
            path = folder / f"{label}.parquet"
            pq.write_table(
                pa.table(
                    {
                        "t_rel_ms": t,
                        "t_from_ignition_ms": t - T0,
                        "p_chamber_1_bar_g": p,
                        "thrust_n": thrust,
                        "valve_signal": valve,
                    }
                ),
                path,
            )
            run = TelemetryRun(
                run_uuid=uuid.uuid4(),
                run_label=label,
                doc_id=d.doc_id,
                blob_sha256=sha,
                source_format="labjack_dat",
                ambient_condition=ambient,
                sampling_rate_hz_actual=1000.0,
                duration_s=9.999,
                n_rows=t.size,
                t0_ignition_ms=int(T0),
                t0_method="pressure_slope",
                normalized_parquet_uri=str(path),
            )
            s.add(run)
            s.flush()
            metrics = {}
            for name, x, quantity, unit, gauge in (
                ("p_chamber_1_bar_g", p, "pressure", "bar", "gauge"),
                ("thrust_n", thrust, "force", "N", "n/a"),
            ):
                m = three_tier_metrics(t, x, T0, valve > 0.5, NormalizeConfig())
                metrics[name] = (x, m)
                s.add(
                    TelemetryChannel(
                        run_uuid=run.run_uuid,
                        canonical_name=name,
                        raw_name=name,
                        quantity=quantity,
                        unit_si=unit,
                        gauge_or_abs=gauge,
                        stat_max=float(x.max()),
                        peak_raw=m.peak_raw,
                        peak_50ms=m.peak_50ms,
                        steady_mean=m.steady_mean,
                        steady_window_ms=m.steady_window_ms,
                        saturated=name == "thrust_n" and label == "TP07_T05",
                    )
                )
            s.add(
                TelemetryChannel(
                    run_uuid=run.run_uuid,
                    canonical_name="valve_signal",
                    raw_name="y7",
                    quantity="valve_state",
                    unit_si="1",
                )
            )
            out[label] = {"t": t, "valve": valve, **metrics}

        add_run("TP07_T04", "T04", 1, 12.4)
        add_run("TP07_T05", "T05", 2, 11.0, ambient="VACUUM_CHAMBER")
        halted = Document(
            route="C",
            status=DocumentStatus.HALTED,
            title="TP07_T06.dat",
            doc_kind="telemetry_run",
            test_plan_id="TP07",
            test_run_id="T06",
            staged_payload_uri="s3://dcl-cir/x/staged.json",
        )
        s.add(halted)
        s.flush()
        s.add(
            ReviewFlag(
                case_key="case-unit-tp07-t06",
                doc_id=halted.doc_id,
                page_or_sheet="",
                fingerprint="e" * 64,
                flag_type="UNIT_AMBIGUITY",
                severity="HARD",
                status="OPEN",
            )
        )
        s.commit()
    return out


def run(engine, **args):
    with Session(engine) as s:
        return query_telemetry(s, QueryTelemetryArgs(**args), connect=duckdb.connect)


def channel(result, label, name):
    [run_] = [r for r in result.result["runs"] if r["run_label"] == label]
    [found] = [c for c in run_["channels"] if c["canonical_name"] == name]
    return found["metrics"]


def test_whole_run_metrics_reproduce_route_c_and_numpy(engine, data):
    result = run(
        engine,
        run_ids=["TP07_T04"],
        channels=["chamber_pressure"],
        metrics=["peak_raw", "peak_50ms", "steady_mean", "mean", "p99", "time_to_peak"],
    )
    x, stored = data["TP07_T04"]["p_chamber_1_bar_g"]
    got = channel(result, "TP07_T04", "p_chamber_1_bar_g")
    assert got["peak_raw"] == pytest.approx(stored.peak_raw, rel=1e-12)
    assert got["peak_50ms"] == pytest.approx(stored.peak_50ms, rel=1e-9)
    assert got["steady_mean"] == pytest.approx(stored.steady_mean, rel=1e-9)
    assert got["mean"] == pytest.approx(x.mean(), rel=1e-9)
    assert got["p99"] == pytest.approx(np.percentile(x, 99), rel=1e-9)
    assert got["time_to_peak"] == pytest.approx(0.5)  # the spike at 1.5 s, t0 = 1.0 s
    assert f"peak_50ms {fmt(stored.peak_50ms)} barg" in result.display
    assert "t0_method pressure_slope" in result.display and "1000 Hz" in result.display
    assert result.provenance[0].provenance == Provenance.MEASURED
    assert "absolute values are not computed because the ambient condition" in " ".join(result.warnings)


def test_valve_open_window_matches_the_golden_method(engine, data):
    result = run(
        engine,
        test_plan_id="TP07",
        test_run_ids=["T04"],
        channels=["chamber_pressure", "thrust"],
        metrics=["duration", "window_stats"],
        window_kind="valve_open",
    )
    d = data["TP07_T04"]
    i = np.flatnonzero(d["valve"] > 0.5)
    x, _ = d["p_chamber_1_bar_g"]
    got = channel(result, "TP07_T04", "p_chamber_1_bar_g")
    assert got["duration"] == pytest.approx((d["t"][i[-1]] - d["t"][i[0]]) / 1000)
    assert got["mean"] == pytest.approx(x[i[0] : i[-1] + 1].mean(), rel=1e-9)
    assert got["max"] == pytest.approx(x[i[0] : i[-1] + 1].max(), rel=1e-12)
    thrust, _ = d["thrust_n"]
    assert channel(result, "TP07_T04", "thrust_n")["mean"] == pytest.approx(
        thrust[i[0] : i[-1] + 1].mean(), rel=1e-9
    )
    assert "valve open t0+0.000 s … t0+7.999 s" in result.display


def test_user_window_value_at_t_and_comparison(engine, data):
    result = run(
        engine,
        test_plan_id="TP07",
        channels=["chamber_pressure"],
        metrics=["mean", "value_at_t"],
        window={"t_from_ignition_ms_start": 2000, "t_from_ignition_ms_end": 4000},
        at_t_from_ignition_ms=3000,
        compare_runs=True,
    )
    assert [r["run_label"] for r in result.result["runs"]] == ["TP07_T04", "TP07_T05"]
    for label in ("TP07_T04", "TP07_T05"):
        x, _ = data[label]["p_chamber_1_bar_g"]
        t = data[label]["t"]
        inside = (t >= T0 + 2000) & (t <= T0 + 4000)
        got = channel(result, label, "p_chamber_1_bar_g")
        assert got["mean"] == pytest.approx(x[inside].mean(), rel=1e-9)
        assert got["value_at_t"] == pytest.approx(x[t == T0 + 3000][0])
    assert "run TP07_T06 (TP07_T06.dat) is halted for review (case-unit-tp07-t06)" in " ".join(
        result.warnings
    )
    assert "TP07_T05: thrust_n" not in " ".join(result.warnings)  # thrust was not asked


def test_missing_quantity_saturation_and_halted_run(engine, data):
    result = run(engine, run_ids=["TP07_T05", "TP07_T06"], channels=["bed_temperature", "thrust"])
    warnings = " ".join(result.warnings)
    assert "run TP07_T05 has no bed temperature channel" in warnings
    assert "run TP07_T05: thrust_n: sensor saturated at range limit" in warnings
    assert "halted for review (case-unit-tp07-t06)" in warnings
    halted_only = run(engine, run_ids=["TP07_T06"], channels=["thrust"])
    assert halted_only.result["runs"] == [] and "halted for review" in " ".join(halted_only.warnings)


def test_no_store_configured(engine, data):
    with Session(engine) as s:
        result = query_telemetry(
            s, QueryTelemetryArgs(run_ids=["TP07_T04"], channels=["thrust"]), connect=None
        )
    assert result.result["runs"] == [] and "not configured" in " ".join(result.warnings)


def test_plot_is_a_png_in_the_asset_store_with_a_presigned_link(engine, data):
    stored = {}

    def put_asset(key, png):
        stored[key] = png
        return f"s3://dcl-assets/{key}"

    def ask():
        with Session(engine) as s:
            return query_telemetry(
                s,
                QueryTelemetryArgs(
                    run_ids=["TP07_T04"],
                    channels=["chamber_pressure", "thrust"],
                    window_kind="valve_open",
                    plot=True,
                ),
                connect=duckdb.connect,
                put_asset=put_asset,
                presign=lambda uri: "https://minio.test/" + uri.removeprefix("s3://"),
            )

    first, second = ask(), ask()
    [plot] = first.result["plots"]
    assert len(stored) == 1  # the same question overwrites the same key
    [(key, png)] = stored.items()
    assert key.startswith("plots/") and key.endswith(".png") and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert (
        plot["url"] == f"https://minio.test/dcl-assets/{key}"
        and second.result["plots"][0]["url"] == plot["url"]
    )
    assert "p_chamber_1_bar_g, thrust_n" in plot["alt"] and "valve open" in plot["alt"]
    without_store = run(engine, run_ids=["TP07_T04"], channels=["thrust"], plot=True)
    assert without_store.result["plots"] == [] and "asset store" in " ".join(without_store.warnings)
