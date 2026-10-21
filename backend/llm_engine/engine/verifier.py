"""Answer verification (file 07 §8). This module holds the deterministic numeric check.

Every `numeric` claim must correspond exactly, value and unit as strings, to a tool result in the same
trace (file 07 §7): the verifier compares strings, so a rounded value must be rounded by the tool, not by
the prose. A number with a unit in the claim must appear with the same unit right after it in some tool
output; a bare number must appear as a bare token. The LLM entailment check (entailed / contradicted /
not_supported per claim) joins this module with the workflow (M8).
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

NUMBER = r"[-+−]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?"
UNIT = r"(?:%|°\s?[CFK]|[A-Za-zµμΩ°][A-Za-z0-9µμΩ°/^·*_²³]*(?:\s?\([ag]\))?)"
VALUE = re.compile(rf"(?<![\w.,])({NUMBER})(?:\s?({UNIT}))?")
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


def check_numeric_claim(claim: str, tool_outputs: Iterable[str]) -> list[NumericMismatch]:
    """Every (value, unit) of the claim must occur in a tool output; returns what does not."""
    available = [numeric_values(output) for output in tool_outputs]
    values_with_unit = {pair for pairs in available for pair in pairs if pair[1]}
    bare_values = {value for pairs in available for value, _ in pairs}
    mismatches = []
    for value, unit in numeric_values(claim):
        if unit and (value, unit) not in values_with_unit:
            reason = (
                "value appears with another unit" if value in bare_values else "value not in any tool result"
            )
            mismatches.append(NumericMismatch(claim, value, unit, reason))
        elif not unit and value not in bare_values:
            mismatches.append(NumericMismatch(claim, value, None, "value not in any tool result"))
    return mismatches


def check_numeric_claims(claims: Iterable[str], tool_outputs: Iterable[str]) -> list[NumericMismatch]:
    outputs = list(tool_outputs)
    return [m for claim in claims for m in check_numeric_claim(claim, outputs)]
