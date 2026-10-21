"""Benchmark catalog: case spec, versioned cases, runs, results, comparison (file 08 §5, file 05 §4.7).

Owner: S3 (the API's domain module; the runner, metrics and judge in this package are S2's).

Cases are authored data: a version is never changed except its status (approve, retire), and every
change writes `audit_events` (entity_type `benchmark_case`). `CaseSpec` is the shape of
`benchmark_cases.spec`; gold passages are stable anchors (never node ids). A run snapshots the
latest active version of each case and stays `queued` until the runner (S2) picks it up.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import AnchorError, parse_anchor
from backend.postgres.enums import (
    AuditEntityType,
    BenchmarkCaseStatus,
    BenchmarkCategory,
    BenchmarkRunStatus,
    FailureClass,
)
from backend.postgres.models import AuditEvent, BenchmarkCase, BenchmarkResult, BenchmarkRun

CASE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$"

# ---------------------------------------------------------------- case spec (file 08 §5.3)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedNumeric(_Strict):
    metric: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1, description="pint-parsable; the judge converts units")
    tolerance_pct: float = Field(default=1.0, ge=0)


class ExpectedCitation(_Strict):
    file_name: str | None = None
    doc_id: uuid.UUID | None = None
    standard_id: str | None = None
    page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _names_a_source(self) -> "ExpectedCitation":
        if not (self.file_name or self.doc_id or self.standard_id):
            raise ValueError("a citation needs file_name, doc_id or standard_id")
        return self


class ExpectedTools(_Strict):
    tools: list[str] = Field(min_length=1)
    ordered: bool = False


class ExpectedBehavior(StrEnum):
    MUST_CLARIFY = "must_clarify"
    MUST_STATE_INSUFFICIENT_EVIDENCE = "must_state_insufficient_evidence"
    MUST_MENTION_HALTED_CASE = "must_mention_halted_case"
    MUST_LABEL_EXTERNAL = "must_label_external"
    MUST_PRESENT_BOTH_CONFLICTING_VALUES = "must_present_both_conflicting_values"


class GoldAnchor(_Strict):
    """A passage that should be retrieved: document plus `<kind>:<value>:<hash>` (file 04 §4.4)."""

    doc_id: uuid.UUID
    anchor: str

    @field_validator("anchor")
    @classmethod
    def _parses(cls, value: str) -> str:
        try:
            parse_anchor(value)
        except AnchorError as exc:
            raise ValueError(str(exc)) from exc
        return value


class CaseSpec(_Strict):
    language: str = "en"
    paraphrases: list[str] = []
    expected_numeric: list[ExpectedNumeric] = []
    expected_citations: list[ExpectedCitation] = []
    must_not_cite: list[ExpectedCitation] = []
    expected_tools: ExpectedTools | None = None
    expected_entities: list[str] = []
    retrieval_gold_anchors: list[GoldAnchor] = []
    expected_behavior: list[ExpectedBehavior] = []
    clarification_answer: str | None = None


# ---------------------------------------------------------------- API models


class CaseContent(_Strict):
    suite: str = Field(min_length=1, max_length=80)
    category: BenchmarkCategory
    question: str = Field(min_length=1, max_length=4000)
    spec: CaseSpec = CaseSpec()
    difficulty: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=4000)


class CaseCreate(CaseContent):
    case_id: str = Field(pattern=CASE_ID)
    status: BenchmarkCaseStatus = BenchmarkCaseStatus.ACTIVE


class DraftFromChat(CaseContent):
    """Add-to-benchmark action (file 08 §2.2): a draft a reviewer approves in the Console."""

    suite: str = Field(default="from-chat", min_length=1, max_length=80)
    source_trace_id: uuid.UUID


class CaseView(BaseModel):
    case_id: str
    version: int
    suite: str
    status: BenchmarkCaseStatus
    category: BenchmarkCategory
    question: str
    spec: CaseSpec
    difficulty: int | None
    notes: str | None
    source_trace_id: uuid.UUID | None
    created_by: str
    created_at: datetime


class BenchmarkCaseList(BaseModel):
    items: list[CaseView]


class RunSummary(BaseModel):
    run_id: uuid.UUID
    status: BenchmarkRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    pass_rate: float | None


class SuiteSummary(BaseModel):
    suite: str
    cases_by_status: dict[str, int]
    cases_by_category: dict[str, int]
    last_run: RunSummary | None


class RunRequest(_Strict):
    suite: str = Field(min_length=1, max_length=80)
    case_ids: list[str] | None = Field(default=None, description="a subset of the suite; default all active")
    git_commit: str | None = Field(default=None, max_length=64)


class RunView(BaseModel):
    run_id: uuid.UUID
    suite: str
    status: BenchmarkRunStatus
    case_versions: dict[str, int]
    git_commit: str | None
    model_config_snapshot: dict[str, Any] = Field(alias="model_config")
    pipeline_version: int | None
    active_doc_count: int | None
    started_at: datetime | None
    finished_at: datetime | None
    aggregate: dict[str, Any]

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class ResultView(BaseModel):
    case_id: str
    case_version: int
    trace_id: uuid.UUID | None
    passed: bool | None
    failure_class: FailureClass | None
    latency_ms: int | None
    cost_estimate: float | None
    metrics: dict[str, Any]


class RunResults(BaseModel):
    run: RunView
    results: list[ResultView]


class CaseDelta(BaseModel):
    case_id: str
    base_passed: bool | None
    head_passed: bool | None
    base_failure_class: FailureClass | None
    head_failure_class: FailureClass | None


class RunComparison(BaseModel):
    base: RunView
    head: RunView
    newly_failing: list[CaseDelta]
    newly_passing: list[CaseDelta]
    still_failing: list[CaseDelta]
    aggregate_delta: dict[str, float]
    config_diff: dict[str, dict[str, Any]]


class SuiteExport(BaseModel):
    suite: str
    exported_at: datetime
    cases: list[CaseCreate]


class SuiteImport(_Strict):
    cases: list[CaseCreate] = Field(min_length=1)


class ImportCounts(BaseModel):
    created: int
    versioned: int
    unchanged: int


class Problem(LookupError):
    """A request the data refuses: status code and message for the router."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------- queries (plain functions over a Session)


