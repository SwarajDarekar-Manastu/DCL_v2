"""config/sanity_ranges.yaml loads, its units match their dimensions, channels select the right
range by physical_quantity and canonical name, and the bounds catch the unit mistakes they exist
for."""

from fnmatch import fnmatchcase

import jsonschema
import pytest

QUANTITY_DIMENSION = {
    "pressure": "[pressure]",
    "force": "[force]",
    "temperature": "[temperature]",
    "mass_flow_rate": "[mass] / [time]",
    "power": "[power]",
    "voltage": "[electric_potential]",
}
SCHEMA = {
    "type": "object",
    "required": ["version", "ranges"],
    "additionalProperties": False,
    "properties": {
        "version": {"const": 2},
        "ranges": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "physical_quantity",
                    "canonical_name_glob",
                    "dimension",
                    "unit",
                    "min",
                    "max",
                    "source",
                    "sme_confirmed",
                ],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                    "physical_quantity": {"enum": sorted(QUANTITY_DIMENSION)},
                    "canonical_name_glob": {"type": "string", "minLength": 1},
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
    return load_config("sanity_ranges.yaml")["ranges"]


@pytest.fixture(scope="module")
def range_for(ranges):
    """The matching rule documented in config/sanity_ranges.yaml: first match in file order."""

    def select(physical_quantity, canonical_name):
        for r in ranges:
            if r["physical_quantity"] == physical_quantity and fnmatchcase(
                canonical_name.casefold(), r["canonical_name_glob"].casefold()
            ):
                return r
        return None

    return select


@pytest.fixture(scope="module")
def in_range(ranges, ureg):
    by_id = {r["id"]: r for r in ranges}

    def check(range_id, value, unit):
        r = by_id[range_id]
        v = ureg.Quantity(value, unit).to(r["unit"]).magnitude
        return r["min"] <= v <= r["max"]

    return check


def test_schema(load_config):
    jsonschema.validate(load_config("sanity_ranges.yaml"), SCHEMA)


def test_ids_unique(ranges):
    ids = [r["id"] for r in ranges]
    assert len(ids) == len(set(ids))


def test_unit_and_dimension_agree_with_the_quantity(ranges, ureg):
    for r in ranges:
        assert r["dimension"] == QUANTITY_DIMENSION[r["physical_quantity"]], r["id"]
        assert ureg.Quantity(1, r["unit"]).check(r["dimension"]), r["id"]
        assert r["min"] < r["max"], r["id"]


def test_values_from_the_manual(ranges):
    # 03 §C.1 step 4: chamber pressure 0-150 bar, thrust 0-200 N, temperature 200-2,000 K,
    # mass flow 0-50 g/s.
    got = {r["id"]: (r["min"], r["max"], r["unit"]) for r in ranges}
    assert got == {
        "chamber_pressure": (0, 150, "bar"),
        "thrust": (0, 200, "N"),
        "temperature": (200, 2000, "K"),
        "mass_flow": (0, 50, "g/s"),
    }


@pytest.mark.parametrize(
    "physical_quantity, canonical_name, expected",
    [  # canonical names in S1's channel_map style (backend/review/rules.py)
        ("pressure", "pt_101_chamber_bar_abs", "chamber_pressure"),
        ("pressure", "PT_101_Chamber_bar_abs", "chamber_pressure"),
        ("pressure", "pt_102_feed_bar_abs", None),
        ("force", "thrust_n", "thrust"),
        ("temperature", "tc_bed_k", "temperature"),
        ("mass_flow_rate", "mdot_g_s", "mass_flow"),
        ("voltage", "valve_cmd_v", None),
        ("temperature", "thrust_n", "temperature"),  # quantity decides, not the name alone
    ],
)
def test_channels_select_the_right_range(range_for, physical_quantity, canonical_name, expected):
    r = range_for(physical_quantity, canonical_name)
    assert (r["id"] if r else None) == expected


def test_bounds_accept_plausible_values(in_range):
    assert in_range("chamber_pressure", 12.4, "bar")
    assert in_range("chamber_pressure", 180, "psi")  # 12.4 bar
    assert in_range("temperature", 845, "K")
    assert in_range("temperature", 572, "degC")  # 845 K
    assert in_range("mass_flow", 0.012, "kg/s")


def test_bounds_reject_classic_unit_mistakes(in_range):
    assert not in_range("temperature", 25, "K")  # 25 °C logged as K
    assert not in_range("chamber_pressure", 2000, "bar")  # psi logged as bar
    assert not in_range("thrust", 450, "lbf")  # 2002 N
    assert not in_range("mass_flow", 12, "kg/s")  # g/s logged as kg/s
