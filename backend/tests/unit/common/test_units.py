"""Units: S5's aliases before pint, gauge/absolute from the spelling, canonical units, gauge → absolute."""

import pytest

from backend.common.units import (
    QUANTITY_DIMENSIONS,
    SEA_LEVEL_BAR_ABS,
    UnitError,
    aliases,
    ambient_bar_abs,
    fits_quantity,
    gauge_to_absolute,
    has_dimension,
    parse_unit,
    to_canonical,
)
from backend.postgres.enums import AmbientCondition, GaugeOrAbs, Quantity


@pytest.mark.parametrize(
    ("text", "reference"),
    [
        ("bar(g)", GaugeOrAbs.GAUGE),
        ("bar(a)", GaugeOrAbs.ABSOLUTE),
        ("psig", GaugeOrAbs.GAUGE),
        ("psia", GaugeOrAbs.ABSOLUTE),
        ("barg", GaugeOrAbs.GAUGE),
        ("ata", GaugeOrAbs.ABSOLUTE),
        ("atü", GaugeOrAbs.GAUGE),
        ("bar", GaugeOrAbs.UNKNOWN),
        ("kPa", GaugeOrAbs.UNKNOWN),
        ("kgf/cm2", GaugeOrAbs.UNKNOWN),
    ],
)
def test_pressure_reference_comes_from_the_spelling(text, reference):
    parsed = parse_unit(text)
    assert parsed.dimension == "[pressure]"
    assert parsed.gauge_or_abs == reference


def test_bar_g_is_a_pressure_never_bar_times_gram():
    assert has_dimension("bar(g)", "[pressure]")
    assert not has_dimension("bar(g)", "[pressure] * [mass]")


@pytest.mark.parametrize("text", ["°C", "°С", "℃", "degC", "deg C"])
def test_celsius_spellings_including_the_cyrillic_c(text):
    parsed = parse_unit(text)
    assert parsed.dimension == "[temperature]"
    assert parsed.gauge_or_abs == GaugeOrAbs.NOT_APPLICABLE
    assert to_canonical(25.0, parsed) == pytest.approx((298.15, "kelvin"))


@pytest.mark.parametrize(
    ("value", "unit", "expected", "canonical"),
    [
        (14.5038, "psi", 1.0, "bar"),
        (1.0, "kgf/cm2", 0.980665, "bar"),
        (100.0, "kPa", 1.0, "bar"),
        (1.0, "lbf", 4.448222, "newton"),
        (3.6, "kg/h", 1.0, "gram / second"),
        (0.5, "kW", 500.0, "watt"),
        (12.0, "mm", 0.012, "meter"),
    ],
)
def test_conversion_to_the_project_canonical_units(value, unit, expected, canonical):
    converted, unit_out = to_canonical(value, unit)
    assert converted == pytest.approx(expected, rel=1e-5)
    assert unit_out == canonical


def test_gauge_to_absolute_needs_a_known_ambient():
    assert ambient_bar_abs(AmbientCondition.SEA_LEVEL) == SEA_LEVEL_BAR_ABS
    assert ambient_bar_abs(AmbientCondition.AMBIENT_RECORDED, 0.95) == 0.95
    assert gauge_to_absolute(10.0, SEA_LEVEL_BAR_ABS) == pytest.approx(11.01325)
    for condition in (AmbientCondition.VACUUM_CHAMBER, AmbientCondition.UNKNOWN, None):
        with pytest.raises(UnitError):
            ambient_bar_abs(condition)


@pytest.mark.parametrize("text", ["", "   ", "frobnicators", "bar)("])
def test_unparsable_units_raise(text):
    with pytest.raises(UnitError):
        parse_unit(text)


def test_aliases_come_from_config_units_txt_longest_first():
    found = aliases()
    assert any(alias.surface == "bar(g)" and alias.expression == "barg" for alias in found)
    assert [len(a.surface) for a in found] == sorted((len(a.surface) for a in found), reverse=True)


@pytest.mark.parametrize(
    ("unit", "quantity", "fits"),
    [
        ("psig", Quantity.PRESSURE, True),
        ("N", Quantity.PRESSURE, False),
        ("g/s", Quantity.MASS_FLOW_RATE, True),
        ("slpm", Quantity.VOLUME_FLOW_RATE, False),
        ("s", Quantity.SPECIFIC_IMPULSE, True),
        ("%", Quantity.RATIO, True),
        ("mV", Quantity.VOLTAGE, True),
        ("furlong", Quantity.OTHER, True),
    ],
)
def test_units_are_checked_against_the_quantity_vocabulary(unit, quantity, fits):
    assert fits_quantity(unit, quantity) is fits


def test_every_quantity_has_a_dimension_entry():
    assert set(QUANTITY_DIMENSIONS) == set(Quantity)


@pytest.mark.parametrize(
    ("text", "dimension", "canonical", "value", "si"),
    [
        ("mV", "[electric_potential]", "volt", 2500.0, 2.5),
        ("V", "[electric_potential]", "volt", 4.5, 4.5),
        ("mA", "[current]", "ampere", 20.0, 0.02),
        ("kohm", "[resistance]", "ohm", 1.5, 1500.0),
        ("kHz", "[frequency]", "hertz", 1.0, 1000.0),
        ("kJ", "[energy]", "joule", 2.0, 2000.0),
    ],
)
def test_electrical_frequency_and_energy_units_are_named(text, dimension, canonical, value, si):
    parsed = parse_unit(text)
    assert (parsed.dimension, parsed.canonical) == (dimension, canonical)
    assert to_canonical(value, text) == pytest.approx((si, canonical))


@pytest.mark.parametrize("quantity", ["voltage", "current", "resistance", "frequency", "energy"])
def test_the_quantity_vocabulary_names_these_dimensions(quantity):
    from backend.postgres.enums import Quantity

    unit = {"voltage": "V", "current": "A", "resistance": "ohm", "frequency": "Hz", "energy": "J"}[quantity]
    assert (
        fits_quantity(unit, Quantity(quantity))
        and parse_unit(unit).dimension.strip("[]").replace("electric_potential", "voltage") == quantity
    )
