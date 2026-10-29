"""Ops endpoints for the Console OpsPage (file 08 §4.2, §4.4; file 10 §4). Owner: S3.

`GET /ops/summary` (viewer): Celery queue depths (Redis list lengths, as S4's `celery_queue_depth` gauge),
files per pipeline step (`file_steps.py`; `GET /ops/steps/{step}` lists one step's files), documents by
status, open HARD/SOFT flags, the latest run per benchmark suite, and tokens/cost today from `llm_calls`
once S1's model exists (Lead ruling 2026-10-23: read-only reads of S1's tables, as viewer.py).
Each part is read on its own; a part that cannot be read is null with a note, never a failed page.

`GET /ops/failed-tasks` lists the Celery dead-letter list newest first, read through S4's
`backend.celery_redis.app.dead_letters`. That module builds the Celery app on import and needs the Redis
settings, so it is imported only when the route runs. There is no retry: the stored args are shortened
reprs and cannot be replayed.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.api.file_steps import (
    JobsReader,
    Step,
    StepCount,
    StepFiles,
    count_steps,
    get_jobs_reader,
    list_step,
)
from backend.postgres.session import get_session

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"])

DeadLetterReader = Callable[[int], list[dict]]


class FailedTask(BaseModel):
    task_id: str
    task: str
    queue: str | None
    args: str
    kwargs: str
    error: str
    retries: int
    at: datetime


class FailedTasks(BaseModel):
    items: list[FailedTask]


def get_dead_letter_reader() -> DeadLetterReader:
    from backend.celery_redis.app import dead_letters

    return dead_letters


def _parse(entries: list[dict]) -> list[FailedTask]:
    items = []
    for entry in entries:
        try:
            items.append(FailedTask.model_validate(entry))
        except ValidationError:
            log.warning("skipping a malformed dead-letter entry: %s", str(entry)[:200])
    return items


@router.get("/failed-tasks", response_model=FailedTasks)
def failed_tasks(
    _: Annotated[ConsoleUser, Depends(require_role(ConsoleRole.ADMIN))],
    read: Annotated[DeadLetterReader, Depends(get_dead_letter_reader)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> FailedTasks:
    try:
        entries = read(limit)
    except Exception as exc:  # Redis down or misconfigured: the page says so instead of a 500
        log.warning("dead-letter list unavailable: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "the failed-task list is unavailable"
        ) from exc
    return FailedTasks(items=_parse(entries))


# ---------------------------------------------------------------- summary


class QueueDepth(BaseModel):
    queue: str
    waiting: int


class SuiteRun(BaseModel):
    suite: str
    run_id: str
    status: str
    pass_rate: float | None
    cases_done: int | None
    cases_total: int | None
    started_at: datetime | None
    finished_at: datetime | None


class LlmToday(BaseModel):
    """Today's model calls (UTC) from `llm_calls` (file 05: input/output/cached tokens, cost_estimate)."""

    calls: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_estimate: float | None


class OpsSummary(BaseModel):
    queues: list[QueueDepth] | None
    steps: list[StepCount] | None
    documents_by_status: dict[str, int] | None
    open_flags: dict[str, int] | None
    last_runs: list[SuiteRun] | None
    llm_today: LlmToday | None
    notes: dict[str, str]


QueueReader = Callable[[], dict[str, int]]


def get_queue_reader() -> QueueReader:
    """Redis list length per Celery queue; the Celery app module is imported only when called."""

    def read() -> dict[str, int]:
        from backend.celery_redis.app import broker
        from backend.celery_redis.queues import Queue

        client = broker()
        return {str(q): int(client.llen(str(q))) for q in Queue}

    return read


def _documents_by_status(session: Session) -> dict[str, int]:
    from backend.postgres.models import Document

    rows = session.execute(select(Document.status, func.count()).group_by(Document.status))
    return {status_: n for status_, n in rows}


