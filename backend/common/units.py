"""Units for every number the pipeline normalizes (file 03 §C.1, file 04 §8, file 05 §2).

One pint registry: pint's defaults plus S5's ``config/units.txt``. Before pint sees a unit
string, the file's surface aliases (``#= <surface> => <expr> | <dimension>``) are applied,
longest surface first, as exact substring replacements, because pint parses some spellings
wrongly (``bar(g)`` would be bar × gram).

pint carries no gauge/absolute reference. The reference is read from the spelling
(``psig``, ``barg``, ``atü`` → gauge; ``psia``, ``bara``, ``ata`` → absolute) and gauge values
are converted to absolute here, with the run's ambient pressure, into a separate value.

Canonical units are the ones the Parquet column names and the sanity ranges use (file 05
§2): pressure bar, force N, temperature K, mass flow g/s, power W; anything else base SI.
"""

import re
import tokenize
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pint

from backend.postgres.enums import AmbientCondition, GaugeOrAbs, Quantity

UNITS_FILE = Path(__file__).resolve().parents[2] / "config" / "units.txt"
ALIAS_LINE = re.compile(r"^#=\s*(?P<surface>.+?)\s*=>\s*(?P<expr>.+?)\s*\|\s*(?P<dimension>\S.*?)\s*$")
SEA_LEVEL_BAR_ABS = 1.01325

GAUGE_UNITS = frozenset({"psig", "barg", "atu", "atü"})
ABSOLUTE_UNITS = frozenset({"psia", "bara", "ata"})
CANONICAL_UNITS = {
    "[pressure]": "bar",
    "[force]": "newton",
    "[temperature]": "kelvin",
    "[mass] / [time]": "gram / second",
    "[power]": "watt",
}
NAMED_DIMENSIONS = (
    *CANONICAL_UNITS,
    "[length]",
    "[mass]",
    "[time]",
    "[current]",
    "[electric_potential]",
    "[energy]",
)


QUANTITY_DIMENSIONS: dict[Quantity, str | None] = {
    Quantity.PRESSURE: "[pressure]",
    Quantity.FORCE: "[force]",
    Quantity.TEMPERATURE: "[temperature]",
    Quantity.MASS_FLOW_RATE: "[mass] / [time]",
    Quantity.VOLUME_FLOW_RATE: "[volume] / [time]",
    Quantity.POWER: "[power]",
    Quantity.ENERGY: "[energy]",
    Quantity.VOLTAGE: "[electric_potential]",
    Quantity.CURRENT: "[current]",
    Quantity.RESISTANCE: "[resistance]",
    Quantity.LENGTH: "[length]",
    Quantity.AREA: "[area]",
    Quantity.VOLUME: "[volume]",
    Quantity.MASS: "[mass]",
    Quantity.DENSITY: "[density]",
    Quantity.TIME: "[time]",
    Quantity.FREQUENCY: "[frequency]",
    Quantity.VELOCITY: "[velocity]",
    Quantity.ACCELERATION: "[acceleration]",
    Quantity.SPECIFIC_IMPULSE: "[time]",
    Quantity.ANGLE: "[]",
    Quantity.RATIO: "[]",
    Quantity.VALVE_STATE: "[]",
    Quantity.OTHER: None,
}


class UnitError(ValueError):
    pass


@dataclass(frozen=True)
class UnitAlias:
    surface: str
    expression: str
    dimension: str


@dataclass(frozen=True)
class ParsedUnit:
    text: str
    expression: str
    unit: pint.Unit
    dimension: str
    gauge_or_abs: GaugeOrAbs

    @property
    def canonical(self) -> str:
        return CANONICAL_UNITS.get(self.dimension) or str(
            registry().Quantity(1, self.unit).to_base_units().units
        )


@lru_cache(maxsize=1)
def registry() -> pint.UnitRegistry:
    ureg = pint.UnitRegistry()
    ureg.load_definitions(str(UNITS_FILE))
    return ureg


