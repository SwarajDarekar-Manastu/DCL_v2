"""What a table column (or a row label) measures, and its unit, with a confidence (plan step B, 2026-10-26).

Every route used to ask only "is this column numeric?" and then "does its header carry a unit?", each with
its own exception lists. So coefficients, rating scales, dates and file lists were flagged, and any short
token pint accepts was taken as the unit (``[ C ]`` became coulomb, ``(S × L)`` siemens × litre). One reader
now does it for every route, in this order:

1. Identify the column from its name: a physical quantity (the ``Quantity`` vocabulary), a unitless quantity
   (ratio, coefficient, efficiency, percentage, a rating or a "(1-5)" scale), not a measurement (an ID, date,
   count or reference), or unknown when the name says nothing. A misspelt word is read as the vocabulary word
   it nearly spells (``closest_word``: one edit for 5-7 letters, two from 8, a swap of two letters counting as
   one; never for 4 letters or fewer). The reading then says so (``read_as``) and its confidence drops by the
   match score, so a flag shows the reviewer what the name was taken for.
2. Look for its unit wherever one is stated: the brackets of the name, a unit written as a word, the same
   column name in other tables (``same_name``). A unit counts only when its dimension fits what the column
   measures; a symbol that fits only through that meaning is read that way (``C`` under "temperature" → degC).
3. Without a stated unit, a physical quantity gets the lab's usual unit as a guess below the threshold.

A name the vocabulary does not know is never guessed: it reads as unknown and goes to a person, with any
bracketed symbol the unit list cannot read named in ``unread`` (add it to ``config/units.txt``). A person's
answer is learned through ``same_name``: the units and "no unit" decisions on other tables' columns of the
same name (``pipeline.table_units_elsewhere``), an empty string meaning "no unit needed".

``UnitReading.settled`` is what the flag check asks: a unit at or above ``UNIT_CONFIDENCE_MIN`` (the user's
threshold), or a column that takes no unit. A physical quantity or an unknown column that is not settled is
for a person, with the guess filled in.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from backend.common.units import QUANTITY_DIMENSIONS, UnitError, fits_quantity, parse_unit
from backend.postgres.enums import Quantity

UNIT_CONFIDENCE_MIN = 0.75


class ColumnKind(StrEnum):
    QUANTITY = "quantity"
    UNITLESS = "unitless"
    NOT_MEASUREMENT = "not_measurement"
    UNKNOWN = "unknown"


# Confidence by where the unit was found (plan step B table)
STATED = 0.95  # a symbol whose dimension fits the column's words
STATED_ALONE = 0.9  # a symbol with a usual dimension, in a column whose name names no quantity
READ_BY_MEANING = 0.9  # a symbol that fits only through the column's meaning: "[ C ]" under temperature
WRITTEN = 0.9  # a unit written as a word: "Temperature in Celsius"
SAME_NAME = 0.8  # every other table that states this column name agrees on one unit
USUAL = 0.5  # only the column's words: the lab's usual unit, a guess for a person to confirm

QUANTITY_WORDS: dict[str, Quantity] = {
    "pressure": Quantity.PRESSURE,
    "press": Quantity.PRESSURE,
    "pt": Quantity.PRESSURE,
    "temperature": Quantity.TEMPERATURE,
    "temp": Quantity.TEMPERATURE,
    "preheat": Quantity.TEMPERATURE,
    "pre heat": Quantity.TEMPERATURE,
    "thermocouple": Quantity.TEMPERATURE,
    "thrust": Quantity.FORCE,
    "force": Quantity.FORCE,
    "load": Quantity.FORCE,
    "mass flow": Quantity.MASS_FLOW_RATE,
    "mass flow rate": Quantity.MASS_FLOW_RATE,
    "mfr": Quantity.MASS_FLOW_RATE,
    "volume flow": Quantity.VOLUME_FLOW_RATE,
    "volumetric flow": Quantity.VOLUME_FLOW_RATE,
    "duration": Quantity.TIME,
    "time": Quantity.TIME,
    "voltage": Quantity.VOLTAGE,
    "current": Quantity.CURRENT,
    "power": Quantity.POWER,
    "energy": Quantity.ENERGY,
    "resistance": Quantity.RESISTANCE,
    "frequency": Quantity.FREQUENCY,
    "mass": Quantity.MASS,
    "weight": Quantity.MASS,
    "length": Quantity.LENGTH,
    "diameter": Quantity.LENGTH,
    "thickness": Quantity.LENGTH,
    "width": Quantity.LENGTH,
    "height": Quantity.LENGTH,
    "depth": Quantity.LENGTH,
    "distance": Quantity.LENGTH,
    "radius": Quantity.LENGTH,
    "area": Quantity.AREA,
    "volume": Quantity.VOLUME,
    "density": Quantity.DENSITY,
    "velocity": Quantity.VELOCITY,
    "speed": Quantity.VELOCITY,
    "acceleration": Quantity.ACCELERATION,
    "specific impulse": Quantity.SPECIFIC_IMPULSE,
    "isp": Quantity.SPECIFIC_IMPULSE,
    "angle": Quantity.ANGLE,
}
# Quantities whose number has no unit: ratios, coefficients and ratings (and the symbols written for them)
UNITLESS_WORDS = frozenset(
    {
        "ratio", "coefficient", "coeff", "efficiency", "factor", "fraction", "percentage", "percent",
        "c f", "cf", "o f", "mach", "valve state", "duty cycle", "score", "rating", "rank", "rpn",
        "likelihood", "severity", "occurrence", "detection", "probability",
    }
)  # fmt: skip
# Columns that number or date things instead of measuring them, whatever else the name says
NOT_MEASUREMENT_WORDS = frozenset(
    {"id", "no", "nr", "number", "serial", "date", "year", "revision", "rev", "edition", "version", "index"}
)
# Words that label or count things; they decide only when the name names no quantity ("Part Temperature")
LABEL_WORDS = frozenset(
    {
        "test", "run", "step", "item", "location", "sensor", "instrument", "vendor", "specification",
        "description", "file", "part", "link", "exists", "status", "remarks", "comment", "name", "sample",
        "count", "qty",
    }
)  # fmt: skip
# A one-letter symbol is trusted alone only when it is one of these; "C", "F" or "c" need the column's words
ONE_LETTER_UNITS = frozenset({"N", "V", "A", "W", "K", "s", "m", "g", "J", "h"})
# Names a program made up for an unnamed column: they mean nothing elsewhere
PLACEHOLDER = re.compile(r"^column \d+$")
# Symbols that fit a quantity only through its meaning
BY_MEANING: dict[Quantity, dict[str, str]] = {
    Quantity.TEMPERATURE: {"c": "degC", "f": "degF", "°": "degC"},
}
UNIT_WORDS: dict[str, str] = {
    "celsius": "degC",
    "centigrade": "degC",
    "fahrenheit": "degF",
    "kelvin": "K",
    "bar": "bar",
    "barg": "barg",
    "bara": "bara",
    "psi": "psi",
    "pascal": "Pa",
    "newton": "N",
    "newtons": "N",
    "second": "s",
    "seconds": "s",
    "minute": "min",
    "minutes": "min",
    "hour": "h",
    "hours": "h",
    "volt": "V",
    "volts": "V",
    "ampere": "A",
    "amperes": "A",
    "amps": "A",
    "watt": "W",
    "watts": "W",
    "hertz": "Hz",
    "gram": "g",
    "grams": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "millimetre": "mm",
    "millimeter": "mm",
    "millimetres": "mm",
    "millimeters": "mm",
    "metre": "m",
    "meter": "m",
    "metres": "m",
    "meters": "m",
}
USUAL_UNITS: dict[Quantity, str] = {
    Quantity.PRESSURE: "bar",
    Quantity.TEMPERATURE: "degC",
    Quantity.FORCE: "N",
    Quantity.MASS_FLOW_RATE: "g/s",
    Quantity.TIME: "s",
    Quantity.VOLTAGE: "V",
    Quantity.CURRENT: "A",
    Quantity.POWER: "W",
    Quantity.ENERGY: "J",
    Quantity.FREQUENCY: "Hz",
    Quantity.MASS: "g",
    Quantity.LENGTH: "mm",
    Quantity.VELOCITY: "m/s",
    Quantity.SPECIFIC_IMPULSE: "s",
    Quantity.ANGLE: "deg",
}
LATEX = (
    (re.compile(r"\$?\^\{?\\circ\}?\$?\s*"), "°"),
    (re.compile(r"\\textdegree(\{\})?\s*"), "°"),
    (re.compile(r"\\[,;:!]"), " "),
)
BRACKETS = re.compile(r"[\(\[]\s*([^\)\]]+?)\s*[\)\]]")
SCALE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*(?:-|–|to|…|\.\.)\s*-?\d+(?:\.\d+)?\s*$")
IN_UNIT = re.compile(r"\bin\s+(\S+)\s*$", re.IGNORECASE)
WORD = re.compile(r"[a-z0-9]+")
# Edits a misspelt word may be from a vocabulary word, by its length (a swap of two letters is one edit)
MAX_EDITS = ((4, 0), (7, 1), (10_000, 2))


@dataclass(frozen=True)
class UnitReading:
    kind: ColumnKind
    quantity: Quantity | None
    unit: str | None
    confidence: float
    basis: str  # stated, read_by_meaning, written, same_name, usual, unitless, not_measurement, none
    read_as: str = ""  # the misspelt words the name was read with: "'temeprature' as 'temperature' (0.91)"
    unread: tuple[str, ...] = ()  # bracketed symbols the unit list cannot read

    @property
    def explained(self) -> str:
        """The basis with what the reader corrected or could not read, for a flag or a suggestion."""
        parts = [self.basis]
        if self.read_as:
            parts.append(f"read {self.read_as}")
        if self.unread:
            parts.append("not a known unit: " + ", ".join(repr(u) for u in self.unread))
        return "; ".join(parts)

    @property
    def settled(self) -> bool:
        """Nothing for a person to decide: a confident unit, or a column that takes no unit."""
        if self.kind in (ColumnKind.UNITLESS, ColumnKind.NOT_MEASUREMENT):
            return True
        return self.unit is not None and self.confidence >= UNIT_CONFIDENCE_MIN

    @property
    def confident_unit(self) -> str | None:
        return self.unit if self.unit is not None and self.confidence >= UNIT_CONFIDENCE_MIN else None


def clean(label: str) -> str:
    """The label with LaTeX degree signs as ``°`` and line breaks as spaces."""
    text = " ".join(label.split())
    for pattern, replacement in LATEX:
        text = pattern.sub(replacement, text)
    return text.strip()


def name_of(label: str) -> str:
    """The label without its brackets, lower case, single-spaced: the key for the same column elsewhere."""
    return " ".join(BRACKETS.sub(" ", clean(label)).casefold().split())


def _words(name: str) -> list[str]:
    return WORD.findall(name.replace("°", " "))


def _phrases(words: list[str], vocabulary: Iterable[str]) -> list[str]:
    joined = f" {' '.join(words)} "
    return [p for p in vocabulary if f" {p} " in joined]


def edit_distance(a: str, b: str) -> int:
    """Insertions, deletions, substitutions and swaps of two neighbouring letters (optimal alignment)."""
    rows = [list(range(len(b) + 1))]
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            row[j] = min(rows[-1][j] + 1, row[j - 1] + 1, rows[-1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], rows[-2][j - 2] + 1)
        rows.append(row)
    return rows[-1][-1]


def _allowed_edits(length: int) -> int:
    return next(edits for limit, edits in MAX_EDITS if length <= limit)


def _vocabulary() -> tuple[str, ...]:
    words = {w for phrase in (*QUANTITY_WORDS, *UNITLESS_WORDS, *LABEL_WORDS) for w in phrase.split()}
    return tuple(sorted(words | NOT_MEASUREMENT_WORDS | set(UNIT_WORDS)))


VOCABULARY = _vocabulary()


@lru_cache(maxsize=4096)
def closest_word(word: str) -> tuple[str, float] | None:
    """The vocabulary word a misspelt word nearly spells, and the match score (1 - edits / length); the
    first in alphabetical order on a tie, so the answer never changes."""
    allowed = _allowed_edits(len(word))
    if word in VOCABULARY or allowed == 0:
        return None
    near = [(edit_distance(word, v), v) for v in VOCABULARY if abs(len(v) - len(word)) <= allowed]
    edits, best = min(near, default=(allowed + 1, ""))
    if edits > allowed:
        return None
    return best, round(1 - edits / max(len(word), len(best)), 2)


def _corrected(words: list[str]) -> tuple[list[str], list[tuple[str, str, float]]]:
    fixed, corrections = [], []
    for word in words:
        match = closest_word(word)
        if match is None:
            fixed.append(word)
        else:
            fixed.append(match[0])
            corrections.append((word, match[0], match[1]))
    return fixed, corrections


@dataclass(frozen=True)
class Identity:
    kind: ColumnKind
    quantity: Quantity | None = None
    corrections: tuple[tuple[str, str, float], ...] = ()  # (word, read as, score) that decided the kind

    @property
    def score(self) -> float:
        return min((c[2] for c in self.corrections), default=1.0)

    @property
    def read_as(self) -> str:
        return ", ".join(f"{w!r} as {v!r} ({sc:.2f})" for w, v, sc in self.corrections)


def identify(label: str) -> Identity:
    """What the column is, from its name alone (brackets read only for a "(1-5)" scale or a percentage)."""
    text = clean(label)
    if any(SCALE.match(b) for b in BRACKETS.findall(text)):
        return Identity(ColumnKind.UNITLESS, Quantity.RATIO)
    words, corrections = _corrected(_words(name_of(text)))

    def used(phrases: list[str]) -> tuple[tuple[str, str, float], ...]:
        decided = {w for p in phrases for w in p.split()}
        return tuple(c for c in corrections if c[1] in decided)

    if (found := _phrases(words, NOT_MEASUREMENT_WORDS)) or "#" in text:
        return Identity(ColumnKind.NOT_MEASUREMENT, None, used(found))
    if (found := _phrases(words, UNITLESS_WORDS)) or "%" in text:
        return Identity(ColumnKind.UNITLESS, Quantity.RATIO, used(found))
    if found := _phrases(words, QUANTITY_WORDS):
        phrase = max(found, key=len)
        return Identity(ColumnKind.QUANTITY, QUANTITY_WORDS[phrase], used([phrase]))
    if found := _phrases(words, LABEL_WORDS):
        return Identity(ColumnKind.NOT_MEASUREMENT, None, used(found))
    return Identity(ColumnKind.UNKNOWN)


def _usual_dimension(text: str) -> Quantity | None:
    """The quantity a unit measures, when it is one of the vocabulary's physical quantities."""
    try:
        parsed = parse_unit(text)
    except UnitError:
        return None
    for quantity, dimension in QUANTITY_DIMENSIONS.items():
        if dimension not in (None, "[]") and fits_quantity(parsed, quantity):
            return quantity
    return None


