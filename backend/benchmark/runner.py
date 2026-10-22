"""Benchmark runner (file 08 §5.6, M10): executes a queued `benchmark_runs` row case by case.

`run_benchmark(run_id, deps)`:
1. Claims the run (QUEUED or a RUNNING run whose worker died → RUNNING), snapshots the model configuration,
   the pipeline version and the ACTIVE document count.
2. Loads the case versions the run snapshotted and skips cases that already have a result, so a redelivered
   task resumes instead of starting over.
3. Answers each case through the Answer Engine's own workflow (benchmark mode: external search mocked unless
   the run asks for `allow`; a clarification is answered from `spec.clarification_answer`), at most
   `concurrency` at a time. A case with retrieval gold anchors also gets a retrieval-only pass (pre-rerank
   top-30, reranked top-8) for the recall metrics.
4. Runs the Gemini judge only where metrics.needs_judge says so, scores the case (metrics.score_case), writes
   `benchmark_results`, recomputes the run aggregate and publishes a `run` websocket event.
5. Stops between cases when the run was CANCELLED; ends COMPLETED, or FAILED with the error in the aggregate.

`deps` holds the effects (database, engine call, retrieval, judge, publish) so the whole flow is testable with
fakes; `default_deps()` wires the stack's clients.
"""

import asyncio
import dataclasses
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from backend.benchmark import metrics
from backend.benchmark.catalog import CaseSpec, ExpectedBehavior
from backend.postgres.enums import BenchmarkRunStatus, DocumentStatus
from backend.postgres.models import BenchmarkCase, BenchmarkResult, BenchmarkRun, Document

log = logging.getLogger(__name__)

AnswerFn = Callable[[str, str, str], Awaitable[tuple[dict, dict | None]]]  # question, history, external mode
RetrieveFn = Callable[[Session, str], tuple[list[tuple[str, str]], list[tuple[str, str]], float | None]]
JudgeFn = Callable[[str, str, str, list[dict]], Awaitable[dict]]  # expectation, question, answer, sources
CLAIMABLE = (BenchmarkRunStatus.QUEUED, BenchmarkRunStatus.RUNNING)


@dataclass
class RunnerDeps:
    session_factory: Callable[[], Session]
    answer: AnswerFn
    publish: Callable[[str, str, dict], None]  # (run_id, event, data) → websocket topic `run`
    retrieve: RetrieveFn | None = None
    judge: JudgeFn | None = None
    model_config: dict[str, Any] = dataclasses.field(default_factory=dict)
    concurrency: int = 3
    external_mode: str = "mock"


@dataclass(frozen=True)
class Case:
    case_id: str
    version: int
    category: str
    question: str
    spec: CaseSpec


# ---------------------------------------------------------------- database steps


def claim(session: Session, run_id: uuid.UUID, model_config: dict) -> BenchmarkRun | None:
    """QUEUED or RUNNING → RUNNING with the configuration snapshot; None when the run is final."""
    row = session.execute(
        update(BenchmarkRun)
        .where(BenchmarkRun.run_id == run_id, BenchmarkRun.status.in_([str(s) for s in CLAIMABLE]))
        .values(
            status=BenchmarkRunStatus.RUNNING, started_at=func.coalesce(BenchmarkRun.started_at, func.now())
        )
        .returning(BenchmarkRun.run_id)
    ).first()
    if row is None:
        return None
    run = session.get(BenchmarkRun, run_id)
    session.refresh(run)
    visible = [str(DocumentStatus.ACTIVE), str(DocumentStatus.ACTIVE_WITH_SOFT_FLAGS)]
    run.active_doc_count = session.scalar(select(func.count()).where(Document.status.in_(visible)))
    run.pipeline_version = session.scalar(
        select(func.max(Document.pipeline_version)).where(Document.status.in_(visible))
    )
    run.model_config = {**(run.model_config or {}), **model_config}
    session.commit()
    return run


def load_cases(session: Session, run: BenchmarkRun) -> list[Case]:
    done = set(session.scalars(select(BenchmarkResult.case_id).where(BenchmarkResult.run_id == run.run_id)))
    cases = []
    for case_id, version in sorted((run.case_versions or {}).items()):
        if case_id in done:
            continue
        row = session.get(BenchmarkCase, (case_id, version))
        if row is None:
            continue
        cases.append(
            Case(case_id, version, row.category, row.question, CaseSpec.model_validate(row.spec or {}))
        )
    return cases


