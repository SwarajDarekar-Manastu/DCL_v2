"""Celery beat schedule (S4 owns the schedule; the tasks belong to their features).

Crontabs are read in BEAT_TIMEZONE (the team's local time); timestamps stay UTC. The daily delta follows
pipeline_config `sync.daily_delta_cron` once that key exists (docs/architecture/02 §3.6); until then 02:00.
The delta poll every 5 minutes is the real-time path on this LAN host (DECISIONS 2026-10-23); the renewal runs
hourly and does nothing until pipeline_config `sync.webhooks_enabled` is true. Still to come when its task
exists: nightly retention (05 §6).
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
    "sync-delta-poll": {
        "task": "dcl.sync.poll_deltas",
        "schedule": 5 * 60.0,
        "options": {"queue": str(Queue.IO_LIGHT)},
    },
    "sync-renew-subscriptions": {
        "task": "dcl.sync.renew_subscriptions",
        "schedule": crontab(minute=0),
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
        "options": {"queue": str(Queue.BENCHMARK)},
    },
}
