"""The Console's rules export must load through S1's `backend.review.rules.load_yaml`, unchanged.

The fixture is the exact text frontend/console/src/lib/components/review/rules_export.ts writes; the vitest
tests/review/rules_export.test.ts checks the Console still writes it."""

from pathlib import Path

from backend.review.rules import RuleType, load_rules_dir, load_yaml

FIXTURE = Path(__file__).resolve().parents[4] / "frontend/console/tests/review/rules_export.expected.yaml"
HEADER = (
    "# DCL operator rules exported from the Console at 2026-10-23T09:00:00Z; "
    "load with backend/review/rules.py load_yaml\n"
)


def test_the_console_export_loads_as_operator_rules(tmp_path):
    text = HEADER + FIXTURE.read_text(encoding="utf-8")
    rules = load_yaml(text).rules
    assert [(r.status, r.rule_type) for r in rules] == [
        ("operator", RuleType.UNIT_MAPPING),
        ("operator", RuleType.CHANNEL_MAP),
        ("operator", RuleType.IGNORE_PATTERN),
    ]
    assert rules[0].scope.scope_root == "APU Injector" and rules[0].scope.scope_filename_glob == "*.dat"
    assert rules[0].precedence == 10 and rules[0].created_by == "asha@manastuspace.com"
    assert rules[1].scope.scope_folder_id == "01RDWVU4ZUFFI75KMFFJEJNIOEECPJM6RB"
    assert (
        rules[1].body["channels"]["y0 (N2)"]["unit"] == "bar"
        and rules[1].body["ambient_pressure_bar_abs"] == 1.013
    )
    assert rules[2].body == {"reason": 'Kalibrierung: "alt" – ignore'}
    (tmp_path / "console_export.yaml").write_text(text, encoding="utf-8")
    assert len(load_rules_dir(tmp_path)) == 3  # dropped into config/rules/, all three load as operator rules
