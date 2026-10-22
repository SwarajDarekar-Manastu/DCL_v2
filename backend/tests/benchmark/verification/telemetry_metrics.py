"""Telemetry metrics that verify golden cases outside the pipeline (S5, file 08 §5.7).

Reads LabJack LJStreamM .dat files (6 header lines: date, time, blanks, column names; columns
Time, v0-v7 raw volts, y0-y7 scaled) and USB-TC thermocouple logger .csv files. Nothing here
uses pipeline code, so a value computed here is an independent check of the engine's answer.

The measured values never enter the public repository (DECISIONS.md 2026-10-22). The committed
suite template names a method per case; the git-ignored data/benchmark/telemetry_sources.yaml maps
run keys to local files under data/samples/; `build` writes the importable suite with values to
data/benchmark/telemetry.json:

    uv run python backend/tests/benchmark/verification/telemetry_metrics.py build
"""

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[4]
TEMPLATE = REPO / "backend/tests/benchmark/suites/telemetry.template.yaml"
SOURCES = REPO / "data/benchmark/telemetry_sources.yaml"
SAMPLES = REPO / "data/samples"
SUITE_OUT = REPO / "data/benchmark/telemetry.json"
VALVE_CHANNEL, VALVE_THRESHOLD_V = "y7", 2.5


@dataclass(frozen=True)
class Run:
    t: np.ndarray
    y: dict[str, np.ndarray]
    start: datetime

    def window(self) -> tuple[int, int]:
        """First and last sample of the single valve-open pulse (valve signal above threshold)."""
        on = np.flatnonzero(self.y[VALVE_CHANNEL] > VALVE_THRESHOLD_V)
        if not len(on):
            raise ValueError("no valve-open samples")
        if np.any(np.diff(on) > 1):
            raise ValueError("more than one valve pulse; this metric expects one")
        return int(on[0]), int(on[-1])


def load_dat(path: Path) -> Run:
    with path.open(encoding="ascii", errors="replace") as fh:
        head = [next(fh).strip() for _ in range(6)]
    cols = head[5].split()
    data = np.loadtxt(path, skiprows=6)
    start = datetime.strptime(f"{head[0]} {head[1]}", "%d-%m-%Y %H:%M:%S")
    return Run(t=data[:, 0], y={c: data[:, i] for i, c in enumerate(cols) if c.startswith("y")}, start=start)


def load_logger_csv(path: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """USB-TC logger: 6 metadata lines, then 'Sample','Date/Time', one column per thermocouple
    whose label starts with its designation (T1 …). Returns POSIX times and {designation: °C}."""
    with path.open(encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    header = next(r for r in rows if r[:2] == ["Sample", "Date/Time"])
    body = [r for r in rows[rows.index(header) + 1 :] if r and r[0].isdigit()]
    times = np.array([datetime.strptime(r[1], "%d-%m-%Y %H:%M:%S.%f").timestamp() for r in body])
    series = {
        label.split(" ")[0]: np.array([float(r[i]) for r in body]) for i, label in enumerate(header) if i >= 2
    }
    return times, series


def valve_open_duration(run: Run) -> float:
    i0, i1 = run.window()
    return float(run.t[i1] - run.t[i0])


def window_mean(run: Run, channel: str) -> float:
    i0, i1 = run.window()
    return float(run.y[channel][i0 : i1 + 1].mean())


def window_max(run: Run, channel: str) -> float:
    i0, i1 = run.window()
    return float(run.y[channel][i0 : i1 + 1].max())


def window_integral(run: Run, channel: str) -> float:
    i0, i1 = run.window()
    return float(np.trapezoid(run.y[channel][i0 : i1 + 1], run.t[i0 : i1 + 1]))


def rise_time(run: Run, channel: str, fraction: float = 0.9) -> float:
    """Time from valve opening until the channel first reaches `fraction` of its valve-open mean."""
    i0, _ = run.window()
    level = fraction * window_mean(run, channel)
    reached = np.flatnonzero((np.arange(len(run.t)) >= i0) & (run.y[channel] >= level))
    return float(run.t[reached[0]] - run.t[i0])


def _wallclock(run: Run, i: int) -> float:
    return run.start.timestamp() + float(run.t[i])


def temperature_at_valve_open(run: Run, logger: tuple, sensor: str) -> float:
    times, series = logger
    return float(series[sensor][np.argmin(np.abs(times - _wallclock(run, run.window()[0])))])


def temperature_max_valve_open(run: Run, logger: tuple, sensor: str) -> float:
    times, series = logger
    i0, i1 = run.window()
    inside = (times >= _wallclock(run, i0)) & (times <= _wallclock(run, i1))
    return float(series[sensor][inside].max())


def temperature_after_close(run: Run, logger: tuple, sensor: str, seconds: float) -> float:
    times, series = logger
    target = _wallclock(run, run.window()[1]) + seconds
    return float(series[sensor][np.argmin(np.abs(times - target))])


METHODS = {
    f.__name__: f
    for f in (
        valve_open_duration,
        window_mean,
        window_max,
        window_integral,
        rise_time,
        temperature_at_valve_open,
        temperature_max_valve_open,
        temperature_after_close,
    )
}


def evaluate(method: dict, sources: dict) -> float:
    """method = {fn, run, [logger], [channel], [sensor], [seconds], [fraction]} from the template."""
    run = load_dat(SAMPLES / sources["runs"][method["run"]])
    kwargs = {k: v for k, v in method.items() if k in ("channel", "sensor", "seconds", "fraction")}
    if "logger" in method:
        return METHODS[method["fn"]](
            run, load_logger_csv(SAMPLES / sources["loggers"][method["logger"]]), **kwargs
        )
    return METHODS[method["fn"]](run, **kwargs)


def build(template: dict, sources: dict) -> dict:
    """The importable suite (S3 POST /benchmark/suites/{suite}/import body) with computed values."""
    cases = []
    for case in template["cases"]:
        spec = {"expected_behavior": case.get("expected_behavior", [])}
        notes = case.get("notes", "")
        if "method" in case:
            value = round(evaluate(case["method"], sources), case["decimals"])
            spec["expected_numeric"] = [
                {
                    "metric": case["metric"],
                    "value": value,
                    "unit": case["unit"],
                    "tolerance_pct": case["tolerance_pct"],
                }
            ]
            team = sources.get("team_values", {}).get(case["case_id"])
            notes = " ".join(part for part in (template.get("precondition", ""), notes) if part)
            notes += (
                f" Verified {datetime.now():%Y-%m-%d} by telemetry_metrics.{case['method']['fn']} over the"
                f" raw files" + (f"; team workbook value {team}." if team is not None else ".")
            )
        if case.get("expected_tools"):
            spec["expected_tools"] = {"tools": case["expected_tools"], "ordered": False}
        cases.append(
            {
                "case_id": case["case_id"],
                "suite": template["suite"],
                "category": case["category"],
                "status": "active",
                "question": case["question"],
                "difficulty": case.get("difficulty"),
                "notes": notes.strip(),
                "spec": spec,
            }
        )
    return {"cases": cases}


def main(argv: list[str]) -> int:
    if argv != ["build"]:
        print(__doc__, file=sys.stderr)
        return 2
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))
    SUITE_OUT.write_text(json.dumps(build(template, sources), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {SUITE_OUT} ({len(template['cases'])} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
