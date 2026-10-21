"""config/units.txt loads into pint and every alias resolves to its declared dimension."""

import pint
import pytest

# 04 §8: "The project unit registry includes ..." — every one must parse (after aliases).
MANUAL_UNITS = [
    "psig",
    "psia",
    "bara",
    "barg",
    "kgf/cm²",
    "kp/cm²",
    "at",
    "atm",
    "mmHg",
    "Torr",
    "lbf",
    "°F",
    "kcal",
    "sccm",
    "slpm",
]


@pytest.mark.parametrize("unit", MANUAL_UNITS)
def test_manual_unit_list_parses(ureg, apply_unit_aliases, unit):
    assert ureg.Quantity(1, apply_unit_aliases(unit)).magnitude == 1


@pytest.mark.parametrize(
    "unit, pascal",
    [
        ("psig", 6894.757293168361),
        ("psia", 6894.757293168361),
        ("barg", 1e5),
        ("bara", 1e5),
        ("ata", 98066.5),
        ("atu", 98066.5),
        ("atü", 98066.5),
        ("Torr", 101325 / 760),
        ("kp/cm**2", 98066.5),
        ("kgf/cm**2", 98066.5),
    ],
)
def test_project_pressure_units_have_expected_magnitude(ureg, unit, pascal):
    assert ureg.Quantity(1, unit).to("Pa").magnitude == pytest.approx(pascal, rel=1e-12)


def test_lbm_and_sccm(ureg):
    assert ureg.Quantity(1, "lbm").to("kg").magnitude == pytest.approx(0.45359237)
    assert ureg.Quantity(1000, "sccm").to("slpm").magnitude == pytest.approx(1.0)


def test_alias_lines_exist_and_surfaces_are_unique(unit_aliases):
    surfaces = [a[0] for a in unit_aliases]
    assert len(surfaces) >= 30
    assert len(surfaces) == len(set(surfaces))


def test_alias_resolves_with_declared_dimension(ureg, apply_unit_aliases, unit_alias):
    surface, expr, dim = unit_alias
    q = ureg.Quantity(1, apply_unit_aliases(surface))
    assert q.check(dim), f"{surface!r} -> {expr!r} has {q.dimensionality}, expected {dim}"


def test_alias_target_is_left_unchanged(apply_unit_aliases, unit_alias):
    # A target must not contain a surface, or the replacement would rewrite it twice.
    _, expr, _ = unit_alias
    assert apply_unit_aliases(expr) == expr


def test_bar_g_is_misparsed_without_the_alias(ureg, apply_unit_aliases):
    # Why the alias exists: pint silently reads "bar(g)" as bar * gram.
    assert not ureg.Quantity(1, "bar(g)").check("[pressure]")
    assert ureg.Quantity(1, apply_unit_aliases("bar(g)")).check("[pressure]")


def test_degree_c_spellings(ureg, apply_unit_aliases, unit_aliases):
    surfaces = {a[0] for a in unit_aliases}
    assert "°С" in surfaces  # Cyrillic С, an OCR and copy-paste trap
    assert "°C" not in surfaces  # Latin °C is pint-native and must not be aliased
    for s in ("°C", "℃", "°С", "deg C"):
        assert ureg.Quantity(25, apply_unit_aliases(s)).to("K").magnitude == pytest.approx(298.15)


def test_gauge_reference_is_not_converted_by_pint(ureg):
    # 03 §C.1 step 3: gauge to absolute needs the ambient condition; pint must not add an offset.
    assert ureg.Quantity(10, "barg").to("bara").magnitude == pytest.approx(10)


def test_unknown_unit_still_raises(ureg):
    with pytest.raises(pint.UndefinedUnitError):
        ureg.Quantity(1, "furlongs_per_fortnight_gauge")
