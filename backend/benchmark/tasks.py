"""Celery tasks of the benchmark runner, on `io_light` (soft limit 300 s per task, so one task per case).

- `dcl.benchmark.start(run_id)`: claim a QUEUED run and enqueue one `dcl.benchmark.case` per pending case.
- `dcl.benchmark.case(run_id, case_id)`: answer, score and record one case; the last one completes the run.
- `dcl.benchmark.sweep()` (beat, every minute): start QUEUED runs, and re-enqueue the missing cases of a
  RUNNING run whose heartbeat (a Redis key refreshed at start and after every case, expiring after
  STALE_AFTER) is gone, i.e. a lost worker; results are per case, so a repeat only redoes cases without one.
"""

import asyncio
import uuid
from datetime import timedelta
from functools import lru_cache

from sqlalchemy import select

from backend.benchmark import runner
from backend.celery_redis.app import app, broker
from backend.celery_redis.queues import Queue
from backend.postgres.enums import BenchmarkRunStatus
from backend.postgres.models import BenchmarkRun

IO_LIGHT = str(Queue.IO_LIGHT)
STALE_AFTER = timedelta(minutes=15)
START_LOCK = "dcl:benchmark:start:{}"
START_LOCK_S = 600
HEARTBEAT = "dcl:benchmark:alive:{}"


def _beat(run_id) -> None:
    broker().set(HEARTBEAT.format(run_id), "1", ex=int(STALE_AFTER.total_seconds()))


@lru_cache(maxsize=1)
def _deps() -> runner.RunnerDeps:
    return runner.default_deps()


@app.task(name="dcl.benchmark.start", queue=IO_LIGHT)
def start(run_id: str) -> int:
    deps = _deps()
    try:
        pending = runner.start(uuid.UUID(run_id), deps)
    except Exception as exc:
        runner.fail(uuid.UUID(run_id), deps, f"{type(exc).__name__}: {exc}")
        raise
    _beat(run_id)
    for case_id in pending or []:
        case.delay(run_id, case_id)
    return len(pending or [])


@app.task(name="dcl.benchmark.case", queue=IO_LIGHT)
def case(run_id: str, case_id: str) -> bool | None:
    outcome = asyncio.run(runner.run_one(uuid.UUID(run_id), case_id, _deps()))
    _beat(run_id)
    return None if outcome is None else bool(outcome["passed"])


@app.task(name="dcl.benchmark.sweep", queue=IO_LIGHT)
def sweep() -> dict[str, int]:
    deps = _deps()
    started = resumed = 0
    with deps.session_factory() as session:
        queued, running = (
            list(session.scalars(select(BenchmarkRun.run_id).where(BenchmarkRun.status == status)))
            for status in (BenchmarkRunStatus.QUEUED, BenchmarkRunStatus.RUNNING)
        )
    stale = [run_id for run_id in running if not broker().exists(HEARTBEAT.format(run_id))]
    for run_id in queued:
        if broker().set(START_LOCK.format(run_id), "1", nx=True, ex=START_LOCK_S):
            start.delay(str(run_id))
            started += 1
    for run_id in stale:
        with deps.session_factory() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None or run.status != BenchmarkRunStatus.RUNNING:
                continue
            pending = [c.case_id for c in runner.load_cases(session, run)]
        _beat(run_id)
        for case_id in pending:
            case.delay(str(run_id), case_id)
        resumed += bool(pending)
        if not pending:
            runner.complete_if_done(run_id, deps)
    return {"started": started, "resumed": resumed}
