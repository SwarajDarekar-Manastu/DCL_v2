"""config/sanity_ranges.yaml loads, its units match their dimensions, and the bounds catch
the unit mistakes they exist for."""

import jsonschema
import pytest

SCHEMA = {
    "type": "object",
    "required": ["version", "quantities"],
    "additionalProperties": False,
    "properties": {
        "version": {"const": 1},
        "quantities": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "required": ["dimension", "unit", "min", "max", "source", "sme_confirmed"],
                "additionalProperties": False,
                "properties": {
                    "dimension": {"type": "string"},
                    "unit": {"type": "string"},
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                    "source": {"type": "string", "minLength": 1},
                    "sme_confirmed": {"type": "boolean"},
                },
            },
        },
    },
}


@pytest.fixture(scope="module")
def ranges(load_config):
    return load_config("sanity_ranges.yaml")


@pytest.fixture(scope="module")
def in_range(ranges, ureg):
    def check(quantity, value, unit):
        r = ranges["quantities"][quantity]
        v = ureg.Quantity(value, unit).to(r["unit"]).magnitude
        return r["min"] <= v <= r["max"]
    return check


def test_schema(ranges):
    jsonschema.validate(ranges, SCHEMA)


def test_unit_parses_with_declared_dimension(ranges, ureg, sanity_quantity):
    r = ranges["quantities"][sanity_quantity]
    assert ureg.Quantity(1, r["unit"]).check(r["dimension"])
    assert r["min"] < r["max"]


def test_values_from_the_manual(ranges):
    # 03 §C.1 step 4: chamber pressure 0-150 bar, thrust 0-200 N, temperature 200-2,000 K,
    # mass flow 0-50 g/s.
    q = ranges["quantities"]
    names = ("chamber_pressure", "thrust", "temperature", "mass_flow")
    got = {k: (q[k]["min"], q[k]["max"], q[k]["unit"]) for k in names}
    assert got == {"chamber_pressure": (0, 150, "bar"), "thrust": (0, 200, "N"),
                   "temperature": (200, 2000, "K"), "mass_flow": (0, 50, "g/s")}


def test_bounds_accept_plausible_values(in_range):
    assert in_range("chamber_pressure", 12.4, "bar")
    assert in_range("chamber_pressure", 180, "psi")      # 12.4 bar
    assert in_range("temperature", 845, "K")
    assert in_range("temperature", 572, "degC")          # 845 K
    assert in_range("mass_flow", 0.012, "kg/s")


def test_bounds_reject_classic_unit_mistakes(in_range):
    assert not in_range("temperature", 25, "K")           # 25 °C logged as K
    assert not in_range("chamber_pressure", 2000, "bar")  # psi logged as bar
    assert not in_range("thrust", 450, "lbf")             # 2002 N
    assert not in_range("mass_flow", 12, "kg/s")          # g/s logged as kg/s
