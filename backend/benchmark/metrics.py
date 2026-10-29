"""Benchmark metrics per case and per run (file 08 §5.4). Pure functions over one answer and its case spec.

An `Observed` answer is what the runner captured from the Answer Engine: the `done` frame, the trace (tool
calls, citations, claims, verdicts), the cited documents' names, and the retrieval lists for the gold check.
`score_case` applies only the checks the case asks for, and `classify` names the failure from the metrics.

Interpretations the manual leaves open, chosen here and recorded on the map page:
- Tool trajectory: the expected tools must all be called (in that order when `ordered`); other tools may run
  too, because every playbook adds cross-check searches.
- Numeric exactness reads numbers and units from the claims the verifier entailed; units convert with pint
  (`config/units.txt`), gauge and absolute pressure never convert into each other.
- Retrieval recall: a gold anchor is found when a retrieved passage is in the same document and has the
  same content hash or the same locator (page, line, time or cells), so a re-chunk does not zero the metric.
"""

import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

import pint

from backend.benchmark.catalog import CaseSpec, ExpectedBehavior, ExpectedCitation, ExpectedNumeric
from backend.common.units import UnitError, parse_unit, registry
from backend.postgres.enums import BenchmarkCategory, FailureClass

CITATION_RECALL_PASS = 0.85
FAITHFULNESS_PASS = 0.95
RECALL_30_PASS = 0.9
RECALL_8_PASS = 0.8
NUMBER = re.compile(
    r"(?<![\w.])(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(°\s?[CFK]|[A-Za-zµ%][A-Za-z0-9µ%/·^*]*)?(?:\s(g|a|abs)\b)?"
)
SPACED_UNITS = {("bar", "g"): "barg", ("bar", "a"): "bara", ("bar", "abs"): "bara"}
HALTED_WORDS = re.compile(r"\bhalted\b|\breview case\b|\bunder review\b", re.IGNORECASE)
EXTERNAL_BLOCK = re.compile(
    r"external sources|\bweb\b|vendor|datasheet|brochure|manufacturer|literature|\bpaper\b|publication",
    re.IGNORECASE,
)
EXTERNAL_PROVENANCE = frozenset({"web", "vendor_claim", "literature"})  # web and the external_kept library


@dataclass
class CitedDoc:
    doc_id: str | None
    title: str | None = None
    file_names: tuple[str, ...] = ()
    standard_id: str | None = None
    page_no: int | None = None
    provenance: str | None = None


@dataclass
class Observed:
    mode: str
    answer: str
    tools: list[str]
    tool_warnings: list[str]
    tool_displays: list[str]
    citations: list[CitedDoc]
    claims: list[dict]
    verdicts: list[dict]
    latency_ms: int | None = None
    cost: float | None = None
    retrieved_30: list[tuple[str, str]] = field(default_factory=list)  # (doc_id, anchor) pre-rerank
    retrieved_8: list[tuple[str, str]] = field(default_factory=list)  # (doc_id, anchor) post-rerank
    rerank_margin: float | None = None
    judge: dict[str, dict] = field(default_factory=dict)  # behaviour/provenance → {passed, rationale}
    retrieved_docs: set[str] = field(
        default_factory=set
    )  # every document a tool returned (trace `retrieved`)
    expected_docs: set[str] = field(default_factory=set)  # indexed documents matching the expected citations
    missing_documents: list[str] = field(default_factory=list)  # expected citations with no indexed document
    doc_routes: dict[str, str] = field(default_factory=dict)  # answer route of each cited or retrieved file
    routes_chosen: list[str] = field(default_factory=list)  # the planner's routes, most likely first


# ---------------------------------------------------------------- numbers


def quantities(text: str) -> list[tuple[float, str | None]]:
    """(value, unit text) pairs as written; a unit that pint cannot read is kept as text for UNIT_ERROR."""
    out = []
    for match in NUMBER.finditer(text):
        value = float(match.group(1).replace(",", ""))
        unit = match.group(2)
        if unit and match.group(3):
            unit = SPACED_UNITS.get((unit, match.group(3)), unit)
        if unit:
            unit = unit.replace("° C", "°C").replace("° F", "°F")
        out.append((value, unit))
    return out


