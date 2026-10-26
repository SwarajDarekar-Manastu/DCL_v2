"""Answer verification (file 07 §8). This module holds the deterministic numeric check.

Every `numeric` claim must correspond, value as a string, to a tool result in the same trace (file 07 §7):
a rounded value must be rounded by the tool, not by the prose. A number with a unit in the claim must appear
in one tool output either with that unit right after it, or bare in an output that names the unit elsewhere —
a table names it once in its column header ("Max [barg]") and its cells hold bare numbers (user, 2026-10-26:
true table values were removed as "another unit"). Units compare through the unit registry, so `barg`,
`bar(g)` and `bar (g)` are one unit, while `bar`, `bara` and `K` are not `barg` and `°C` (a claim keeps the
source's gauge or absolute); a unit the registry cannot
read must match as a string. A bare number must appear as a bare token. The LLM entailment check (entailed /
contradicted / not_supported per claim) joins this module with the workflow (M8).
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from backend.common.units import UnitError, parse_unit, registry

NUMBER = r"[-+−]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?"
UNIT = r"(?:%|°\s?[CFK]|[A-Za-zµμΩ°][A-Za-z0-9µμΩ°/^·*_²³]*(?:\s?\([ag]\))?)"
VALUE = re.compile(rf"(?<![\w.,])({NUMBER})(?:\s?({UNIT}))?")
# a unit named apart from a number: in brackets ("Pressure [barg]", "(°C)") or as a word of its own
NAMED_UNIT = re.compile(rf"[\[(]\s*({UNIT})\s*[\])]|(?<![\w.])({UNIT})(?![\w])")
NOT_UNITS = frozenset(
    "a an and or to of on at in by for from over until between than then with per the was is are were "
    "after before during while times".split()
)


@dataclass(frozen=True)
class NumericMismatch:
    claim: str
    value: str
    unit: str | None
    reason: str


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("−", "-")


def numeric_values(text: str) -> list[tuple[str, str | None]]:
    """(value, unit) string pairs in reading order; the unit is the token right after the number, if any."""
    pairs = []
    for match in VALUE.finditer(_normalize(text)):
        unit = match.group(2)
        if unit and unit.lower() in NOT_UNITS:
            unit = None
        pairs.append((match.group(1), unit.replace(" ", "") if unit else None))
    return pairs


@lru_cache(maxsize=512)
def _parsed(unit: str):
    try:
        return parse_unit(unit)
    except UnitError:
        return None


def same_unit(a: str, b: str) -> bool:
    """One unit written two ways: same factor and offset in the registry, and no gauge/absolute clash."""
    if a == b:
        return True
    pa, pb = _parsed(a), _parsed(b)
    if pa is None or pb is None:
        return a.casefold() == b.casefold()
    if pa.dimension != pb.dimension:
        return False
    if pa.gauge_or_abs != pb.gauge_or_abs:  # a claim keeps the source's gauge or absolute, never adds one
        return False
    ureg = registry()
    try:
        one = ureg.Quantity(1.0, pa.unit).to(pb.unit).magnitude
        zero = ureg.Quantity(0.0, pa.unit).to(pb.unit).magnitude
    except Exception:  # noqa: BLE001 — pint raises several types; not convertible is not the same unit
        return False
    return abs(one - 1.0) < 1e-9 and abs(zero) < 1e-9


def _named_units(text: str) -> set[str]:
    return {(m.group(1) or m.group(2)).replace(" ", "") for m in NAMED_UNIT.finditer(_normalize(text))}


def check_numeric_claim(claim: str, tool_outputs: Iterable[str]) -> list[NumericMismatch]:
    """Every (value, unit) of the claim must occur in one tool output (see the module docstring); returns
    what does not."""
    outputs = [(numeric_values(o), _named_units(o)) for o in tool_outputs]
    bare_values = {value for pairs, _ in outputs for value, _ in pairs}
    mismatches = []
    for value, unit in numeric_values(claim):
        if unit:
            found = any(
                any(v == value and u and same_unit(unit, u) for v, u in pairs)
                or (any(v == value and not u for v, u in pairs) and any(same_unit(unit, n) for n in named))
                for pairs, named in outputs
            )
            if not found:
                reason = (
                    "value appears with another unit"
                    if value in bare_values
                    else "value not in any tool result"
                )
                mismatches.append(NumericMismatch(claim, value, unit, reason))
        elif value not in bare_values:
            mismatches.append(NumericMismatch(claim, value, None, "value not in any tool result"))
    return mismatches


def check_numeric_claims(claims: Iterable[str], tool_outputs: Iterable[str]) -> list[NumericMismatch]:
    outputs = list(tool_outputs)
    return [m for claim in claims for m in check_numeric_claim(claim, outputs)]
