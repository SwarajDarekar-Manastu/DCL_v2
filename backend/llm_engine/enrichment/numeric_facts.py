"""Layer 3 numeric facts (file 04 §1, §3.2, §8): numbers the enrichment located, validated by code.

For each grounded `NumericExtract`: parse the value locale-aware (`12,4` in a decimal-comma document is
12.4; `1.234` there is one thousand two hundred thirty-four only when the thousands pattern is confirmed,
otherwise the fact is `suspect`); parse the unit with S1's registry (`backend/common/units.py`); a unit pint
cannot read keeps the number with `needs_unit`; a unit whose dimension does not fit the quantity is dropped;
the value is converted to the canonical unit (`value_si`, `unit_si`); a value outside the sanity range
chosen for it by origin and role (`sanity_bounds`) is `suspect`. Facts from external documents get
`source = vendor_claim` or `literature` so the engine never treats them as measured (file 04 §2.3).

Nothing here writes to the database; S1's commit stores the returned `FactDecision`s.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from backend.common.units import UnitError, fits_quantity, parse_unit, to_canonical
from backend.llm_engine.enrichment.extract import NumericExtract
from backend.postgres.enums import DocKind, GaugeOrAbs, NodeSource, NumericFactSource, Quantity, SourceOrigin

LITERATURE_KINDS = frozenset(
    {
        DocKind.ACADEMIC_PAPER,
        DocKind.ARTICLE,
        DocKind.BOOK_EXCERPT,
        DocKind.CONFERENCE_PAPER,
        DocKind.STANDARD,
    }
)
NODE_SOURCE_TO_FACT = {
    NodeSource.PRINTED: NumericFactSource.PRINTED,
    NodeSource.OCR: NumericFactSource.OCR,
    NodeSource.VLM: NumericFactSource.VLM,
    NodeSource.STRUCTURED: NumericFactSource.TABLE,
    NodeSource.SOURCE_CODE: NumericFactSource.PRINTED,
    NodeSource.HUMAN: NumericFactSource.HUMAN,
}
SIGNS = str.maketrans({"−": "-", "–": "-", "+": ""})
NUMBER = re.compile(r"^-?(\d{1,3}(?:[.,\s']\d{3})+|\d+)(?:[.,](\d+))?$")


class NumberLocale(StrEnum):
    DOT = "dot"
    COMMA = "comma"


class DropReason(StrEnum):
    UNPARSEABLE_VALUE = "unparseable_value"
    DIMENSION_MISMATCH = "dimension_mismatch"


@dataclass(frozen=True)
class FactDecision:
    """One future `numeric_facts` row without ids; `node_ref` is resolved to a node id at commit."""

    node_ref: str
    quantity: Quantity
    value_raw: str
    unit_raw: str | None
    value_si: float | None
    unit_si: str | None
    gauge_or_abs: GaugeOrAbs
    context: str
    span_start: int | None
    span_end: int | None
    source: NumericFactSource
    suspect: bool
    needs_unit: bool
    confidence: float | None = None


@dataclass(frozen=True)
class DroppedFact:
    node_ref: str
    value: str
    unit: str | None
    reason: DropReason


def parse_number(value: str, locale: NumberLocale) -> tuple[float, bool]:
    """(number, ambiguous). Ambiguous (file 04 §8): a decimal-comma document's `1.234`, read as one thousand
    two hundred thirty-four, where the dot could also be a decimal mark from an English source."""
    text = value.strip().translate(SIGNS).replace(" ", " ")
    negative = text.startswith("-")
    text = text.lstrip("-").strip()
    decimal, thousands = (",", ".") if locale is NumberLocale.COMMA else (".", ",")
    if text.count(decimal) > 1 or not re.fullmatch(r"[\d.,\s']+", text):
        raise ValueError(f"not a number: {value!r}")
    ambiguous = False
    if decimal in text:
        whole, fraction = text.rsplit(decimal, 1)
    else:
        whole, fraction = text, ""
        groups = re.split(rf"[{re.escape(thousands)}\s']", whole)
        if locale is NumberLocale.COMMA and len(groups) == 2 and len(groups[1]) == 3:
            ambiguous = True
    groups = re.split(rf"[{re.escape(thousands)}\s']", whole)
    if len(groups) > 1 and (not 1 <= len(groups[0]) <= 3 or any(len(g) != 3 for g in groups[1:])):
        raise ValueError(f"thousands groups do not line up in {value!r}")
    number = float("".join(groups) + ("." + fraction if fraction else ""))
    return (-number if negative else number), ambiguous


def fact_source(node_source: NodeSource, origin: SourceOrigin | None, doc_kind: DocKind) -> NumericFactSource:
    if origin == SourceOrigin.EXTERNAL_KEPT:
        return (
            NumericFactSource.LITERATURE if doc_kind in LITERATURE_KINDS else NumericFactSource.VENDOR_CLAIM
        )
    return NODE_SOURCE_TO_FACT.get(node_source, NumericFactSource.PRINTED)


def role_of(quantity_label: str) -> str:
    """`chamber pressure` → `chamber_pressure`: the label in the snake_case form of the range ids."""
    return "_".join(re.findall(r"[a-z0-9]+", quantity_label.lower()))


def sanity_bounds(
    ranges: Iterable[Mapping[str, Any]], quantity: Quantity, *, external: bool, role: str | None = None
) -> tuple[float, float, str] | None:
    """[min, max] in canonical units for one fact (S5's rule in config/sanity_ranges.yaml):
    external_kept → the range marked `checks_external_kept`; internal → the range whose id names the fact's
    role (contained in the role, e.g. `chamber_pressure` in `peak_chamber_pressure`), else the last range of
    the quantity."""
    own = [r for r in ranges if r.get("physical_quantity") == quantity]
    if not own:
        return None
    if external:
        chosen = next((r for r in own if r.get("checks_external_kept")), own[-1])
    else:
        named = [r for r in own if role and str(r.get("id", "")) in role]
        chosen = max(named, key=lambda r: len(str(r["id"]))) if named else own[-1]
    low, unit = to_canonical(float(chosen["min"]), chosen["unit"])
    high, _ = to_canonical(float(chosen["max"]), chosen["unit"])
    return low, high, unit


def validate_fact(
    fact: NumericExtract,
    *,
    node_ref: str,
    node_text: str,
    locale: NumberLocale,
    source: NumericFactSource,
    ranges: Iterable[Mapping[str, Any]] = (),
    external: bool = False,
    confidence: float | None = None,
) -> FactDecision | DroppedFact:
    try:
        number, ambiguous = parse_number(fact.value, locale)
    except ValueError:
        return DroppedFact(node_ref, fact.value, fact.unit, DropReason.UNPARSEABLE_VALUE)
    span_start = node_text.find(fact.span) if fact.span else -1
    span = (span_start, span_start + len(fact.span)) if span_start >= 0 else (None, None)
    base = dict(
        node_ref=node_ref,
        quantity=fact.quantity,
        value_raw=fact.value,
        unit_raw=fact.unit,
        context=fact.context,
        span_start=span[0],
        span_end=span[1],
        source=source,
        confidence=confidence,
    )
    if fact.unit is None:
        return FactDecision(
            value_si=None,
            unit_si=None,
            gauge_or_abs=GaugeOrAbs.UNKNOWN,
            suspect=ambiguous,
            needs_unit=True,
            **base,
        )
    try:
        parsed = parse_unit(fact.unit)
    except UnitError:
        return FactDecision(
            value_si=None,
            unit_si=None,
            gauge_or_abs=GaugeOrAbs.UNKNOWN,
            suspect=ambiguous,
            needs_unit=True,
            **base,
        )
    if not fits_quantity(parsed, fact.quantity):
        return DroppedFact(node_ref, fact.value, fact.unit, DropReason.DIMENSION_MISMATCH)
    value_si, unit_si = to_canonical(number, parsed)
    bounds = sanity_bounds(ranges, fact.quantity, external=external, role=role_of(fact.quantity_label))
    out_of_range = bounds is not None and not bounds[0] <= value_si <= bounds[1]
    return FactDecision(
        value_si=value_si,
        unit_si=unit_si,
        gauge_or_abs=parsed.gauge_or_abs,
        suspect=ambiguous or out_of_range,
        needs_unit=False,
        **base,
    )