def _convert(value: float, unit: str, target: str) -> float | None:
    try:
        source, wanted = parse_unit(unit), parse_unit(target)
    except UnitError:
        return None
    if source.gauge_or_abs != wanted.gauge_or_abs and "unknown" not in (
        source.gauge_or_abs,
        wanted.gauge_or_abs,
    ):
        return None
    try:
        return float(registry().Quantity(value, source.unit).to(wanted.unit).magnitude)
    except (pint.PintError, ValueError):
        return None


def _within(found: float, expected: ExpectedNumeric) -> bool:
    tolerance = abs(expected.value) * expected.tolerance_pct / 100
    return abs(found - expected.value) <= max(tolerance, 1e-12)


def _entailed(claims: list[dict], verdicts: list[dict]) -> tuple[list[dict], list[dict]]:
    verdict = {v["claim_index"]: v["verdict"] for v in verdicts}
    good = [c for i, c in enumerate(claims) if verdict.get(i, "entailed") == "entailed"]
    bad = [c for i, c in enumerate(claims) if verdict.get(i, "entailed") != "entailed"]
    return good, bad


def numeric_exactness(expected: list[ExpectedNumeric], observed: Observed) -> dict[str, Any]:
    good, rejected = _entailed(observed.claims, observed.verdicts)
    found = [q for claim in good for q in quantities(claim["text"])]
    rejected_found = [q for claim in rejected for q in quantities(claim["text"])]
    details, unit_error, verifier_dropped = [], False, False
    for item in expected:
        hit = next(
            (
                (v, u)
                for v, u in found
                if u and (c := _convert(v, u, item.unit)) is not None and _within(c, item)
            ),
            None,
        )
        if hit is None and any(_within(v, item) for v, u in found):
            unit_error = True  # the right number with a unit that does not convert to the expected one
        if hit is None and any(
            u and (c := _convert(v, u, item.unit)) is not None and _within(c, item) for v, u in rejected_found
        ):
            verifier_dropped = True
        details.append(
            {
                "metric": item.metric,
                "expected": item.value,
                "unit": item.unit,
                "tolerance_pct": item.tolerance_pct,
                "found": f"{hit[0]} {hit[1]}" if hit else None,
                "ok": hit is not None,
            }
        )
    return {
        "passed": all(d["ok"] for d in details),
        "details": details,
        "unit_error": unit_error,
        "verifier_dropped": verifier_dropped,
    }


# ---------------------------------------------------------------- citations, tools, entities


def _matches(citation: CitedDoc, expected: ExpectedCitation) -> bool:
    if expected.doc_id is not None and citation.doc_id != str(expected.doc_id):
        return False
    if expected.standard_id and (citation.standard_id or "").casefold() != expected.standard_id.casefold():
        return False
    if expected.file_name:
        names = {n.casefold() for n in (*citation.file_names, citation.title or "") if n}
        if expected.file_name.casefold() not in names:
            return False
    return expected.page is None or citation.page_no == expected.page


def citation_scores(
    expected: list[ExpectedCitation], forbidden: list[ExpectedCitation], cited: list[CitedDoc]
) -> dict[str, Any]:
    recalled = [e for e in expected if any(_matches(c, e) for c in cited)]
    relevant = [c for c in cited if any(_matches(c, e) for e in expected)]
    bad = [c.doc_id or c.title for c in cited if any(_matches(c, f) for f in forbidden)]
    recall = len(recalled) / len(expected) if expected else None
    precision = len(relevant) / len(cited) if expected and cited else None
    passed = (recall is None or recall >= CITATION_RECALL_PASS) and not bad
    return {"recall": recall, "precision": precision, "forbidden_cited": bad, "passed": passed}


def tool_trajectory(expected: list[str], ordered: bool, actual: list[str]) -> dict[str, Any]:
    missing = [t for t in expected if t not in actual]
    in_order = True
    if ordered and not missing:
        positions = [actual.index(t) for t in expected]
        in_order = positions == sorted(positions)
    return {"expected": expected, "actual": actual, "missing": missing, "passed": not missing and in_order}


