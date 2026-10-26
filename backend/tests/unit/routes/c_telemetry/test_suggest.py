"""UNIT_AMBIGUITY suggestions: a unit only when a file states it, else an explicit 'no suggestion'."""

from backend.dispatcher.contract import (
    CandidateUnit,
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    SetUnit,
    SiblingUnit,
    Suggestion,
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


def _unit_flag(**kw) -> Flag:
    return Flag(
        flag_type="UNIT_AMBIGUITY", severity="HARD", anchor=FlagAnchor(channel="y0"), evidence=_evidence(**kw)
    )


def test_the_model_proposes_only_when_no_file_states_a_unit():
    calls = []

    def propose(evidence):
        calls.append(evidence.channel)
        return Suggestion(
            resolution=SetUnit(channel="y0", unit="bar", quantity="pressure", gauge_or_abs="gauge"),
            confidence=0.4,
            rationale="model proposal",
            proposed_by="llm",
        )

    silent = with_suggestion(_unit_flag(channel="y0"), propose).suggested_resolution
    assert (silent.proposed_by, silent.resolution.unit, calls) == ("llm", "bar", ["y0"])
    stated = with_suggestion(_unit_flag(channel="y0", raw_unit="psi"), propose).suggested_resolution
    assert (stated.proposed_by, stated.resolution.unit, calls) == ("heuristic", "psi", ["y0"])


def test_a_model_proposal_is_capped_below_auto_apply_and_marked_as_the_models():
    from types import SimpleNamespace

    from backend.llm_engine.suggestions import MAX_CONFIDENCE, UnitProposal, propose_unit

    class Client:
        def generate_sync(self, **kw):
            self.kw = kw
            reply = UnitProposal(quantity="pressure", unit="bar", gauge_or_abs="gauge", confidence=0.95)
            return SimpleNamespace(parsed=reply, model=kw["model"])

    client = Client()
    s = propose_unit(client, _evidence(channel="y3"), file_name="t1.dat", folder="APU/TP12", model="m")
    assert (s.proposed_by, s.confidence, s.resolution.unit, s.resolution.gauge_or_abs) == (
        "llm",
        MAX_CONFIDENCE,
        "bar",
        "gauge",
    )
    assert (
        client.kw["context"].purpose == "suggest.unit"
        and "Column: y3" in client.kw["messages"][1].parts[0].text
    )
    unknown = UnitProposal(confidence=0.2, rationale="no evidence")
    client.generate_sync = lambda **kw: SimpleNamespace(parsed=unknown, model="m")
    assert (
        propose_unit(client, _evidence(channel="y3"), file_name="t1.dat", folder="x", model="m").resolution
        is None
    )


def test_the_readers_guess_is_proposed_below_the_names_confidence():
    evidence = UnitTelemetryEvidence(
        channel="Chamber PT 1",
        quantity_guess="pressure",
        candidate_units=[CandidateUnit(unit="bar", score=0.5, reason="usual")],
    )
    suggestion = suggest_unit(evidence)
    assert (suggestion.resolution.unit, suggestion.resolution.quantity, suggestion.confidence) == (
        "bar",
        "pressure",
        0.4,
    )
    assert "reads as pressure, usually in bar" in suggestion.rationale
