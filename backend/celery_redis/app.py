"""The Celery app shared by every worker and beat (docs/architecture/10 §4).

Workers start with `celery -A backend.celery_redis.app worker --hostname <queue>@%h <Pool.worker_args>`; the
compose file holds the exact commands. Task modules are imported when they exist, so features add a
`tasks_*.py` file and their tasks register without touching this module.
"""

import importlib.util

from celery import Celery, signals
from kombu import Exchange
from kombu import Queue as KombuQueue

from backend.celery_redis.beat import BEAT_SCHEDULE, BEAT_TIMEZONE
from backend.celery_redis.queues import VISIBILITY_TIMEOUT_S, Queue
from backend.common.telemetry import instrument_celery, setup_telemetry
from backend.config import Group, get_settings

TASK_MODULES = (
    "backend.celery_redis.tasks_sync",
    "backend.celery_redis.tasks_process",
    "backend.celery_redis.tasks_embed",
    "backend.celery_redis.tasks_review",
)


def present_task_modules() -> list[str]:
    return [name for name in TASK_MODULES if importlib.util.find_spec(name) is not None]


def create_celery() -> Celery:
    redis_url = get_settings().require(Group.REDIS).redis_url
    app = Celery("dcl", broker=redis_url, backend=redis_url, include=present_task_modules())
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