def status_of(session: Session, run_id: uuid.UUID) -> str:
    return session.scalar(select(BenchmarkRun.status).where(BenchmarkRun.run_id == run_id))


def cited_documents(session: Session, citations: list[dict]) -> list[metrics.CitedDoc]:
    ids = [c["doc_id"] for c in citations if c.get("doc_id")]
    names: dict[str, tuple] = {}
    if ids:
        rows = session.execute(
            text(
                "SELECT d.doc_id::text AS doc_id, d.title, d.standard_id, "
                "array_remove(array_agg(DISTINCT di.name), NULL) AS names "
                "FROM documents d LEFT JOIN document_sources ds ON ds.doc_id = d.doc_id "
                "LEFT JOIN drive_items di ON di.blob_sha256 = ds.blob_sha256 "
                "WHERE d.doc_id::text = ANY(:ids) GROUP BY d.doc_id"
            ),
            {"ids": ids},
        )
        names = {r.doc_id: (r.title, tuple(r.names or ()), r.standard_id) for r in rows}
    out = []
    for c in citations:
        title, files, standard = names.get(c.get("doc_id") or "", (c.get("title"), (), None))
        anchor = c.get("anchor") or ""
        page = (
            int(anchor.split(":")[1])
            if anchor.startswith("page:") and anchor.split(":")[1].isdigit()
            else None
        )
        out.append(
            metrics.CitedDoc(
                doc_id=c.get("doc_id"),
                title=title or c.get("title"),
                file_names=files,
                standard_id=standard,
                page_no=page,
                provenance=c.get("provenance"),
            )
        )
    return out


def write_result(session: Session, run_id: uuid.UUID, case: Case, outcome: dict) -> None:
    session.merge(
        BenchmarkResult(
            run_id=run_id,
            case_id=case.case_id,
            case_version=case.version,
            trace_id=outcome.get("trace_id"),
            passed=outcome["passed"],
            failure_class=outcome["metrics"].get("failure_class"),
            latency_ms=outcome["metrics"].get("latency_ms"),
            cost_estimate=outcome.get("cost"),
            metrics=outcome["metrics"],
        )
    )
    session.commit()


def refresh_aggregate(session: Session, run_id: uuid.UUID) -> dict:
    run = session.get(BenchmarkRun, run_id)
    rows = session.scalars(select(BenchmarkResult).where(BenchmarkResult.run_id == run_id))
    categories = {
        c.case_id: c.category
        for c in session.scalars(
            select(BenchmarkCase).where(BenchmarkCase.case_id.in_(list((run.case_versions or {}).keys())))
        )
    }
    results = [
        {
            "case_id": r.case_id,
            "category": categories.get(r.case_id, "UNKNOWN"),
            "passed": r.passed,
            "metrics": {"retrieval": {"recall_at_8": None, "recall_at_30": None}, **(r.metrics or {})},
            "cost": float(r.cost_estimate) if r.cost_estimate is not None else None,
        }
        for r in rows
    ]
    run.aggregate = metrics.aggregate(results, total=len(run.case_versions or {}))
    session.commit()
    return run.aggregate


def finish(session: Session, run_id: uuid.UUID, status: BenchmarkRunStatus, error: str | None = None) -> None:
    run = session.get(BenchmarkRun, run_id)
    session.refresh(run)
    if run.status == BenchmarkRunStatus.CANCELLED:
        return
    run.status = status
    run.finished_at = datetime.now(UTC)
    if error:
        run.aggregate = {**(run.aggregate or {}), "error": error[:500]}
    session.commit()


# ---------------------------------------------------------------- one case


def observed_from(done: dict, trace: dict | None, cited: list[metrics.CitedDoc]) -> metrics.Observed:
    trace = trace or {}
    verifier = trace.get("verifier_result") or {}
    calls = trace.get("tool_calls", [])
    return metrics.Observed(
        mode=done.get("mode", "error"),
        answer=done.get("answer_markdown", ""),
        tools=[c["tool"] for c in calls],
        tool_warnings=[w for c in calls for w in c.get("warnings", [])],
        tool_displays=[c.get("display", "") for c in calls],
        citations=cited,
        claims=trace.get("claims", []),
        verdicts=verifier.get("verdicts", []),
        latency_ms=done.get("latency_ms"),
        cost=(done.get("usage") or {}).get("cost_estimate"),
    )


