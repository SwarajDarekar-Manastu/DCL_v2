"""Golden telemetry suite (feature quality/benchmark-suites).

The committed template carries questions, methods, units and tolerances, never measured values
(DECISIONS.md 2026-10-22). When the git-ignored suite data/benchmark/telemetry.json and the
samples exist, every value is recomputed from the raw files and cross-checked with the team's
workbook values kept beside it.
"""

import importlib.util
import json
import re
import typing
from pathlib import Path

import pint
import pytest
import yaml

from backend.benchmark.catalog import CASE_ID, CaseCreate
from backend.llm_engine.engine.analysis import ToolName
from backend.postgres.enums import BenchmarkCategory

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
_spec = importlib.util.spec_from_file_location(
    "s5_telemetry_metrics", HERE / "verification/telemetry_metrics.py"
)
tm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tm)

TEMPLATE = yaml.safe_load(tm.TEMPLATE.read_text(encoding="utf-8"))
CASES = TEMPLATE["cases"]
NUMERIC = [c for c in CASES if "method" in c]


@pytest.fixture(scope="module")
def ureg():
    registry = pint.UnitRegistry()
    registry.load_definitions(str(REPO / "config/units.txt"))
    return registry


def test_template_shape():
    assert TEMPLATE["precondition"].startswith("Precondition:")
    ids = [c["case_id"] for c in CASES]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(CASE_ID, i) for i in ids)
    assert {c["category"] for c in CASES} <= {m.value for m in BenchmarkCategory}
    assert len(NUMERIC) >= 15  # brief: the first 15 telemetry cases
    for c in CASES:
        assert ("method" in c) == (c["category"] == "TELEMETRY_MATH"), c["case_id"]
        assert "method" in c or c.get("expected_behavior"), c["case_id"]


def test_template_holds_no_values_or_file_names():
    text = tm.TEMPLATE.read_text(encoding="utf-8")
    assert "value:" not in text and "team_values" not in text
    assert not re.search(r"\w\.(dat|dat_fail|csv|xlsx|tdms)\b", text, re.IGNORECASE)  # a file name


@pytest.mark.parametrize("case", NUMERIC, ids=lambda c: c["case_id"])
def test_numeric_case_method_and_unit(case, ureg):
    assert case["method"]["fn"] in tm.METHODS
    assert case["tolerance_pct"] > 0 and isinstance(case["decimals"], int)
    ureg.Quantity(1, case["unit"])  # parses with the project registry
    assert case["expected_tools"] == ["query_telemetry"]  # file 08 §5.3
    assert set(case["expected_tools"]) <= set(typing.get_args(ToolName))  # the engine's tool names


SUITE = tm.SUITE_OUT
needs_suite = pytest.mark.skipif(
    not SUITE.is_file(), reason="data/benchmark/telemetry.json not built locally"
)


@needs_suite
def test_built_suite_validates_and_matches_the_template():
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    for case in suite["cases"]:
        CaseCreate.model_validate(case)
        if case["category"] == "TELEMETRY_MATH":
            assert case["notes"].startswith(TEMPLATE["precondition"])
    assert [c["case_id"] for c in suite["cases"]] == [c["case_id"] for c in CASES]


@needs_suite
@pytest.mark.parametrize("case", NUMERIC, ids=lambda c: c["case_id"])
def test_values_recompute_from_raw_files_and_match_the_team(case):
    sources = yaml.safe_load(tm.SOURCES.read_text(encoding="utf-8"))
    built = {c["case_id"]: c for c in json.loads(SUITE.read_text(encoding="utf-8"))["cases"]}
    expected = built[case["case_id"]]["spec"]["expected_numeric"][0]
    try:
        value = tm.evaluate(case["method"], sources)
    except FileNotFoundError:
        pytest.skip("raw files not exported locally")
    assert round(value, case["decimals"]) == expected["value"]
    team = sources.get("team_values", {}).get(case["case_id"])
    if team is not None:
        assert value == pytest.approx(team, rel=case["tolerance_pct"] / 100)
