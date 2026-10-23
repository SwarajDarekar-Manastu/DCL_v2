"""Benchmark metrics (file 08 §5.4) on hand-built answers: what passes, what fails, and the failure class."""

import uuid

import pytest

from backend.benchmark.catalog import CaseSpec
from backend.benchmark.metrics import (
    CitedDoc,
    Observed,
    aggregate,
    needs_judge,
    quantities,
    retrieval_recall,
    score_case,
)

DOC = str(uuid.UUID("00000000-0000-4000-8000-000000000041"))
OLD = str(uuid.UUID("00000000-0000-4000-8000-000000000040"))
HASH = "a" * 64


def answer(**overrides) -> Observed:
    values = dict(
        mode="answered",
        answer="The mean chamber pressure while the valve was open was 12.41 barg [1].",
        tools=["catalog_lookup", "query_telemetry", "search_documents"],
        tool_warnings=[],
        tool_displays=[],
        citations=[CitedDoc(doc_id=DOC, title="TP07_T01.dat", file_names=("TP07_T01.dat",), page_no=None)],
        claims=[{"text": "mean chamber pressure 12.41 barg", "kind": "numeric"}],
        verdicts=[{"claim_index": 0, "verdict": "entailed"}],
        latency_ms=4200,
    )
    return Observed(**{**values, **overrides})


TELEMETRY = CaseSpec.model_validate(
    {
        "expected_numeric": [
            {"metric": "chamber_pressure_mean", "value": 12.4, "unit": "barg", "tolerance_pct": 1}
        ],
        "expected_tools": {"tools": ["query_telemetry"]},
        "expected_citations": [{"file_name": "TP07_T01.dat"}],
    }
)


def test_quantities_read_numbers_with_units_as_engineers_write_them():
    assert quantities("12.41 barg, 2 bar g, 985.05 kelvin and 7.999 s in TP07 T04") == [
        (12.41, "barg"),
        (2.0, "barg"),
        (985.05, "kelvin"),
        (7.999, "s"),
    ]
    assert quantities("1,234.5 N at 20 °C") == [(1234.5, "N"), (20.0, "°C")]


def test_a_correct_telemetry_answer_passes_every_check():
    metrics = score_case("TELEMETRY_MATH", TELEMETRY, answer())
    assert metrics["passed"] and metrics["failure_class"] is None
    assert metrics["numeric"]["details"][0]["found"] == "12.41 barg"
    assert metrics["citations"]["recall"] == 1.0 and metrics["tools"]["passed"]
    assert metrics["faithfulness"] == 1.0


def test_units_convert_but_gauge_never_becomes_absolute():
    in_psi = answer(claims=[{"text": "mean 179.9 psig", "kind": "numeric"}])
    assert score_case("TELEMETRY_MATH", TELEMETRY, in_psi)["passed"]
    absolute = answer(claims=[{"text": "mean 12.41 bara", "kind": "numeric"}])
    metrics = score_case("TELEMETRY_MATH", TELEMETRY, absolute)
    assert not metrics["passed"] and metrics["failure_class"] == "UNIT_ERROR"


def test_a_number_the_verifier_rejected_is_a_verifier_false_negative():
    rejected = answer(verdicts=[{"claim_index": 0, "verdict": "not_supported"}])
    metrics = score_case("TELEMETRY_MATH", TELEMETRY, rejected)
    assert metrics["failure_class"] == "VERIFIER_FALSE_NEGATIVE"
    assert metrics["faithfulness"] == 0.0


def test_a_missing_tool_is_a_misroute_and_a_wrong_number_a_synthesis_error():
    misrouted = answer(tools=["search_documents"])
    assert score_case("TELEMETRY_MATH", TELEMETRY, misrouted)["failure_class"] == "TOOL_MISROUTE"
    wrong = answer(claims=[{"text": "mean 14.0 barg", "kind": "numeric"}])
    assert score_case("TELEMETRY_MATH", TELEMETRY, wrong)["failure_class"] == "SYNTHESIS_ERROR"
    broken = answer(tools=["query_telemetry"], tool_warnings=["telemetry query failed: IO error"], claims=[])
    assert score_case("TELEMETRY_MATH", TELEMETRY, broken)["failure_class"] == "TOOL_ERROR"