def entities_present(expected: list[str], answer: str) -> dict[str, Any]:
    missing = [e for e in expected if e.casefold() not in answer.casefold()]
    return {"missing": missing, "passed": not missing}


def faithfulness(verdicts: list[dict]) -> float | None:
    if not verdicts:
        return None
    return sum(v["verdict"] == "entailed" for v in verdicts) / len(verdicts)


# ---------------------------------------------------------------- retrieval


def _locator(anchor: str) -> tuple[str, str]:
    kind, value, _ = anchor.rsplit(":", 2) if anchor.count(":") >= 2 else (anchor, "", "")
    return kind, value


def _found(gold_doc: str, gold_anchor: str, retrieved: list[tuple[str, str]]) -> bool:
    content_hash = gold_anchor.rsplit(":", 1)[-1]
    for doc_id, anchor in retrieved:
        if doc_id != gold_doc:
            continue
        if anchor.rsplit(":", 1)[-1] == content_hash or _locator(anchor) == _locator(gold_anchor):
            return True
    return False


def retrieval_recall(gold: list[tuple[str, str]], retrieved: list[tuple[str, str]]) -> float | None:
    if not gold:
        return None
    return sum(_found(d, a, retrieved) for d, a in gold) / len(gold)


# ---------------------------------------------------------------- behaviour


def behaviour(expected: list[ExpectedBehavior], observed: Observed) -> dict[str, Any]:
    """Deterministic checks where the answer's shape decides; the judge's verdict where only reading does."""
    checks: dict[str, dict] = {}
    for item in expected:
        if item == ExpectedBehavior.MUST_CLARIFY:
            checks[item] = {"passed": observed.mode == "clarification", "by": "mode"}
        elif item == ExpectedBehavior.MUST_STATE_INSUFFICIENT_EVIDENCE:
            checks[item] = {"passed": observed.mode == "insufficient_evidence", "by": "mode"}
        elif item == ExpectedBehavior.MUST_MENTION_HALTED_CASE:
            text = observed.answer + " " + " ".join(observed.tool_warnings)
            checks[item] = {
                "passed": bool(HALTED_WORDS.search(observed.answer)) and "halted" in text,
                "by": "regex",
            }
        elif item == ExpectedBehavior.MUST_LABEL_EXTERNAL:
            external = [c for c in observed.citations if c.provenance in EXTERNAL_PROVENANCE]
            checks[item] = {
                "passed": bool(external) and bool(EXTERNAL_BLOCK.search(observed.answer)),
                "by": "citations",
            }
        else:  # MUST_PRESENT_BOTH_CONFLICTING_VALUES: only reading the answer decides
            verdict = observed.judge.get(str(item))
            checks[item] = {
                "passed": bool(verdict and verdict["passed"]),
                "by": "judge",
                "rationale": verdict["rationale"] if verdict else "judge not run",
            }
    return {
        "checks": {str(k): v for k, v in checks.items()},
        "passed": all(c["passed"] for c in checks.values()),
    }


JUDGED_BEHAVIOURS = frozenset({ExpectedBehavior.MUST_PRESENT_BOTH_CONFLICTING_VALUES})


def route_hit(expected: list[str], observed: Observed) -> dict[str, Any]:
    """Whether the answer cited a file of an expected answer route (PLAN_query_routing.md step 0)."""
    cited = sorted(
        {observed.doc_routes[c.doc_id] for c in observed.citations if c.doc_id in observed.doc_routes}
    )
    retrieved = sorted({observed.doc_routes[d] for d in observed.retrieved_docs if d in observed.doc_routes})
    return {
        "expected": [str(r) for r in expected],
        "chosen": observed.routes_chosen,
        "chosen_ok": bool({str(r) for r in expected} & set(observed.routes_chosen)),
        "cited": cited,
        "retrieved": retrieved,
        "passed": bool({str(r) for r in expected} & set(cited)),
    }