def _open_flags(session: Session) -> dict[str, int]:
    from backend.postgres.enums import FlagStatus
    from backend.postgres.models import ReviewFlag

    open_states = [FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED]
    rows = session.execute(
        select(ReviewFlag.severity, func.count())
        .where(ReviewFlag.status.in_([str(s) for s in open_states]))
        .group_by(ReviewFlag.severity)
    )
    counts = {"HARD": 0, "SOFT": 0}
    counts.update({severity: n for severity, n in rows})
    return counts


def _last_runs(session: Session) -> list[SuiteRun]:
    from backend.postgres.models import BenchmarkRun

    latest = (
        select(BenchmarkRun.suite, func.max(BenchmarkRun.started_at).label("started_at"))
        .group_by(BenchmarkRun.suite)
        .subquery()
    )
    rows = session.scalars(
        select(BenchmarkRun)
        .join(
            latest, (BenchmarkRun.suite == latest.c.suite) & (BenchmarkRun.started_at == latest.c.started_at)
        )
        .order_by(BenchmarkRun.suite)
    )
    out = []
    for run in rows:
        agg = run.aggregate or {}
        out.append(
            SuiteRun(
                suite=run.suite,
                run_id=str(run.run_id),
                status=str(run.status),
                pass_rate=agg.get("pass_rate"),
                cases_done=agg.get("cases_done"),
                cases_total=agg.get("cases_total"),
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
        )
    return out


def _llm_today(session: Session) -> LlmToday:
    from backend.postgres import models

    model = getattr(models, "LlmCall", None)
    if model is None:
        raise LookupError("llm_calls is not available yet (S1 migration 0012)")
    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    calls, tokens_in, tokens_out, cached, cost = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(model.input_tokens), 0),
            func.coalesce(func.sum(model.output_tokens), 0),
            func.coalesce(func.sum(model.cached_tokens), 0),
            func.sum(model.cost_estimate),
        ).where(model.at >= since)
    ).one()
    return LlmToday(
        calls=calls,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cached_tokens=cached,
        cost_estimate=float(cost) if cost is not None else None,
    )


def _part(notes: dict[str, str], name: str, read: Callable[[], Any], session: Session | None = None) -> Any:
    try:
        return read()
    except Exception as exc:  # one unreadable part must not hide the others
        if session is not None:
            session.rollback()
        notes[name] = str(exc) if isinstance(exc, LookupError) else f"unavailable ({type(exc).__name__})"
        log.warning("ops summary: %s unavailable: %s", name, exc)
        return None


class UsageRow(BaseModel):
    """One day, model and task of `llm_calls`. A failed call whose reply came back carries tokens and is
    billed like any other; a cache hit carries none."""

    day: date
    model: str
    purpose: str
    calls: int
    billed_calls: int = Field(description="calls that used tokens, failed ones included")
    cache_hits: int = Field(description="answered from the result cache: no cost")
    errors: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: float | None = Field(description="the cost each call recorded at the price then in force")
    unpriced_calls: int = Field(description="billed calls recorded while the model had no price")


COUNTS = ("calls", "billed_calls", "cache_hits", "errors", "input_tokens", "output_tokens", "unpriced_calls")


class ModelTotal(BaseModel):
    model: str
    calls: int
    billed_calls: int
    cache_hits: int
    errors: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    unpriced_calls: int


class LlmUsage(BaseModel):
    days: int
    rows: list[UsageRow]
    by_model: list[ModelTotal]
    total_cost_usd: float | None


