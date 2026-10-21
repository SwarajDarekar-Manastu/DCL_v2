"""Celery beat schedule (S4 owns the schedule; the tasks belong to their features).

Entries are added when their task exists: daily full delta (`sync.daily_delta_cron`), token health,
nightly retention (docs/architecture/05 §6), webhook subscription renewal.
"""

BEAT_SCHEDULE: dict[str, dict] = {}
