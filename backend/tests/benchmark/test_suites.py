"""Golden suites built by verification/build_suites.py (every suite except telemetry).

Templates are committed without measured values or company file names (DECISIONS.md 2026-10-22);
local fragments and the built suites live in the git-ignored data/benchmark/.
"""

import importlib.util
import json
import re
import typing
from pathlib import Path

import pytest
import yaml

from backend.benchmark.catalog import CASE_ID, CaseCreate, ExpectedBehavior
from backend.llm_engine.engine.analysis import ToolName
from backend.postgres.enums import BenchmarkCategory

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s5_build_suites", HERE / "verification/build_suites.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

TEMPLATES = bs.templates()
TOOLS = set(typing.get_args(ToolName))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def all_template_ids() -> list[str]:
    ids = []
    for path in [*TEMPLATES, bs.SUITES / "telemetry.template.yaml"]:
        ids += [c["case_id"] for c in load(path)["cases"]]
    return ids


def test_case_ids_unique_across_all_suites():
    ids = all_template_ids()
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_shape(path):
    template = load(path)
    assert path.name == f"{template['suite']}.template.yaml"
    for case in template["cases"]:
        assert set(case) <= bs.CASE_KEYS, case["case_id"]
        assert re.fullmatch(CASE_ID, case["case_id"])
        assert case["category"] in {m.value for m in BenchmarkCategory}
        assert set(case.get("expected_tools", [])) <= TOOLS, case["case_id"]
        assert set(case.get("expected_behavior", [])) <= {b.value for b in ExpectedBehavior}
        assert case.get("expected_behavior") or case.get("numeric_from") or case.get("local"), case["case_id"]
        if case.get("expected_behavior") == ["must_clarify"]:
            assert case.get("clarification_answer"), case["case_id"]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_holds_no_values_or_file_names(path):
    text = path.read_text(encoding="utf-8")
    assert "expected_numeric" not in text and "expected_citations" not in text
    assert not re.search(r"\w\.(pdf|docx|pptx|xlsx|dat|csv|tdms|tex|json|py)\b", text, re.IGNORECASE)


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_numeric_from_points_to_telemetry_cases(path):
    telemetry = {c["case_id"] for c in load(bs.SUITES / "telemetry.template.yaml")["cases"] if "method" in c}
    for case in load(path)["cases"]:
        if "numeric_from" in case:
            assert case["numeric_from"] in telemetry, case["case_id"]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_built_suite_validates(path):
    template = load(path)
    built = bs.LOCAL / f"{template['suite']}.json"
    if not built.is_file():
        pytest.skip(f"{built.name} not built locally")
    suite = json.loads(built.read_text(encoding="utf-8"))
    assert [c["case_id"] for c in suite["cases"]] == [c["case_id"] for c in template["cases"]]
    for case, source in zip(suite["cases"], template["cases"], strict=True):
        CaseCreate.model_validate(case)
        if source.get("local"):
            assert set(case["spec"]) - {"expected_behavior", "expected_tools", "expected_numeric"}, case[
                "case_id"
            ]