@lru_cache(maxsize=1)
def aliases() -> tuple[UnitAlias, ...]:
    found = []
    for line in UNITS_FILE.read_text(encoding="utf-8").splitlines():
        match = ALIAS_LINE.match(line)
        if match:
            found.append(UnitAlias(match["surface"], match["expr"], match["dimension"]))
    return tuple(sorted(found, key=lambda alias: len(alias.surface), reverse=True))


def apply_aliases(text: str) -> str:
    for alias in aliases():
        text = text.replace(alias.surface, alias.expression)
    return text


def _dimension_name(unit: pint.Unit) -> str:
    """``[pressure]``-style name when the unit has a named dimension, else pint's base dimensionality."""
    ureg = registry()
    dimensionality = ureg.get_dimensionality(unit)
    for name in NAMED_DIMENSIONS:
        if dimensionality == ureg.get_dimensionality(name):
            return name
    return str(dimensionality)


def _reference(expression: str, dimension: str) -> GaugeOrAbs:
    names = set(re.findall(r"[^\W\d_]+", expression))
    if names & GAUGE_UNITS:
        return GaugeOrAbs.GAUGE
    if names & ABSOLUTE_UNITS:
        return GaugeOrAbs.ABSOLUTE
    return GaugeOrAbs.UNKNOWN if dimension == "[pressure]" else GaugeOrAbs.NOT_APPLICABLE


def parse_unit(text: str) -> ParsedUnit:
    """Parse a unit string from a header, a table cell or the LLM; refuses anything pint cannot read."""
    cleaned = text.strip()
    if not cleaned:
        raise UnitError("empty unit")
    expression = apply_aliases(cleaned)
    try:
        unit = registry().parse_units(expression)
    except (pint.PintError, ValueError, TypeError, SyntaxError, tokenize.TokenError) as exc:
        raise UnitError(f"cannot parse unit {text!r}") from exc
    dimension = _dimension_name(unit)
    return ParsedUnit(cleaned, expression, unit, dimension, _reference(expression, dimension))


def to_canonical(value: float, unit: str | ParsedUnit) -> tuple[float, str]:
    """``(value, unit)`` in the canonical unit of its dimension; gauge stays gauge (``gauge_to_absolute``)."""
    parsed = unit if isinstance(unit, ParsedUnit) else parse_unit(unit)
    target = parsed.canonical
    converted = registry().Quantity(value, parsed.unit).to(target)
    return float(converted.magnitude), str(converted.units)


def ambient_bar_abs(condition: AmbientCondition | None, recorded_bar_abs: float | None = None) -> float:
    """The reference a gauge reading is relative to. Only sea level has a default."""
    if recorded_bar_abs is not None:
        return recorded_bar_abs
    if condition == AmbientCondition.SEA_LEVEL:
        return SEA_LEVEL_BAR_ABS
    raise UnitError(
        f"no ambient pressure for {condition or 'an unknown ambient'}; a recorded value is needed"
    )


def gauge_to_absolute(value_bar_g: float, ambient: float) -> float:
    """Absolute pressure in bar from a gauge reading in bar; stored next to the gauge value, never over it."""
    return value_bar_g + ambient


def has_dimension(unit: str | ParsedUnit, dimension: str) -> bool:
    """True when ``unit`` has ``dimension`` (a name such as ``[pressure]`` or a pint expression)."""
    parsed = unit if isinstance(unit, ParsedUnit) else parse_unit(unit)
    ureg = registry()
    return ureg.get_dimensionality(parsed.unit) == ureg.get_dimensionality(dimension)


def fits_quantity(unit: str | ParsedUnit, quantity: Quantity) -> bool:
    """True when the unit's dimension is the one ``quantity`` expects (``other`` accepts any unit)."""
    expected = QUANTITY_DIMENSIONS[quantity]
    return expected is None or has_dimension(unit, expected)
