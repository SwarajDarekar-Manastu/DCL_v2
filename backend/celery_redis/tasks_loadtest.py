"""Synthetic tasks for the M1 queue load test (docs/architecture/10 §4, §5 M1). Never scheduled.

Each task records where it ran in Redis under `dcl:loadtest:<run_id>:done`, so the runner
(backend/celery_redis/load_test.py) can prove routing and account for every task.
"""

import json
import time

from backend.celery_redis.app import app, broker

DONE_KEY = "dcl:loadtest:{}:done"
CHUNK = 64 * 1024 * 1024


class InjectedFailure(RuntimeError):
    pass


@app.task(name="dcl.loadtest.noop", bind=True, max_retries=3)
def noop(self, run_id: str, index: int, expected_queue: str, fail_times: int, sleep_ms: int) -> None:
    if self.request.retries < fail_times:
        raise self.retry(
            exc=InjectedFailure(f"injected failure {self.request.retries + 1}/{fail_times}"), countdown=0.2
        )
    time.sleep(sleep_ms / 1000)
    routed = (self.request.delivery_info or {}).get("routing_key")
    worker = (self.request.hostname or "").split("@", 1)[0]
    record = {"expected": expected_queue, "routed": routed, "worker": worker, "retries": self.request.retries}
    broker().hset(DONE_KEY.format(run_id), str(index), json.dumps(record))
    broker().expire(DONE_KEY.format(run_id), 7 * 24 * 3600)


@app.task(name="dcl.loadtest.oom", bind=True)
def oom(self, run_id: str, index: int, target_mb: int) -> None:
    """Allocates and touches memory until the container's cgroup limit kills this worker process."""
    hoard = []
    for _ in range(target_mb * 1024 * 1024 // CHUNK):
        block = bytearray(CHUNK)
        block[::4096] = b"\x01" * len(block[::4096])
        hoard.append(block)
    broker().hset(
        DONE_KEY.format(run_id), str(index), json.dumps({"expected": "oom", "survived_mb": target_mb})
    )
