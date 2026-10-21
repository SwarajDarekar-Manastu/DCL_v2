"""config/propellants.yaml loads, every card registers in RocketCEA, and RocketCEA reproduces
the published reference values within tolerance."""

import re

import jsonschema
import pytest

rocketcea = pytest.importorskip("rocketcea.cea_obj")

SCHEMA = {
    "type": "object",
    "required": ["version", "propellants"],
    "additionalProperties": False,
    "properties": {
        "version": {"const": 1},
        "propellants": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "kind",
                    "description",
                    "aliases",
                    "card",
                    "reference_checks",
                    "sme_confirmed",
                ],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^[A-Za-z0-9_]+$"},
                    "kind": {"enum": ["monopropellant", "oxidizer", "fuel"]},
                    "description": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "rocketcea_builtin_equivalent": {"type": "string"},
                    "card": {"type": "string"},
                    "reference_checks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "quantity",
                                "value",
                                "unit",
                                "conditions",
                                "tolerance_pct",
                                "source",
                            ],
                            "additionalProperties": False,
                            "properties": {
                                "quantity": {"enum": ["adiabatic_decomposition_temperature"]},
                                "value": {"type": "number"},
                                "unit": {"type": "string"},
                                "conditions": {"type": "string"},
                                "tolerance_pct": {"type": "number", "exclusiveMinimum": 0},
                                "source": {"type": "string", "minLength": 10},
                            },
                        },
                    },
                    "sme_confirmed": {"type": "boolean"},
                },
            },
        },
    },
}

ONE_ATM_PSIA = 14.6959
KEYWORD = {"monopropellant": "name", "oxidizer": "oxid", "fuel": "fuel"}


def register(p):
    add = {
        "monopropellant": rocketcea.add_new_propellant,
        "oxidizer": rocketcea.add_new_oxidizer,
        "fuel": rocketcea.add_new_fuel,
    }[p["kind"]]
    add(p["id"], p["card"])


@pytest.fixture(scope="module")
def data(load_config):
    return load_config("propellants.yaml")


def test_schema(data):
    jsonschema.validate(data, SCHEMA)


def test_ids_and_aliases_unique(data):
    props = data["propellants"]
    ids = [p["id"] for p in props]
    assert len(ids) == len(set(ids))
    aliases = [a.casefold() for p in props for a in p["aliases"]]
    assert len(aliases) == len(set(aliases))


def test_card_mass_fractions_sum_to_100(propellant):
    fractions = [float(x) for x in re.findall(r"wt%=\s*([0-9.]+)", propellant["card"])]
    assert fractions and sum(fractions) == pytest.approx(100.0)
    for line in propellant["card"].strip().splitlines():
        assert line.split()[0] in (KEYWORD[propellant["kind"]],) or line.startswith("h,cal="), line


def test_card_matches_rocketcea_builtin_thermo_data(propellant):
    if "rocketcea_builtin_equivalent" not in propellant:
        pytest.skip("no built-in equivalent")
    builtin = " ".join(rocketcea.oxCards[propellant["rocketcea_builtin_equivalent"]])

    def numbers(key, text):
        return [float(v) for v in re.findall(key + r"=\s*(-?[0-9.]+)", text)]

    assert numbers("h,cal", propellant["card"]) == numbers("h,cal", builtin)
    assert numbers("wt%", propellant["card"]) == numbers("wt%", builtin)


def test_rocketcea_reproduces_reference_values(propellant):
    register(propellant)
    cea = rocketcea.CEA_Obj(propName=propellant["id"])
    for check in propellant["reference_checks"]:
        assert check["quantity"] == "adiabatic_decomposition_temperature" and check["unit"] == "K"
        tc_k = cea.get_Tcomb(Pc=ONE_ATM_PSIA) / 1.8  # RocketCEA returns degrees Rankine
        assert tc_k == pytest.approx(check["value"], rel=check["tolerance_pct"] / 100), (
            f"{propellant['id']}: RocketCEA {tc_k:.1f} K vs published {check['value']} K"
        )