def test_ordered_tools_must_appear_in_order():
    spec = CaseSpec.model_validate(
        {"expected_tools": {"tools": ["catalog_lookup", "query_telemetry"], "ordered": True}}
    )
    assert score_case("FAILURE_ANALYSIS", spec, answer())["passed"]
    swapped = answer(tools=["query_telemetry", "catalog_lookup"])
    assert not score_case("FAILURE_ANALYSIS", spec, swapped)["passed"]


def test_citations_recall_pages_and_forbidden_sources():
    spec = CaseSpec.model_validate(
        {
            "expected_citations": [{"doc_id": DOC, "page": 8}],
            "must_not_cite": [{"doc_id": OLD}],
        }
    )
    right = answer(citations=[CitedDoc(doc_id=DOC, page_no=8)])
    assert score_case("FACT_LOOKUP", spec, right)["citations"]["passed"]
    wrong_page = answer(citations=[CitedDoc(doc_id=DOC, page_no=9)])
    assert score_case("FACT_LOOKUP", spec, wrong_page)["citations"]["recall"] == 0.0
    forbidden = answer(citations=[CitedDoc(doc_id=DOC, page_no=8), CitedDoc(doc_id=OLD, page_no=1)])
    scored = score_case("FACT_LOOKUP", spec, forbidden)
    assert scored["citations"]["forbidden_cited"] == [OLD] and not scored["passed"]
    assert scored["citations"]["precision"] == 0.5


def test_retrieval_recall_survives_a_rechunk_and_classifies_the_miss():
    gold = [(DOC, f"page:8:{HASH}")]
    assert retrieval_recall(gold, [(DOC, f"page:8:{'b' * 64}")]) == 1.0  # same page, new chunk
    assert retrieval_recall(gold, [(DOC, f"page:3:{HASH}")]) == 1.0  # same passage, moved
    assert retrieval_recall(gold, [(OLD, f"page:8:{HASH}")]) == 0.0
    spec = CaseSpec.model_validate(
        {
            "retrieval_gold_anchors": [{"doc_id": DOC, "anchor": f"page:8:{HASH}"}],
            "expected_entities": ["T04"],
        }
    )
    missed = answer(retrieved_30=[], retrieved_8=[])
    assert score_case("FACT_LOOKUP", spec, missed)["failure_class"] == "RETRIEVAL_MISS"
    reranked_away = answer(retrieved_30=[(DOC, f"page:8:{HASH}")], retrieved_8=[])
    assert score_case("FACT_LOOKUP", spec, reranked_away)["failure_class"] == "RERANK_MISS"


@pytest.mark.parametrize(
    ("behavior", "observed", "passed"),
    [
        ("must_clarify", answer(mode="clarification"), True),
        ("must_clarify", answer(), False),
        ("must_state_insufficient_evidence", answer(mode="insufficient_evidence"), True),
        (
            "must_mention_halted_case",
            answer(
                answer="Run T06 is halted for review (case-unit-tp07-t06).",
                tool_warnings=["run T06 is halted"],
            ),
            True,
        ),
        ("must_mention_halted_case", answer(), False),
        (
            "must_label_external",
            answer(
                answer="External sources: preheat 2–5 W (web) [2].",
                citations=[CitedDoc(None, provenance="web")],
            ),
            True,
        ),
    ],
)
def test_behaviour_checks_decided_by_the_answer_shape(behavior, observed, passed):
    spec = CaseSpec.model_validate({"expected_behavior": [behavior]})
    metrics = score_case("HALTED_DATA_BEHAVIOR", spec, observed)
    assert metrics["behavior"]["passed"] is passed
    assert metrics["failure_class"] == (None if passed else "BEHAVIOR_FAIL")


def test_the_judge_decides_conflicts_and_provenance_only():
    conflict = CaseSpec.model_validate({"expected_behavior": ["must_present_both_conflicting_values"]})
    assert needs_judge("CONFLICT_BEHAVIOR", conflict) == ["must_present_both_conflicting_values"]
    assert needs_judge("LIBRARY_VS_INTERNAL", CaseSpec()) == ["provenance_labeling"]
    assert needs_judge("TELEMETRY_MATH", TELEMETRY) == []
    judged = answer(
        judge={"must_present_both_conflicting_values": {"passed": True, "rationale": "both stated"}}
    )
    assert score_case("CONFLICT_BEHAVIOR", conflict, judged)["passed"]
    assert not score_case("CONFLICT_BEHAVIOR", conflict, answer())["passed"]  # judge not run → not passed
    labelled = answer(
        judge={"provenance_labeling": {"passed": False, "rationale": "vendor value unlabelled"}}
    )
    assert score_case("LIBRARY_VS_INTERNAL", CaseSpec(), labelled)["failure_class"] == "SYNTHESIS_ERROR"


