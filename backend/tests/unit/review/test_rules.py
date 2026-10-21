"""Rules: scope matching, the four-step precedence, typed bodies, YAML export of operator rules."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.postgres.enums import RuleOrigin, RuleType
from backend.review.api_models import RuleDraft
from backend.review.rules import (
    ExportedRule,
    RuleRecord,
    RuleScope,
    RuleTarget,
    export_yaml,
    load_yaml,
    matches,
    parse_body,
    resolve,
)

T0 = datetime(2026, 10, 21, tzinfo=UTC)
TARGET = RuleTarget(
    root_name="APU Injector",
    folder_ids=["F-PRESSURE", "F-TP30", "F-ROOT"],
    file_name="TP30_T01.dat",
    extension=".dat",
)


def rule(name, origin=RuleOrigin.OPERATOR, precedence=0, age_days=0, rule_type=RuleType.CHANNEL_MAP, **scope):
    return RuleRecord(
        rule_id=uuid.uuid5(uuid.NAMESPACE_URL, name),
        rule_type=rule_type,
        origin=origin,
        scope=RuleScope(**scope),
        precedence=precedence,
        created_at=T0 - timedelta(days=age_days),
    )


def winner(*rules):
    found = resolve(rules, TARGET, RuleType.CHANNEL_MAP)
    return (
        None
        if found is None
        else next(n for n in "abcdefgh" if uuid.uuid5(uuid.NAMESPACE_URL, n) == found.rule_id)
    )


# ---------- matching ----------


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ({}, True),
        ({"scope_root": "APU Injector"}, True),
        ({"scope_root": "APU"}, False),
        ({"scope_folder_id": "F-TP30"}, True),
        ({"scope_folder_id": "F-OTHER"}, False),
        ({"scope_filename_glob": "tp30_*.DAT"}, True),
        ({"scope_filename_glob": "*.csv"}, False),
        ({"scope_extension": "DAT"}, True),
        ({"scope_extension": ".csv"}, False),
        ({"scope_folder_id": "F-PRESSURE", "scope_filename_glob": "*.csv"}, False),
    ],
)
def test_a_rule_applies_only_when_every_scope_column_it_sets_matches(scope, expected):
    assert matches(rule("a", **scope), TARGET) is expected


def test_inactive_and_other_type_rules_never_apply():
    inactive = RuleRecord(**{**rule("a").__dict__, "active": False})
    assert not matches(inactive, TARGET)
    assert resolve([rule("a", rule_type=RuleType.UNIT_MAPPING)], TARGET, RuleType.CHANNEL_MAP) is None


# ---------- precedence ----------


def test_nearer_folder_beats_ancestor_beats_root_beats_global():
    assert winner(rule("a"), rule("b", scope_root="APU Injector")) == "b"
    assert winner(rule("b", scope_root="APU Injector"), rule("c", scope_folder_id="F-ROOT")) == "c"
    assert winner(rule("c", scope_folder_id="F-ROOT"), rule("d", scope_folder_id="F-PRESSURE")) == "d"


def test_within_a_folder_a_filename_glob_then_an_extension_is_more_specific():
    folder = rule("a", scope_folder_id="F-PRESSURE")
    with_ext = rule("b", scope_folder_id="F-PRESSURE", scope_extension=".dat")
    with_glob = rule("c", scope_folder_id="F-PRESSURE", scope_filename_glob="TP30_T0*.dat")
    assert winner(folder, with_ext) == "b"
    assert winner(with_ext, with_glob) == "c"


def test_a_folder_beats_a_root_wide_filename_glob():
    assert (
        winner(
            rule("a", scope_root="APU Injector", scope_filename_glob="*.dat"),
            rule("b", scope_folder_id="F-ROOT"),
        )
        == "b"
    )


def test_operator_beats_derived_at_equal_specificity_but_not_a_more_specific_derived_rule():
    cfg = rule("a", origin=RuleOrigin.CFG, scope_folder_id="F-PRESSURE")
    operator = rule("b", origin=RuleOrigin.OPERATOR, scope_folder_id="F-PRESSURE")
    assert winner(cfg, operator) == "b"
    operator_on_parent = rule("c", origin=RuleOrigin.OPERATOR, scope_folder_id="F-TP30")
    assert winner(cfg, operator_on_parent) == "a"


def test_precedence_then_newest_break_the_remaining_ties():
    assert winner(rule("a", precedence=5), rule("b", precedence=1)) == "a"
    assert winner(rule("a", age_days=3), rule("b", age_days=1)) == "b"


# ---------- bodies ----------

CHANNEL_MAP = {
    "channels": {
        "AIN0": {
            "canonical_name": "pt_101_chamber_bar_g",
            "physical_quantity": "pressure",
            "unit": "psi",
            "gauge_or_abs": "gauge",
            "scaling": {"slope": 50, "offset": -25},
            "sensor_tag": "PT-101",
            "range_min": 0,
            "range_max": 250,
        },
        "AIN1": {"canonical_name": "tc_bed_k", "physical_quantity": "temperature", "unit": "K"},
    },
    "ambient_condition": "SEA_LEVEL",
}


def test_channel_map_body_parses_and_refuses_two_conversions():
    body = parse_body(RuleType.CHANNEL_MAP, CHANNEL_MAP)
    assert body.channels["AIN0"].scaling.slope == 50
    assert body.channels["AIN1"].scaling is None
    bad = {"channels": {"AIN0": {**CHANNEL_MAP["channels"]["AIN0"], "expression": "val * 2"}}}
    with pytest.raises(ValidationError, match="scaling or expression"):
        parse_body(RuleType.CHANNEL_MAP, bad)


def test_rule_draft_validates_its_body_by_rule_type():
    unit = {"channel": "AIN0", "unit": "psig", "quantity": "pressure", "gauge_or_abs": "gauge"}
    assert RuleDraft(rule_type=RuleType.UNIT_MAPPING, scope=RuleScope(scope_folder_id="F"), body=unit)
    with pytest.raises(ValidationError):
        RuleDraft(rule_type=RuleType.SCHEMA_MAPPING, scope=RuleScope(), body=unit)


# ---------- YAML export ----------


def test_yaml_export_keeps_only_operator_rules_and_loads_back():
    operator = ExportedRule(
        rule_type=RuleType.CHANNEL_MAP,
        scope=RuleScope(scope_folder_id="F-PRESSURE"),
        body=CHANNEL_MAP,
        created_by="reviewer@manastuspace.com",
    )
    derived = ExportedRule(
        rule_type=RuleType.CHANNEL_MAP, scope=RuleScope(scope_folder_id="F-X"), body=CHANNEL_MAP
    )
    text = export_yaml([(RuleOrigin.OPERATOR, operator), (RuleOrigin.CFG, derived)])
    loaded = load_yaml(text)
    assert loaded.version == 1
    assert loaded.rules == [operator]
    assert "F-X" not in text