async def run_case(case: Case, deps: RunnerDeps) -> dict:
    question = case.question
    done, trace = await deps.answer(question, "", deps.external_mode)
    clarify = ExpectedBehavior.MUST_CLARIFY in case.spec.expected_behavior
    if done.get("mode") == "clarification" and case.spec.clarification_answer and not clarify:
        history = f"user: {question}\nassistant: {done.get('answer_markdown', '')}"
        done, trace = await deps.answer(case.spec.clarification_answer, history, deps.external_mode)
    citations = (trace or {}).get("citations", [])
    with deps.session_factory() as session:
        cited = cited_documents(session, citations)
        observed = observed_from(done, trace, cited)
        if case.spec.retrieval_gold_anchors and deps.retrieve is not None:
            observed.retrieved_30, observed.retrieved_8, observed.rerank_margin = await asyncio.to_thread(
                deps.retrieve, session, question
            )
    for expectation in metrics.needs_judge(case.category, case.spec):
        if deps.judge is not None:
            observed.judge[expectation] = await deps.judge(expectation, question, observed.answer, citations)
    scored = metrics.score_case(case.category, case.spec, observed)
    trace_id = done.get("trace_id")
    return {
        "trace_id": uuid.UUID(trace_id) if trace_id else None,
        "passed": scored.pop("passed"),
        "metrics": scored,
        "cost": observed.cost,
    }


# ---------------------------------------------------------------- one run


def start(run_id: uuid.UUID, deps: RunnerDeps) -> list[str] | None:
    """Claim the run; the case ids still without a result, or None when the run is already final."""
    with deps.session_factory() as session:
        run = claim(session, run_id, deps.model_config)
        if run is None:
            return None
        pending = [case.case_id for case in load_cases(session, run)]
        total = len(run.case_versions or {})
    deps.publish(str(run_id), "progress", {"status": "RUNNING", "cases_total": total})
    if not pending:
        complete_if_done(run_id, deps)
    return pending


def complete_if_done(run_id: uuid.UUID, deps: RunnerDeps) -> bool:
    """RUNNING → COMPLETED once every snapshotted case has a result; exactly one caller wins the update."""
    with deps.session_factory() as session:
        run = session.get(BenchmarkRun, run_id)
        results = session.scalar(select(func.count()).where(BenchmarkResult.run_id == run_id))
        if run is None or results < len(run.case_versions or {}):
            return False
        aggregate = refresh_aggregate(session, run_id)
        won = session.execute(
            update(BenchmarkRun)
            .where(BenchmarkRun.run_id == run_id, BenchmarkRun.status == BenchmarkRunStatus.RUNNING)
            .values(status=BenchmarkRunStatus.COMPLETED, finished_at=func.now())
            .returning(BenchmarkRun.run_id)
        ).first()
        session.commit()
    if won:
        deps.publish(str(run_id), "finished", {"status": str(BenchmarkRunStatus.COMPLETED), **aggregate})
    return bool(won)


async def run_one(run_id: uuid.UUID, case_id: str, deps: RunnerDeps) -> dict | None:
    """Answer and score one case of a RUNNING run; None when the run is not running or the case is done."""
    with deps.session_factory() as session:
        run = session.get(BenchmarkRun, run_id)
        if run is None or run.status != BenchmarkRunStatus.RUNNING:
            return None
        done = session.get(BenchmarkResult, (run_id, case_id))
        version = (run.case_versions or {}).get(case_id)
        row = session.get(BenchmarkCase, (case_id, version)) if version is not None else None
        if done is not None or row is None:
            return None
        case = Case(case_id, version, row.category, row.question, CaseSpec.model_validate(row.spec or {}))
        total = len(run.case_versions or {})
    try:
        outcome = await run_case(case, deps)
    except Exception as exc:  # noqa: BLE001 — one broken case is recorded, the run goes on
        log.exception("benchmark %s case %s failed", run_id, case_id)
        outcome = {"passed": False, "metrics": {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}}
    with deps.session_factory() as session:
        if status_of(session, run_id) != BenchmarkRunStatus.RUNNING:
            return None  # cancelled while answering: the result is dropped
        write_result(session, run_id, case, outcome)
        aggregate = refresh_aggregate(session, run_id)
    deps.publish(
        str(run_id),
        "progress",
        {
            "case_id": case_id,
            "passed": outcome["passed"],
            "failure_class": outcome["metrics"].get("failure_class"),
            "cases_done": aggregate["cases_done"],
            "cases_total": total,
            "pass_rate": aggregate["pass_rate"],
        },
    )
    complete_if_done(run_id, deps)
    return outcome


