"""Ops endpoints for the Console OpsPage (file 08 §4.2, §4.4; file 10 §4). Owner: S3.

`GET /ops/failed-tasks` lists the Celery dead-letter list newest first, read through S4's
`backend.celery_redis.app.dead_letters`. That module builds the Celery app on import and needs the Redis
settings, so it is imported only when the route runs. There is no retry: the stored args are shortened
reprs and cannot be replayed.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ValidationError

from backend.api.auth import ConsoleRole, ConsoleUser, require_role

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
