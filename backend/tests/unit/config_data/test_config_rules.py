"""Proposed operator rules in config/rules/proposed/ (Lead ruling 2026-10-22): valid for S1's
loader, marked as proposals, and consistent with the units registry and the sanity ranges."""

from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from backend.postgres.enums import RuleType
from backend.review.rules import ChannelMapBody, load_yaml

RULES = Path(__file__).resolve().parents[4] / "config" / "rules"
PROPOSED = sorted((RULES / "proposed").glob("*.yaml"))


def test_proposals_exist_and_nothing_is_confirmed_yet():
    assert len(PROPOSED) == 3
    # A file at the top level of config/rules/ is a confirmed operator rule; none exists yet.
    assert sorted(RULES.glob("*.yaml")) == []


@pytest.mark.parametrize("path", PROPOSED, ids=lambda p: p.name)
def test_proposal_loads_with_s1_loader_and_is_marked(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# PROPOSED")
    rules = load_yaml(text).rules
    assert rules and all(r.rule_type == RuleType.CHANNEL_MAP for r in rules)
    assert all("proposal" in (r.created_by or "") for r in rules)
    assert all(r.scope.scope_folder_id and r.scope.scope_root for r in rules)


@pytest.mark.parametrize("path", PROPOSED, ids=lambda p: p.name)
def test_units_parse_and_names_select_the_intended_sanity_range(path, ureg, load_config):
    ranges = load_config("sanity_ranges.yaml")["ranges"]

    def route_c_range(quantity, name):
        return next(
            (
                r["id"]
                for r in ranges
                if r["physical_quantity"] == quantity
                and fnmatchcase(name.casefold(), r["canonical_name_glob"])
            ),
            None,
        )

    intended = {
        "p_chamber": "chamber_pressure",
        "p_valve": "valve_pressure",
        "p_feed": "feed_pressure",
        "thrust": "thrust",
        "mdot": "mass_flow",
    }
    for rule in load_yaml(path.read_text(encoding="utf-8")).rules:
        body = ChannelMapBody.model_validate(rule.body)
        for raw, entry in body.channels.items():
            assert raw.startswith("y"), "LabJack v* columns are voltages and need no mapping"
            ureg.Quantity(1, entry.unit)
            prefix = next((p for p in intended if entry.canonical_name.startswith(p)), None)
            if prefix:
                assert route_c_range(entry.physical_quantity, entry.canonical_name) == intended[prefix], raw