def _view(row: BenchmarkCase) -> CaseView:
    return CaseView(
        case_id=row.case_id,
        version=row.version,
        suite=row.suite,
        status=row.status,
        category=row.category,
        question=row.question,
        spec=CaseSpec.model_validate(row.spec or {}),
        difficulty=row.difficulty,
        notes=row.notes,
        source_trace_id=row.source_trace_id,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _run_view(row: BenchmarkRun) -> RunView:
    return RunView(
        run_id=row.run_id,
        suite=row.suite,
        status=row.status,
        case_versions=row.case_versions or {},
        git_commit=row.git_commit,
        model_config=row.model_config or {},
        pipeline_version=row.pipeline_version,
        active_doc_count=row.active_doc_count,
        started_at=row.started_at,
        finished_at=row.finished_at,
        aggregate=row.aggregate or {},
    )


def _audit(session: Session, actor: str, case_id: str, action: str, before: Any, after: Any) -> None:
    session.add(
        AuditEvent(
            actor=actor,
            entity_type=AuditEntityType.BENCHMARK_CASE,
            entity_id=case_id,
            action=action,
            before=before,
            after=after,
        )
    )


def _latest_versions():
    """Subquery: (case_id, version) of the newest version of every case."""
    return (
        select(BenchmarkCase.case_id, func.max(BenchmarkCase.version).label("version"))
        .group_by(BenchmarkCase.case_id)
        .subquery()
    )


def _latest(session: Session, case_id: str) -> BenchmarkCase | None:
    stmt = select(BenchmarkCase).where(BenchmarkCase.case_id == case_id)
    return session.scalars(stmt.order_by(BenchmarkCase.version.desc()).limit(1)).first()


def list_cases(
    session: Session,
    suite: str | None = None,
    status_: BenchmarkCaseStatus | None = None,
    category: BenchmarkCategory | None = None,
) -> BenchmarkCaseList:
    latest = _latest_versions()
    stmt = select(BenchmarkCase).join(
        latest, (BenchmarkCase.case_id == latest.c.case_id) & (BenchmarkCase.version == latest.c.version)
    )
    if suite:
        stmt = stmt.where(BenchmarkCase.suite == suite)
    if status_:
        stmt = stmt.where(BenchmarkCase.status == status_)
    if category:
        stmt = stmt.where(BenchmarkCase.category == category)
    return BenchmarkCaseList(items=[_view(r) for r in session.scalars(stmt.order_by(BenchmarkCase.case_id))])


def case_history(session: Session, case_id: str) -> list[CaseView]:
    stmt = (
        select(BenchmarkCase).where(BenchmarkCase.case_id == case_id).order_by(BenchmarkCase.version.desc())
    )
    rows = list(session.scalars(stmt))
    if not rows:
        raise Problem(404, f"no case {case_id}")
    return [_view(r) for r in rows]


def _content(row: BenchmarkCase) -> dict[str, Any]:
    return {
        "suite": row.suite,
        "category": row.category,
        "question": row.question,
        "spec": row.spec,
        "difficulty": row.difficulty,
        "notes": row.notes,
    }


def create_case(session: Session, body: CaseCreate, actor: str) -> CaseView:
    if _latest(session, body.case_id) is not None:
        raise Problem(409, f"case {body.case_id} exists; add a version instead")
    row = BenchmarkCase(
        case_id=body.case_id,
        version=1,
        status=body.status,
        created_by=actor,
        **body.model_dump(
            mode="json", include={"suite", "category", "question", "spec", "difficulty", "notes"}
        ),
    )
    session.add(row)
    session.flush()
    _audit(
        session, actor, body.case_id, "create", None, {"version": 1, "status": body.status, **_content(row)}
    )
    return _view(row)


def add_version(session: Session, case_id: str, body: CaseContent, actor: str) -> CaseView:
    """An edit is a new version carrying the previous status; stored versions never change."""
    previous = _latest(session, case_id)
    if previous is None:
        raise Problem(404, f"no case {case_id}")
    row = BenchmarkCase(
        case_id=case_id,
        version=previous.version + 1,
        status=previous.status,
        source_trace_id=previous.source_trace_id,
        created_by=actor,
        **body.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        actor,
        case_id,
        "new_version",
        _content(previous) | {"version": previous.version},
        _content(row) | {"version": row.version},
    )
    return _view(row)


def set_status(
    session: Session,
    case_id: str,
    new_status: BenchmarkCaseStatus,
    actor: str,
    require: BenchmarkCaseStatus | None,
) -> CaseView:
    row = _latest(session, case_id)
    if row is None:
        raise Problem(404, f"no case {case_id}")
    if require is not None and row.status != require:
        raise Problem(409, f"case {case_id} v{row.version} is {row.status}, not {require}")
    before = row.status
    row.status = new_status
    session.flush()
    action = "approve" if new_status == BenchmarkCaseStatus.ACTIVE else str(new_status)
    _audit(
        session,
        actor,
        case_id,
        action,
        {"version": row.version, "status": before},
        {"version": row.version, "status": new_status},
    )
    return _view(row)


def draft_from_chat(session: Session, body: DraftFromChat, actor: str) -> CaseView:
    case_id = f"chat-{uuid.uuid4().hex[:12]}"
    row = BenchmarkCase(
        case_id=case_id,
        version=1,
        status=BenchmarkCaseStatus.DRAFT,
        created_by=actor,
        source_trace_id=body.source_trace_id,
        **body.model_dump(mode="json", exclude={"source_trace_id"}),
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        actor,
        case_id,
        "draft_from_chat",
        None,
        {"version": 1, **_content(row), "source_trace_id": str(body.source_trace_id)},
    )
    return _view(row)


def _pass_rate(session: Session, run_id: uuid.UUID) -> float | None:
    passed, total = session.execute(
        select(func.count().filter(BenchmarkResult.passed.is_(True)), func.count()).where(
            BenchmarkResult.run_id == run_id
        )
    ).one()
    return round(passed / total, 4) if total else None


def list_suites(session: Session) -> list[SuiteSummary]:
    latest = _latest_versions()
    rows = session.execute(
        select(BenchmarkCase.suite, BenchmarkCase.status, BenchmarkCase.category, func.count())
        .join(
            latest, (BenchmarkCase.case_id == latest.c.case_id) & (BenchmarkCase.version == latest.c.version)
        )
        .group_by(BenchmarkCase.suite, BenchmarkCase.status, BenchmarkCase.category)
    ).all()
    suites: dict[str, SuiteSummary] = {}
    for suite, status_, category, count in rows:
        summary = suites.setdefault(
            suite, SuiteSummary(suite=suite, cases_by_status={}, cases_by_category={}, last_run=None)
        )
        summary.cases_by_status[status_] = summary.cases_by_status.get(status_, 0) + count
        if status_ == BenchmarkCaseStatus.ACTIVE:
            summary.cases_by_category[category] = summary.cases_by_category.get(category, 0) + count
    for summary in suites.values():
        run = session.scalars(
            select(BenchmarkRun)
            .where(BenchmarkRun.suite == summary.suite)
            .order_by(BenchmarkRun.started_at.desc().nulls_first(), BenchmarkRun.run_id)
            .limit(1)
        ).first()
        if run is not None:
            summary.last_run = RunSummary(
                run_id=run.run_id,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                pass_rate=_pass_rate(session, run.run_id),
            )
    return sorted(suites.values(), key=lambda s: s.suite)


def start_run(session: Session, body: RunRequest, actor: str) -> RunView:
    active = {
        c.case_id: c.version
        for c in list_cases(session, suite=body.suite, status_=BenchmarkCaseStatus.ACTIVE).items
    }
    if body.case_ids is not None:
        unknown = sorted(set(body.case_ids) - set(active))
        if unknown:
            raise Problem(422, f"not active in suite {body.suite}: {', '.join(unknown)}")
        active = {case_id: active[case_id] for case_id in body.case_ids}
    if not active:
        raise Problem(422, f"suite {body.suite} has no active cases")
    row = BenchmarkRun(
        suite=body.suite,
        case_versions=active,
        git_commit=body.git_commit,
        model_config={"requested_by": actor},
        status=BenchmarkRunStatus.QUEUED,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return _run_view(row)


def list_runs(session: Session, suite: str | None, limit: int) -> list[RunView]:
    stmt = select(BenchmarkRun)
    if suite:
        stmt = stmt.where(BenchmarkRun.suite == suite)
    stmt = stmt.order_by(BenchmarkRun.started_at.desc().nulls_first(), BenchmarkRun.run_id).limit(limit)
    return [_run_view(r) for r in session.scalars(stmt)]


def _run(session: Session, run_id: uuid.UUID) -> BenchmarkRun:
    row = session.get(BenchmarkRun, run_id)
    if row is None:
        raise Problem(404, f"no run {run_id}")
    return row


def run_results(session: Session, run_id: uuid.UUID) -> RunResults:
    run = _run(session, run_id)
    rows = session.scalars(
        select(BenchmarkResult).where(BenchmarkResult.run_id == run_id).order_by(BenchmarkResult.case_id)
    )
    results = [
        ResultView(
            case_id=r.case_id,
            case_version=r.case_version,
            trace_id=r.trace_id,
            passed=r.passed,
            failure_class=r.failure_class,
            latency_ms=r.latency_ms,
            cost_estimate=float(r.cost_estimate) if r.cost_estimate is not None else None,
            metrics=r.metrics or {},
        )
        for r in rows
    ]
    return RunResults(run=_run_view(run), results=results)


def cancel_run(session: Session, run_id: uuid.UUID) -> RunView:
    run = _run(session, run_id)
    if run.status not in (BenchmarkRunStatus.QUEUED, BenchmarkRunStatus.RUNNING):
        raise Problem(409, f"run {run_id} is {run.status}")
    run.status = BenchmarkRunStatus.CANCELLED
    run.finished_at = datetime.now(UTC)
    session.flush()
    return _run_view(run)


def compare_runs(session: Session, base_id: uuid.UUID, head_id: uuid.UUID) -> RunComparison:
    base, head = run_results(session, base_id), run_results(session, head_id)
    before = {r.case_id: r for r in base.results}
    newly_failing, newly_passing, still_failing = [], [], []
    for r in head.results:
        b = before.get(r.case_id)
        delta = CaseDelta(
            case_id=r.case_id,
            base_passed=b.passed if b else None,
            head_passed=r.passed,
            base_failure_class=b.failure_class if b else None,
            head_failure_class=r.failure_class,
        )
        if r.passed is False and (b is None or b.passed is not False):
            newly_failing.append(delta)
        elif r.passed is True and b is not None and b.passed is False:
            newly_passing.append(delta)
        elif r.passed is False:
            still_failing.append(delta)
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    aggregate_delta = {
        key: round(head.run.aggregate[key] - base.run.aggregate[key], 6)
        for key in sorted(set(base.run.aggregate) & set(head.run.aggregate))
        if numeric(base.run.aggregate[key]) and numeric(head.run.aggregate[key])
    }
    config = lambda run: {  # noqa: E731
        **{f"model_config.{k}": v for k, v in run.model_config_snapshot.items()},
        "git_commit": run.git_commit,
        "pipeline_version": run.pipeline_version,
        "active_doc_count": run.active_doc_count,
    }
    b_config, h_config = config(base.run), config(head.run)
    config_diff = {
        key: {"base": b_config.get(key), "head": h_config.get(key)}
        for key in sorted(set(b_config) | set(h_config))
        if b_config.get(key) != h_config.get(key)
    }
    return RunComparison(
        base=base.run,
        head=head.run,
        newly_failing=newly_failing,
        newly_passing=newly_passing,
        still_failing=still_failing,
        aggregate_delta=aggregate_delta,
        config_diff=config_diff,
    )


def export_suite(session: Session, suite: str) -> SuiteExport:
    cases = [
        CaseCreate(
            case_id=c.case_id,
            status=c.status,
            **c.model_dump(include={"suite", "category", "question", "spec", "difficulty", "notes"}),
        )
        for c in list_cases(session, suite=suite).items
        if c.status != BenchmarkCaseStatus.RETIRED
    ]
    return SuiteExport(suite=suite, exported_at=datetime.now(UTC), cases=cases)


def import_suite(session: Session, suite: str, body: SuiteImport, actor: str) -> ImportCounts:
    counts = ImportCounts(created=0, versioned=0, unchanged=0)
    for case in body.cases:
        if case.suite != suite:
            raise Problem(422, f"case {case.case_id} belongs to suite {case.suite}, not {suite}")
        previous = _latest(session, case.case_id)
        content = case.model_dump(
            mode="json", include={"suite", "category", "question", "spec", "difficulty", "notes"}
        )
        if previous is None:
            create_case(session, case, actor)
            counts.created += 1
        elif _content(previous) == content:
            counts.unchanged += 1
        else:
            add_version(session, case.case_id, CaseContent.model_validate(content), actor)
            counts.versioned += 1
    return counts