def needs_judge(category: str, spec: CaseSpec) -> list[str]:
    """What the Gemini judge decides here (file 08 §5.4: behaviour checks and provenance labeling)."""
    asks = [str(b) for b in spec.expected_behavior if b in JUDGED_BEHAVIOURS]
    if category == BenchmarkCategory.LIBRARY_VS_INTERNAL:
        asks.append("provenance_labeling")
    return asks


# ---------------------------------------------------------------- one case


def score_case(category: str, spec: CaseSpec, observed: Observed) -> dict[str, Any]:
    metrics: dict[str, Any] = {"mode": observed.mode}
    checks: list[bool] = []
    if spec.expected_numeric:
        metrics["numeric"] = numeric_exactness(spec.expected_numeric, observed)
        checks.append(metrics["numeric"]["passed"])
    if spec.expected_citations or spec.must_not_cite:
        metrics["citations"] = citation_scores(
            spec.expected_citations, spec.must_not_cite, observed.citations
        )
        checks.append(metrics["citations"]["passed"])
    if spec.expected_tools:
        metrics["tools"] = tool_trajectory(
            spec.expected_tools.tools, spec.expected_tools.ordered, observed.tools
        )
        checks.append(metrics["tools"]["passed"])
    if spec.expected_entities:
        metrics["entities"] = entities_present(spec.expected_entities, observed.answer)
        checks.append(metrics["entities"]["passed"])
    if spec.expected_behavior:
        metrics["behavior"] = behaviour(spec.expected_behavior, observed)
        checks.append(metrics["behavior"]["passed"])
    if category == BenchmarkCategory.LIBRARY_VS_INTERNAL:
        verdict = observed.judge.get("provenance_labeling") or {"passed": False, "rationale": "judge not run"}
        metrics["provenance_labeling"] = {"by": "judge", **verdict}
        checks.append(bool(verdict["passed"]))
    if category == BenchmarkCategory.OUT_OF_SCOPE:
        metrics["out_of_scope"] = {"passed": not observed.tools and not observed.citations}
        checks.append(metrics["out_of_scope"]["passed"])
    faith = faithfulness(observed.verdicts)
    metrics["faithfulness"] = faith
    if faith is not None:
        checks.append(faith >= FAITHFULNESS_PASS)
    gold = [(str(g.doc_id), g.anchor) for g in spec.retrieval_gold_anchors]
    metrics["retrieval"] = {
        "recall_at_30": retrieval_recall(gold, observed.retrieved_30),
        "recall_at_8": retrieval_recall(gold, observed.retrieved_8),
        "rerank_margin": observed.rerank_margin,
    }
    if spec.expected_routes:  # reported next to the checks, not one of them
        metrics["route"] = route_hit(spec.expected_routes, observed)
    metrics["latency_ms"] = observed.latency_ms
    if observed.missing_documents:
        metrics["missing_documents"] = observed.missing_documents
    passed = all(checks)
    metrics["failure_class"] = None if passed else classify(category, spec, observed, metrics)
    metrics["passed"] = passed
    return metrics


# Classes added after the first scored run (Lead 2026-10-23); S1 adds them to FailureClass and its CHECK.
MISSING_DOCUMENT = "MISSING_DOCUMENT"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
TIMEOUT = "TIMEOUT"
HALTED_DATA = "HALTED_DATA"
HALTED_WARNING = re.compile(r"halted for review", re.IGNORECASE)


