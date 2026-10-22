"""UNIT_AMBIGUITY suggestions: a unit only when a file states it, else an explicit 'no suggestion'."""

from backend.dispatcher.contract import (
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    SiblingUnit,
    UnitTelemetryEvidence,
)
from backend.routes.c_telemetry.suggest import suggest_unit, with_suggestion


def _evidence(**kw) -> UnitTelemetryEvidence:
    return UnitTelemetryEvidence(**{"channel": "y3", **kw})


def test_raw_unit_wins():
    s = suggest_unit(
        _evidence(
            raw_unit="psig",
            sibling_units=[SiblingUnit(file_name="a.csv", channel="y3", unit="K", source="header")],
        )
    )
    assert (s.resolution.unit, s.resolution.quantity, s.resolution.gauge_or_abs, s.confidence) == (
        "psig",
        "pressure",
        "gauge",
        0.6,
    )


def test_sibling_unit_for_the_same_channel():
    s = suggest_unit(
        _evidence(
            channel="AI0",
            sibling_units=[SiblingUnit(file_name="run.csv", channel="ai0", unit="degC", source="header")],
        )
    )
    assert (s.resolution.channel, s.resolution.unit, s.resolution.quantity, s.confidence) == (
        "AI0",
        "degC",
        "temperature",
        0.5,
    )
    assert s.rationale == "run.csv (header) states 'degC'"


def test_unit_in_the_channel_name():
    s = suggest_unit(_evidence(channel="Thrust (N)"))
    assert (s.resolution.unit, s.resolution.quantity, s.confidence) == ("N", "force", 0.4)


def test_scaling_alone_is_an_explicit_no_suggestion():
    s = suggest_unit(
        _evidence(
            scaling_equation="y=a*2.995+0.1",
            scaling_source="LJStreamM.cfg",
            sibling_units=[SiblingUnit(file_name="x.csv", channel="CH1", unit="K", source="header")],
        )
    )
    assert (s.resolution, s.confidence) == (None, 0)
    assert s.rationale == (
        "no suggestion: no file states a unit for this channel; LJStreamM.cfg scales it as 'y=a*2.995+0.1' "
        "(engineering units, unit not stated); 1 sibling units for other channel names are in the evidence"
    )


def test_with_suggestion_only_touches_telemetry_unit_flags():
    unit = Flag(
        flag_type="UNIT_AMBIGUITY",
        severity="HARD",
        anchor=FlagAnchor(channel="y0"),
        evidence=_evidence(channel="y0"),
    )
    other = Flag(flag_type="LOW_CONFIDENCE_EXTRACTION", severity="SOFT", evidence=LowConfidenceEvidence())
    assert (
        with_suggestion(unit).suggested_resolution.rationale
        == "no suggestion: no file states a unit for this channel"
    )
    assert with_suggestion(unit).fingerprint == unit.fingerprint
    assert with_suggestion(other) is other