def llm_usage(session: Session, days: int) -> LlmUsage:
    """Gemini use per day, model and task over the last `days` days (UTC). Each call's cost is the one the
    gateway client recorded from `models.prices` when it ran, so a price change never rewrites history."""
    from backend.postgres import models

    model = models.LlmCall
    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    day = func.date_trunc("day", model.at).label("day")
    billed = (model.input_tokens + model.output_tokens) > 0
    rows = session.execute(
        select(
            day,
            model.model,
            model.purpose,
            func.count(),
            func.count().filter(billed),
            func.count().filter(model.status == "cache_hit"),
            func.count().filter(model.status.notin_(("ok", "cache_hit"))),
            func.coalesce(func.sum(model.input_tokens), 0),
            func.coalesce(func.sum(model.output_tokens), 0),
            func.coalesce(func.sum(model.cached_tokens), 0),
            func.sum(model.cost_estimate),
            func.count().filter(billed & model.cost_estimate.is_(None)),
        )
        .where(model.at >= since)
        .group_by(day, model.model, model.purpose)
        .order_by(day.desc(), model.model, model.purpose)
    ).all()
    out = [
        UsageRow(
            day=d.date(),
            model=name,
            purpose=purpose,
            calls=calls,
            billed_calls=n_billed,
            cache_hits=hits,
            errors=errors,
            input_tokens=t_in,
            output_tokens=t_out,
            cached_tokens=cached,
            cost_usd=round(float(cost), 6) if cost is not None else None,
            unpriced_calls=unpriced,
        )
        for d, name, purpose, calls, n_billed, hits, errors, t_in, t_out, cached, cost, unpriced in rows
    ]
    by_model = []
    for name in sorted({r.model for r in out}):
        mine = [r for r in out if r.model == name]
        costs = [r.cost_usd for r in mine if r.cost_usd is not None]
        by_model.append(
            ModelTotal(
                model=name,
                **{key: sum(getattr(r, key) for r in mine) for key in COUNTS},
                cost_usd=round(sum(costs), 6) if costs else None,
            )
        )
    costs = [t.cost_usd for t in by_model if t.cost_usd is not None]
    return LlmUsage(
        days=days,
        rows=out,
        by_model=by_model,
        total_cost_usd=round(sum(costs), 4) if costs else None,
    )


@router.get("/llm-usage", response_model=LlmUsage)
def get_llm_usage(
    _: Annotated[ConsoleUser, Depends(require_role(ConsoleRole.VIEWER))],
    session: Annotated[Session, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> LlmUsage:
    return llm_usage(session, days)


@router.get("/summary", response_model=OpsSummary)
def summary(
    _: Annotated[ConsoleUser, Depends(require_role(ConsoleRole.VIEWER))],
    session: Annotated[Session, Depends(get_session)],
    read_queues: Annotated[QueueReader, Depends(get_queue_reader)],
    read_jobs: Annotated[JobsReader, Depends(get_jobs_reader)],
) -> OpsSummary:
    notes: dict[str, str] = {}
    depths = _part(notes, "queues", read_queues)
    return OpsSummary(
        queues=[QueueDepth(queue=q, waiting=n) for q, n in depths.items()] if depths is not None else None,
        steps=_part(notes, "steps", lambda: count_steps(session, read_jobs(False)), session),
        documents_by_status=_part(
            notes, "documents_by_status", lambda: _documents_by_status(session), session
        ),
        open_flags=_part(notes, "open_flags", lambda: _open_flags(session), session),
        last_runs=_part(notes, "last_runs", lambda: _last_runs(session), session),
        llm_today=_part(notes, "llm_today", lambda: _llm_today(session), session),
        notes=notes,
    )


@router.get("/steps/{step}", response_model=StepFiles)
def step_files(
    step: Step,
    _: Annotated[ConsoleUser, Depends(require_role(ConsoleRole.VIEWER))],
    session: Annotated[Session, Depends(get_session)],
    read_jobs: Annotated[JobsReader, Depends(get_jobs_reader)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> StepFiles:
    try:
        jobs = read_jobs(step == Step.IN_LINE)
    except Exception as exc:  # Redis down: the list says so instead of a 500
        log.warning("job list unavailable: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the job list is unavailable") from exc
    return list_step(session, step, jobs, limit)