def fail(run_id: uuid.UUID, deps: RunnerDeps, error: str) -> None:
    with deps.session_factory() as session:
        finish(session, run_id, BenchmarkRunStatus.FAILED, error)
    deps.publish(str(run_id), "finished", {"status": str(BenchmarkRunStatus.FAILED), "error": error[:500]})


async def run_benchmark(run_id: uuid.UUID, deps: RunnerDeps) -> str:
    """The whole run in one process (tests, a manual run); the workers use `start` + one task per case."""
    try:
        pending = start(run_id, deps)
    except Exception as exc:
        fail(run_id, deps, f"{type(exc).__name__}: {exc}")
        raise
    if pending:
        gate = asyncio.Semaphore(max(1, deps.concurrency))

        async def one(case_id: str) -> None:
            async with gate:
                await run_one(run_id, case_id, deps)

        await asyncio.gather(*(one(case_id) for case_id in pending))
    with deps.session_factory() as session:
        return status_of(session, run_id) or "MISSING"


# ---------------------------------------------------------------- production wiring


def workflow_answer(engine) -> AnswerFn:
    """Benchmark answers through the Answer Engine's own workflow (same code path as chat), with the trace
    captured. The benchmark caller belongs to the external-search groups, and the external mode of the run
    (`mock` by default: canned results, no network) decides what T6 does."""
    from backend.llm_engine.engine.workflow import AnswerWorkflow

    async def answer(question: str, history: str, external_mode: str) -> tuple[dict, dict | None]:
        traces: list[dict] = []
        deps = dataclasses.replace(engine, save_trace=lambda t: (traces.append(t), engine.save_trace(t)))
        with engine.session_factory() as session:
            allowed = list(engine.external_policy(session).allowed_groups)
        handler = AnswerWorkflow(deps, timeout=300).run(
            question=question,
            trace_id=str(uuid.uuid4()),
            history=history,
            groups=["dcl-benchmark", *allowed],
            external_mode=external_mode,
        )
        done = await handler
        return done, traces[0] if traces else None

    return answer


def default_deps(*, concurrency: int = 3) -> RunnerDeps:
    """The stack's clients: the Answer Engine's own deps (engine_deps), the models role for retrieval,
    the Gemini judge, and Redis for the websocket bridge."""
    import redis

    from backend.api.engine import engine_deps
    from backend.api.ws import Event, Topic, publish_event
    from backend.benchmark.judge import judge
    from backend.config import Group, get_settings
    from backend.indexing.retrieval import search

    settings = get_settings()
    engine = engine_deps(settings)
    redis_client = redis.Redis.from_url(settings.require(Group.REDIS).redis_url, socket_timeout=5)

    def retrieve(session: Session, question: str):
        pre = search(session, question, embed_query=engine.embed_query, rerank=None, k=30)
        post = search(session, question, embed_query=engine.embed_query, rerank=engine.rerank, k=8)
        pairs = lambda result: [(str(h.doc_id), h.anchor) for h in result.hits]  # noqa: E731
        return pairs(pre), pairs(post), post.rerank_margin_1_5

    def publish(run_id: str, event: str, data: dict) -> None:
        try:
            publish_event(redis_client, Event(topic=Topic.RUN, key=run_id, event=event, data=data))
        except Exception:  # noqa: BLE001 — progress events are best effort; the Console also polls
            log.warning("benchmark %s: could not publish %s", run_id, event, exc_info=True)

    return RunnerDeps(
        session_factory=engine.session_factory,
        answer=workflow_answer(engine),
        publish=publish,
        retrieve=retrieve,
        judge=lambda *args: judge(engine.gemini, *args),
        model_config={
            "gemini_model": settings.gemini_model,
            "gemini_lite_model": settings.gemini_lite_model,
            "external_search": "mock",
        },
        concurrency=concurrency,
    )
