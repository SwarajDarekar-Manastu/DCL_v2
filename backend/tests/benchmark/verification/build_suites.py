"""Build importable golden suites from committed templates plus local fragments (S5).

For every backend/tests/benchmark/suites/<suite>.template.yaml except telemetry (which has its own
builder, telemetry_metrics.py, because it computes values from raw files), this writes
data/benchmark/<suite>.json in S3's import format (POST /benchmark/suites/{suite}/import).

- Spec fragments that name company files or carry measured values come from the git-ignored
  data/benchmark/<suite>.local.yaml ({case_id: {spec keys}}); a case marked `local: true` must
  have one.
- `numeric_from: <telemetry case id>` copies expected_numeric from the built telemetry suite, so a
  measured value exists in one place only.

    uv run python backend/tests/benchmark/verification/build_suites.py
"""

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
SUITES = REPO / "backend/tests/benchmark/suites"
LOCAL = REPO / "data/benchmark"
SPEC_KEYS = ("expected_behavior", "clarification_answer", "paraphrases", "expected_entities", "language")
CASE_KEYS = {
    "case_id",
    "category",
    "question",
    "difficulty",
    "notes",
    "expected_tools",
    "numeric_from",
    "local",
    *SPEC_KEYS,
}


def templates() -> list[Path]:
    return sorted(p for p in SUITES.glob("*.template.yaml") if not p.name.startswith("telemetry."))


def telemetry_numeric() -> dict[str, list]:
    built = LOCAL / "telemetry.json"
    if not built.is_file():
        return {}
    return {
        c["case_id"]: c["spec"].get("expected_numeric", []) for c in json.loads(built.read_text())["cases"]
    }


def build(template: dict, local: dict, numeric: dict) -> dict:
    cases = []
    for case in template["cases"]:
        unknown = set(case) - CASE_KEYS
        if unknown:
            raise ValueError(f"{case['case_id']}: unknown keys {sorted(unknown)}")
        spec = {k: case[k] for k in SPEC_KEYS if k in case}
        if case.get("expected_tools"):
            spec["expected_tools"] = {"tools": case["expected_tools"], "ordered": False}
        if "numeric_from" in case:
            if case["numeric_from"] not in numeric:
                raise KeyError(f"{case['case_id']}: build the telemetry suite first ({case['numeric_from']})")
            spec["expected_numeric"] = numeric[case["numeric_from"]]
        if case.get("local"):
            if case["case_id"] not in local:
                raise KeyError(
                    f"{case['case_id']}: no fragment in data/benchmark/{template['suite']}.local.yaml"
                )
            spec.update(local[case["case_id"]])
        cases.append(
            {
                "case_id": case["case_id"],
                "suite": template["suite"],
                "category": case["category"],
                "status": "active",
                "question": case["question"],
                "difficulty": case.get("difficulty"),
                "notes": case.get("notes"),
                "spec": spec,
            }
        )
    return {"cases": cases}


def main(argv: list[str]) -> int:
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    from backend.benchmark.catalog import CaseCreate

    numeric = telemetry_numeric()
    for path in templates():
        template = yaml.safe_load(path.read_text(encoding="utf-8"))
        local_path = LOCAL / f"{template['suite']}.local.yaml"
        local = yaml.safe_load(local_path.read_text(encoding="utf-8")) if local_path.is_file() else {}
        suite = build(template, local or {}, numeric)
        for case in suite["cases"]:
            CaseCreate.model_validate(case)
        out = LOCAL / f"{template['suite']}.json"
        out.write_text(json.dumps(suite, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out} ({len(suite['cases'])} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
