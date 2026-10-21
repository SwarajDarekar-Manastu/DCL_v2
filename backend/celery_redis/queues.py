"""Celery queues and worker pools of docs/architecture/10 §4. The single source for names and limits.

backend/devops/compose.yaml runs one worker container per queue with exactly these values; a unit test keeps
the two in step. Time limits and retries are S4's initial values, tuned after the M1 queue load test.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Queue(StrEnum):
    IO_LIGHT = "io_light"
    CPU_PARSE = "cpu_parse"
    TELEMETRY_STREAM = "telemetry_stream"
    MEDIA = "media"
    VISION_BATCH = "vision_batch"
    EMBED = "embed"


@dataclass(frozen=True)
class Pool:
    queue: Queue
    pool: Literal["threads", "prefork"]
    concurrency: int
    memory_limit_mb: int
    max_memory_per_child_mb: int | None
    soft_time_limit_s: int
    time_limit_s: int
    max_retries: int

    @property
    def worker_args(self) -> list[str]:
        args = [
            "--queues",
            str(self.queue),
            "--pool",
            self.pool,
            "--concurrency",
            str(self.concurrency),
            "--soft-time-limit",
            str(self.soft_time_limit_s),
            "--time-limit",
            str(self.time_limit_s),
        ]
        if self.max_memory_per_child_mb is not None:
            args += ["--max-memory-per-child", str(self.max_memory_per_child_mb * 1024)]
        return args


POOLS: dict[Queue, Pool] = {
    pool.queue: pool
    for pool in (
        Pool(Queue.IO_LIGHT, "threads", 4, 1024, None, 300, 360, 5),
        Pool(Queue.CPU_PARSE, "prefork", 4, 4 * 6144, 6144, 1800, 2100, 2),
        Pool(Queue.TELEMETRY_STREAM, "prefork", 2, 2 * 3072, 3072, 3600, 3900, 2),
        Pool(Queue.MEDIA, "prefork", 2, 4096, 2048, 3600, 3900, 2),
        Pool(Queue.VISION_BATCH, "threads", 2, 1024, None, 900, 1000, 5),
        Pool(Queue.EMBED, "threads", 2, 2048, None, 600, 660, 5),
    )
}
VISIBILITY_TIMEOUT_S = 2 * max(pool.time_limit_s for pool in POOLS.values())

DEAD_LETTER_KEY = "dcl:dead_letter"
DEAD_LETTER_MAX = 10_000
MAX_DELIVERIES = 3
"""A task whose worker died this many times (OOM kill, crash) is dead-lettered instead of redelivered."""