def _fit(text: str, quantity: Quantity | None) -> tuple[str, float, str, Quantity | None] | None:
    """``(unit, confidence, basis, quantity)`` when ``text`` reads as a unit of the column's quantity. Without
    a quantity to check against, only a usual dimension counts, and a one-letter symbol only a common one."""
    text = text.strip()
    if quantity is None:
        if len(text) == 1 and text not in ONE_LETTER_UNITS:
            return None
        for spelling in dict.fromkeys((text, text.lower()) if len(text) > 1 else (text,)):
            measured = _usual_dimension(spelling)
            if measured is not None:
                return spelling, STATED_ALONE, "stated", measured
        return None
    for spelling in dict.fromkeys((text, text.lower())):
        try:
            if fits_quantity(spelling, quantity):
                return spelling, STATED, "stated", quantity
        except UnitError:
            pass
    meaning = BY_MEANING.get(quantity or Quantity.OTHER, {}).get(text.strip().casefold())
    if meaning is not None:
        return meaning, READ_BY_MEANING, "read_by_meaning", quantity
    return None


def read_unit(label: str, *, same_name: Mapping[str, Iterable[str]] | None = None) -> UnitReading:
    """What the column named ``label`` measures and its unit. ``same_name`` maps a column name (``name_of``)
    to the units other tables state or a person decided for it ("" = no unit needed)."""
    text = clean(label)
    identity = identify(text)
    kind, quantity, score = identity.kind, identity.quantity, identity.score

    def reading(kind, quantity, unit, confidence, basis, unread=()) -> UnitReading:
        return UnitReading(
            kind, quantity, unit, round(confidence * score, 2), basis, identity.read_as, unread
        )

    if kind == ColumnKind.NOT_MEASUREMENT:
        return reading(kind, None, None, STATED, "not_measurement")
    brackets = list(reversed(BRACKETS.findall(text)))
    candidates = list(brackets)
    if (match := IN_UNIT.search(BRACKETS.sub(" ", text))) is not None:
        candidates.append(match.group(1))
    if "%" in text:
        return reading(ColumnKind.UNITLESS, Quantity.RATIO, "%", STATED, "stated")
    for candidate in candidates:
        found = _fit(candidate, quantity if kind == ColumnKind.QUANTITY else None)
        if found is not None:
            unit, confidence, basis, measured = found
            return reading(ColumnKind.QUANTITY, measured, unit, confidence, basis)
    unread = tuple(b for b in brackets if _unknown_symbol(b))
    if kind == ColumnKind.UNITLESS:
        return reading(kind, quantity, None, STATED, "unitless")
    for word in _words(name_of(text)):
        unit = UNIT_WORDS.get(word)
        if unit is not None and quantity is not None and fits_quantity(unit, quantity):
            return reading(kind, quantity, unit, WRITTEN, "written")
    name = name_of(text)
    decided = set((same_name or {}).get(name, ())) if not PLACEHOLDER.match(name) else set()
    if decided == {""}:  # people said "no unit needed" for this name elsewhere
        return reading(ColumnKind.UNITLESS, quantity, None, SAME_NAME, "same_name")
    others = decided - {""}
    readings = {_fit(u, quantity) for u in others}
    if others and "" not in decided and None not in readings and len({r[0] for r in readings}) == 1:
        unit, _, _, measured = next(iter(readings))
        return reading(ColumnKind.QUANTITY, measured, unit, SAME_NAME, "same_name")
    if quantity is not None and quantity in USUAL_UNITS:
        return reading(kind, quantity, USUAL_UNITS[quantity], USUAL, "usual", unread)
    return reading(kind, quantity, None, 0.0, "none", unread)


def _unknown_symbol(text: str) -> bool:
    """A short bracketed token that looks like a unit symbol but the unit list cannot read ("sccm")."""
    token = text.strip()
    if (
        not token
        or len(token) > 12
        or SCALE.match(token)
        or " " in token
        or not re.search(r"[^\W\d_]", token)
    ):
        return False
    try:
        parse_unit(token)
    except UnitError:
        return True
    return False
