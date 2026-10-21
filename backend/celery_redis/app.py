"""The Celery app shared by every worker and beat (docs/architecture/10 §4).

Workers start with `celery -A backend.celery_redis.app worker --hostname <queue>@%h <Pool.worker_args>`; the
compose file holds the exact commands. Task modules are imported when they exist, so features add a
`tasks_*.py` file and their tasks register without touching this module.

Every task runs through DclTask: deliveries are counted per task id, so a task whose worker keeps dying
(OOM kill, crash; acks_late redelivers it) is stopped after MAX_DELIVERIES, and every final failure is
recorded in the dead-letter list `dcl:dead_letter` that the Console's "Failed tasks" page reads.
"""

import importlib.util
import json
from datetime import UTC, datetime
from functools import cache

import redis
from celery import Celery, Task, signals
from kombu import Exchange
from kombu import Queue as KombuQueue

from backend.celery_redis.beat import BEAT_SCHEDULE, BEAT_TIMEZONE
from backend.celery_redis.queues import (
    DEAD_LETTER_KEY,
    DEAD_LETTER_MAX,
    MAX_DELIVERIES,
    VISIBILITY_TIMEOUT_S,
    Queue,
)
from backend.common.telemetry import instrument_celery, setup_telemetry
from backend.config import Group, get_settings

TASK_MODULES = (
    "backend.celery_redis.tasks_loadtest",
    "backend.celery_redis.tasks_sync",
    "backend.celery_redis.tasks_process",
    "backend.celery_redis.tasks_embed",
    "backend.celery_redis.tasks_review",
)


def present_task_modules() -> list[str]:
    return [name for name in TASK_MODULES if importlib.util.find_spec(name) is not None]


DELIVERY_KEY = "dcl:deliveries:{}"
TEXT_LIMIT = 500


class PoisonTask(RuntimeError):
    """Raised instead of running a task whose worker was lost MAX_DELIVERIES times."""


@cache
def broker() -> redis.Redis:
    return redis.Redis.from_url(get_settings().require(Group.REDIS).redis_url, socket_timeout=5)


def _short(value) -> str:
    text = repr(value)
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…"


def record_dead_letter(
    task_id: str, name: str, queue: str | None, args, kwargs, exc: BaseException, retries: int
) -> None:
    entry = {
        "task_id": task_id,
        "task": name,
        "queue": queue,
        "args": _short(args),
        "kwargs": _short(kwargs),
        "error": f"{type(exc).__name__}: {_short(str(exc))}",
        "retries": retries,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    pipe = broker().pipeline()
    pipe.lpush(DEAD_LETTER_KEY, json.dumps(entry))
    pipe.ltrim(DEAD_LETTER_KEY, 0, DEAD_LETTER_MAX - 1)
    pipe.execute()


def dead_letters(limit: int = 100) -> list[dict]:
    """Newest first; for the Console "Failed tasks" page and the load test."""
    return [json.loads(raw) for raw in broker().lrange(DEAD_LETTER_KEY, 0, limit - 1)]


class DclTask(Task):
    def __call__(self, *args, **kwargs):
        if self.request.is_eager or not self.request.id:
            return super().__call__(*args, **kwargs)
        key = DELIVERY_KEY.format(self.request.id)
        deliveries = broker().incr(key)
        broker().expire(key, 24 * 3600)
        if deliveries > MAX_DELIVERIES:
            raise PoisonTask(f"worker lost {deliveries - 1} times while running this task")
        try:
            return super().__call__(*args, **kwargs)
        finally:
            broker().delete(key)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        queue = (self.request.delivery_info or {}).get("routing_key")
        try:
            record_dead_letter(task_id, self.name, queue, args, kwargs, exc, self.request.retries)
        except redis.RedisError:
            pass


def create_celery() -> Celery:
    redis_url = get_settings().require(Group.REDIS).redis_url
    app = Celery("dcl", broker=redis_url, backend=redis_url, include=present_task_modules(), task_cls=DclTask)
    exchange = Exchange("dcl", type="direct")
    app.conf.update(
        task_queues=[KombuQueue(str(q), exchange, routing_key=str(q)) for q in Queue],
        task_default_queue=str(Queue.IO_LIGHT),
        task_default_exchange="dcl",
        task_default_routing_key=str(Queue.IO_LIGHT),
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,
        worker_send_task_events=True,
        task_send_sent_event=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=24 * 3600,
        timezone=BEAT_TIMEZONE,
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT_S},
        beat_schedule=BEAT_SCHEDULE,
    )
    return app


app = create_celery()


@signals.worker_process_init.connect
def _telemetry_in_worker_process(**_) -> None:
    setup_telemetry("dcl-worker")
    instrument_celery()


@signals.beat_init.connect
def _telemetry_in_beat(**_) -> None:
    setup_telemetry("dcl-beat")


@app.task(name="dcl.ping")
def ping() -> str:
    return "pong"
