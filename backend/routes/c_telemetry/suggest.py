"""Suggested resolution for a telemetry ``UNIT_AMBIGUITY`` (file 06 §5: deterministic hints first).

A unit is proposed only when a file states it: the channel's own raw unit string, a sibling file's unit for
the same channel name, or a unit written in the channel name (``Thrust (N)``). Nothing is derived from a
scaling slope or a sensor list (decision 2026-10-22). Otherwise the suggestion says so explicitly and
carries the folder ``.cfg`` scaling as context, so the reviewer sees why no unit is proposed.
Confidence stays below the 0.9 auto-apply threshold: an operator always confirms.
"""

from backend.common.units import UnitError, parse_unit
from backend.dispatcher.contract import Flag, SetUnit, Suggestion, UnitTelemetryEvidence
from backend.postgres.enums import FlagType
from backend.routes.c_telemetry.tables import header_unit

RAW_UNIT = 0.6
SIBLING = 0.5
NAME = 0.4


def _set_unit(channel: str, text: str, confidence: float, rationale: str) -> Suggestion | None:
    try:
        parsed = parse_unit(text)
    except UnitError:
        return None
    return Suggestion(
        resolution=SetUnit(
            channel=channel,
            unit=text,
            quantity=parsed.dimension.strip("[]"),
            gauge_or_abs=parsed.gauge_or_abs,
        ),
        confidence=confidence,
        rationale=rationale,
    )


def suggest_unit(evidence: UnitTelemetryEvidence) -> Suggestion:
    channel = evidence.channel
    if evidence.raw_unit:
        found = _set_unit(channel, evidence.raw_unit, RAW_UNIT, f"the file states {evidence.raw_unit!r}")
        if found:
            return found
    same = [s for s in evidence.sibling_units if s.channel.casefold() == channel.casefold()]
    for sibling in same:
        found = _set_unit(
            channel, sibling.unit, SIBLING, f"{sibling.file_name} ({sibling.source}) states {sibling.unit!r}"
        )
        if found:
            return found
    named = header_unit(channel)
    if named:
        found = _set_unit(channel, named, NAME, f"the channel name {channel!r} states {named!r}")
        if found:
            return found
    context = []
    if evidence.scaling_equation:
        context.append(
            f"{evidence.scaling_source or 'the folder .cfg'} scales it as {evidence.scaling_equation!r} "
            "(engineering units, unit not stated)"
        )
    if evidence.sibling_units and not same:
        context.append(
            f"{len(evidence.sibling_units)} sibling units for other channel names are in the evidence"
        )
    return Suggestion(
        resolution=None,
        confidence=0,
        rationale="no suggestion: no file states a unit for this channel"
        + ("; " + "; ".join(context) if context else ""),
    )


def with_suggestion(flag: Flag) -> Flag:
    """The flag with a suggestion, when it is a telemetry UNIT_AMBIGUITY without one."""
    if (
        flag.flag_type != FlagType.UNIT_AMBIGUITY
        or flag.suggested_resolution is not None
        or not isinstance(flag.evidence, UnitTelemetryEvidence)
    ):
        return flag
    return flag.model_copy(update={"suggested_resolution": suggest_unit(flag.evidence)})