def classify(category: str, spec: CaseSpec, observed: Observed, metrics: dict) -> str:
    """The first failure in pipeline order (file 08 §5.4 plus the classes above): MISSING_DOCUMENT →
    HALTED_DATA (a tool reported the asked run halted; behaviour cases excepted) → BEHAVIOR_FAIL →
    RETRIEVAL_MISS (gold anchors) → RERANK_MISS → TOOL_MISROUTE → TOOL_ERROR → INSUFFICIENT_EVIDENCE →
    RETRIEVAL_MISS (an expected document no tool returned) → UNIT_ERROR → VERIFIER_FALSE_NEGATIVE →
    SYNTHESIS_ERROR."""
    if observed.missing_documents:
        return MISSING_DOCUMENT
    if any(HALTED_WARNING.search(w) for w in observed.tool_warnings) and "behavior" not in metrics:
        return HALTED_DATA
    if "behavior" in metrics and not metrics["behavior"]["passed"]:
        return FailureClass.BEHAVIOR_FAIL
    if not metrics.get("out_of_scope", {}).get("passed", True):
        return FailureClass.BEHAVIOR_FAIL
    retrieval = metrics["retrieval"]
    if retrieval["recall_at_30"] is not None and retrieval["recall_at_30"] < 1.0:
        return FailureClass.RETRIEVAL_MISS
    if retrieval["recall_at_8"] is not None and retrieval["recall_at_8"] < 1.0:
        return FailureClass.RERANK_MISS
    if "tools" in metrics and not metrics["tools"]["passed"]:
        return FailureClass.TOOL_MISROUTE
    if any(re.search(r"\bfailed\b|\berror\b", w, re.IGNORECASE) for w in observed.tool_warnings):
        return FailureClass.TOOL_ERROR
    if observed.mode == "insufficient_evidence":
        return INSUFFICIENT_EVIDENCE
    if observed.expected_docs and not observed.expected_docs & observed.retrieved_docs:
        return FailureClass.RETRIEVAL_MISS
    numeric = metrics.get("numeric")
    if numeric and not numeric["passed"]:
        if numeric["unit_error"]:
            return FailureClass.UNIT_ERROR
        if numeric["verifier_dropped"]:
            return FailureClass.VERIFIER_FALSE_NEGATIVE
    return FailureClass.SYNTHESIS_ERROR


# ---------------------------------------------------------------- one run


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(statistics.fmean(present), 4) if present else None


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def aggregate(results: list[dict], total: int) -> dict[str, Any]:
    """Run summary for the dashboard ribbon: results are `{case_id, category, passed, metrics, cost}`."""
    done = len(results)
    latencies = [r["metrics"]["latency_ms"] for r in results if r["metrics"].get("latency_ms") is not None]
    numeric = [r["metrics"]["numeric"]["passed"] for r in results if "numeric" in r["metrics"]]
    categories: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = categories.setdefault(r["category"], {"cases": 0, "passed": 0})
        bucket["cases"] += 1
        bucket["passed"] += bool(r["passed"])
    failures: dict[str, int] = {}
    for r in results:
        if r["metrics"].get("failure_class"):
            failures[r["metrics"]["failure_class"]] = failures.get(r["metrics"]["failure_class"], 0) + 1
    routes: dict[str, dict[str, int]] = {}
    for r in results:
        route = r["metrics"].get("route")
        for name in route["expected"] if route else []:
            bucket = routes.setdefault(name, {"cases": 0, "passed": 0, "route_hit": 0, "route_chosen": 0})
            bucket["cases"] += 1
            bucket["passed"] += bool(r["passed"])
            bucket["route_hit"] += bool(route["passed"])
            bucket["route_chosen"] += bool(route.get("chosen_ok"))
    costs = [r["cost"] for r in results if r.get("cost") is not None]
    return {
        "cases_total": total,
        "cases_done": done,
        "pass_rate": round(sum(bool(r["passed"]) for r in results) / done, 4) if done else None,
        "numeric_exactness": round(sum(numeric) / len(numeric), 4) if numeric else None,
        "citation_recall": _mean([r["metrics"].get("citations", {}).get("recall") for r in results]),
        "faithfulness": _mean([r["metrics"].get("faithfulness") for r in results]),
        "retrieval_recall_at_8": _mean([r["metrics"]["retrieval"]["recall_at_8"] for r in results]),
        "retrieval_recall_at_30": _mean([r["metrics"]["retrieval"]["recall_at_30"] for r in results]),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "cost_total": round(sum(costs), 6) if costs else None,
        "failure_classes": failures,
        "by_category": categories,
        "by_route": routes,
        "clarifications": sum(r["metrics"].get("mode") == "clarification" for r in results),
    }
