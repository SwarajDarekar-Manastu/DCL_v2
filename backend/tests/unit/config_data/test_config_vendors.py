"""config/vendors.yaml loads; aliases and domains are unambiguous; short aliases are case-sensitive."""

import re

import jsonschema
import pytest

SCHEMA = {
    "type": "object",
    "required": ["version", "vendors"],
    "additionalProperties": False,
    "properties": {
        "version": {"const": 1},
        "vendors": {"type": "array", "minItems": 1, "items": {
            "type": "object",
            "required": ["id", "name", "aliases", "domains", "category", "internal_equipment",
                         "sme_confirmed"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                "name": {"type": "string", "minLength": 2},
                "aliases": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 2}},
                "case_sensitive_aliases": {"type": "array", "items": {"type": "string"}},
                "domains": {"type": "array", "items": {"type": "string"}},
                "category": {"enum": ["propulsion", "sensors", "fluidics", "daq_software", "materials",
                                      "chemicals"]},
                "internal_equipment": {"type": "boolean"},
                "sme_confirmed": {"type": "boolean"},
            }}},
    },
}

DOMAIN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")


@pytest.fixture(scope="module")
def data(load_config):
    return load_config("vendors.yaml")


@pytest.fixture(scope="module")
def vendors(data):
    return data["vendors"]


def test_schema(data):
    jsonschema.validate(data, SCHEMA)


def test_ids_unique(vendors):
    ids = [v["id"] for v in vendors]
    assert len(ids) == len(set(ids))


def test_alias_belongs_to_one_vendor(vendors):
    seen = {}
    for v in vendors:
        for a in v["aliases"]:
            assert seen.setdefault(a.casefold(), v["id"]) == v["id"], f"{a!r} shared"


def test_short_aliases_are_case_sensitive(vendors):
    for v in vendors:
        cs = set(v.get("case_sensitive_aliases", []))
        assert cs <= set(v["aliases"]), v["id"]
        for a in v["aliases"]:
            if len(a) < 4:
                assert a in cs, f"{v['id']}: short alias {a!r} must be listed in case_sensitive_aliases"


def test_domains_are_bare_and_unique(vendors):
    seen = set()
    for v in vendors:
        for d in v["domains"]:
            assert DOMAIN.match(d), d
            assert d not in seen, d
            seen.add(d)


def test_test_equipment_vendors_are_marked_internal(vendors):
    by_id = {v["id"]: v for v in vendors}
    for vid in ("labjack", "national_instruments", "kistler", "swagelok"):
        assert by_id[vid]["internal_equipment"] is True
