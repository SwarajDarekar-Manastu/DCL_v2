"""Celery beat schedule (S4 owns the schedule; the tasks belong to their features).

Crontabs are read in BEAT_TIMEZONE (the team's local time); timestamps stay UTC. The daily delta follows
pipeline_config `sync.daily_delta_cron` once that key exists (docs/architecture/02 §3.6); until then 02:00.
Still to come when their tasks exist: nightly retention (05 §6), webhook subscription renewal.
"""

from celery.schedules import crontab

from backend.celery_redis.queues import Queue

BEAT_TIMEZONE = "Asia/Kolkata"

BEAT_SCHEDULE: dict[str, dict] = {
    "sync-delta-all-daily": {
        "task": "dcl.sync.delta_all",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": str(Queue.IO_LIGHT)},
    },
    "sync-token-health": {
        "task": "dcl.sync.token_health",
        "schedule": 15 * 60.0,
        "options": {"queue": str(Queue.IO_LIGHT)},
    },
    "process-dispatch": {
        "task": "dcl.process.dispatch",
        "schedule": 30 * 60.0,
        "options": {"queue": str(Queue.IO_LIGHT)},
    },
    "process-sweep-documents-daily": {
        "task": "dcl.process.sweep_documents",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": str(Queue.IO_LIGHT)},
    },
    "sync-enqueue-downloads": {
        "task": "dcl.sync.enqueue_downloads",
        "schedule": 10 * 60.0,
        "options": {"queue": str(Queue.IO_LIGHT)},
    },
    "benchmark-sweep": {
        "task": "dcl.benchmark.sweep",
        "schedule": 60.0,
        "options": {"queue": str(Queue.IO_LIGHT)},
    },
}