def test_out_of_scope_answers_without_tools_or_citations():
    chat = answer(mode="chitchat", tools=[], citations=[], claims=[], verdicts=[])
    assert score_case("OUT_OF_SCOPE", CaseSpec(), chat)["passed"]
    assert score_case("OUT_OF_SCOPE", CaseSpec(), answer())["failure_class"] == "BEHAVIOR_FAIL"


def test_aggregate_for_the_dashboard_ribbon():
    passed = score_case("TELEMETRY_MATH", TELEMETRY, answer())
    failed = score_case("TELEMETRY_MATH", TELEMETRY, answer(tools=["search_documents"], latency_ms=9000))
    results = [
        {"case_id": "a", "category": "TELEMETRY_MATH", "passed": True, "metrics": passed, "cost": 0.01},
        {"case_id": "b", "category": "TELEMETRY_MATH", "passed": False, "metrics": failed, "cost": 0.02},
    ]
    summary = aggregate(results, total=3)
    assert (summary["cases_done"], summary["cases_total"], summary["pass_rate"]) == (2, 3, 0.5)
    assert summary["numeric_exactness"] == 1.0 and summary["citation_recall"] == 1.0
    assert summary["failure_classes"] == {"TOOL_MISROUTE": 1}
    assert summary["latency_p50_ms"] == 4200 and summary["latency_p95_ms"] == 9000
    assert summary["by_category"] == {"TELEMETRY_MATH": {"cases": 2, "passed": 1}}
    assert summary["cost_total"] == 0.03


def test_every_failure_gets_a_class_from_the_first_scored_run():
    fact = CaseSpec.model_validate({"expected_citations": [{"file_name": "TP12 Test Report.pdf"}]})
    missing = answer(missing_documents=["TP12 Test Report.pdf"], citations=[])
    assert score_case("FACT_LOOKUP", fact, missing)["failure_class"] == "MISSING_DOCUMENT"
    nothing = answer(mode="insufficient_evidence", citations=[], expected_docs={DOC})
    assert score_case("FACT_LOOKUP", fact, nothing)["failure_class"] == "INSUFFICIENT_EVIDENCE"
    never_found = answer(citations=[], expected_docs={DOC}, retrieved_docs={OLD})
    assert score_case("FACT_LOOKUP", fact, never_found)["failure_class"] == "RETRIEVAL_MISS"
    found_not_cited = answer(citations=[], expected_docs={DOC}, retrieved_docs={DOC})
    assert score_case("FACT_LOOKUP", fact, found_not_cited)["failure_class"] == "SYNTHESIS_ERROR"
    expected = CaseSpec.model_validate({"expected_behavior": ["must_state_insufficient_evidence"]})
    assert score_case("HALTED_DATA_BEHAVIOR", expected, nothing)["passed"]  # asked for: not a failure


def test_halted_data_and_library_labels_from_the_s5_baseline():
    halted = answer(
        tool_warnings=["run TP07_T01 (TP07_T01.dat) is halted for review (case-unit-7)"],
        claims=[],
        verdicts=[],
    )
    assert score_case("TELEMETRY_MATH", TELEMETRY, halted)["failure_class"] == "HALTED_DATA"
    expects = CaseSpec.model_validate({"expected_behavior": ["must_mention_halted_case"]})
    assert score_case("HALTED_DATA_BEHAVIOR", expects, halted)["failure_class"] == "BEHAVIOR_FAIL"
    library = CaseSpec.model_validate({"expected_behavior": ["must_label_external"]})
    vendor = answer(
        answer="The Moog datasheet claims 22 N (vendor claim) [1].",
        citations=[CitedDoc(DOC, provenance="vendor_claim")],
    )
    assert score_case("LIBRARY_VS_INTERNAL", library, vendor)["behavior"]["passed"]
