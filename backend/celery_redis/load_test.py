"""M1 queue load test (docs/architecture/10 §4, §5 M1): routing, retries, dead-letter, OOM, no loss.

Runs inside any backend container of a live stack (it needs the broker), for example:

    docker compose -p dcl-v2 exec worker-io-light python -m backend.celery_redis.load_test --tasks 5000

Plan: `--tasks` synthetic no-op tasks spread evenly over the six queues; a `--transient` share fails once
or twice and succeeds on retry; a `--permanent` share fails past max_retries and must be dead-lettered;
`--oom` extra tasks on telemetry_stream allocate memory until the container kills their worker process
and must be dead-lettered after MAX_DELIVERIES. The run passes when every task is done on the queue it was
routed to, or dead-lettered for the expected reason. Container-level containment (no other worker
restarted or killed) is checked by backend/devops/ci/queue_load_test.sh around this script.
"""

import argparse
import json
import random
import sys
import time
import uuid
from dataclasses import dataclass, field

from backend.celery_redis.app import broker, dead_letters
from backend.celery_redis.queues import MAX_DELIVERIES, POOLS, Queue
from backend.celery_redis.tasks_loadtest import DONE_KEY, noop, oom

NOOP_QUEUES = [str(q) for q in POOLS]


@dataclass
class Plan:
    run_id: str
    noops: dict[int, tuple[str, int]] = field(default_factory=dict)
    oom: list[int] = field(default_factory=list)

    @property
    def permanent(self) -> set[int]:
        return {i for i, (_, fail) in self.noops.items() if fail > noop.max_retries}

    @property
    def transient(self) -> set[int]:
        return {i for i, (_, fail) in self.noops.items() if 0 < fail <= noop.max_retries}


def make_plan(tasks: int, transient: float, permanent: float, oom_tasks: int, seed: int) -> Plan:
    rng = random.Random(seed)  # noqa: S311 - reproducible test plan, not security
    plan = Plan(run_id=uuid.uuid4().hex[:12])
    for index in range(tasks):
        roll = rng.random()
        fail = (
            noop.max_retries + 1
            if roll < permanent
            else rng.choice((1, 2))
            if roll < permanent + transient
            else 0
        )
        plan.noops[index] = (NOOP_QUEUES[index % len(NOOP_QUEUES)], fail)
    plan.oom = list(range(tasks, tasks + oom_tasks))
    return plan


def enqueue(plan: Plan, oom_mb: int, sleep_ms: int) -> None:
    for index, (queue, fail) in plan.noops.items():
        noop.apply_async(args=(plan.run_id, index, queue, fail, sleep_ms), queue=queue)
    for index in plan.oom:
        oom.apply_async(args=(plan.run_id, index, oom_mb), queue=str(Queue.TELEMETRY_STREAM))


def run_dead_letters(run_id: str) -> dict[int, dict]:
    found = {}
    for entry in dead_letters(limit=20_000):
        if run_id in entry["args"]:
            index = int(entry["args"].split(",")[1].strip())
            found[index] = entry
    return found


def wait(plan: Plan, timeout_s: int) -> tuple[dict[int, dict], dict[int, dict]]:
    expected = len(plan.noops) + len(plan.oom)
    deadline = time.monotonic() + timeout_s
    while True:
        done = {int(k): json.loads(v) for k, v in broker().hgetall(DONE_KEY.format(plan.run_id)).items()}
        dead = run_dead_letters(plan.run_id)
        accounted = len(set(done) | set(dead))
        print(
            f"progress: {accounted}/{expected} accounted ({len(done)} done, {len(dead)} dead-lettered)",
            flush=True,
        )
        if accounted >= expected or time.monotonic() > deadline:
            return done, dead
        time.sleep(5)


def verify(plan: Plan, done: dict[int, dict], dead: dict[int, dict]) -> dict:
    everything = set(plan.noops) | set(plan.oom)
    lost = sorted(everything - set(done) - set(dead))
    misrouted = [
        i
        for i, rec in done.items()
        if i in plan.noops and not (rec["routed"] == rec["expected"] == rec["worker"])
    ]
    retried_ok = all(done[i]["retries"] >= plan.noops[i][1] for i in plan.transient if i in done)
    permanent_ok = all(i in dead and "InjectedFailure" in dead[i]["error"] for i in plan.permanent)
    oom_ok = all(i in dead and "PoisonTask" in dead[i]["error"] for i in plan.oom) and not any(
        i in done for i in plan.oom
    )
    unexpected_dead = sorted(set(dead) - plan.permanent - set(plan.oom))
    report = {
        "run_id": plan.run_id,
        "tasks": len(everything),
        "done": len(done),
        "dead_lettered": len(dead),
        "lost": lost[:20],
        "misrouted": misrouted[:20],
        "unexpected_dead_letters": unexpected_dead[:20],
        "per_queue_done": {q: sum(1 for r in done.values() if r.get("routed") == q) for q in NOOP_QUEUES},
        "transient_retried": retried_ok,
        "permanent_dead_lettered": permanent_ok,
        "oom_dead_lettered_after_max_deliveries": oom_ok,
        "max_deliveries": MAX_DELIVERIES,
    }
    report["passed"] = (
        not lost and not misrouted and not unexpected_dead and retried_ok and permanent_ok and oom_ok
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks", type=int, default=5000)
    parser.add_argument(
        "--transient", type=float, default=0.05, help="share that fails once or twice, then succeeds"
    )
    parser.add_argument("--permanent", type=float, default=0.01, help="share that fails past max_retries")
    parser.add_argument("--oom", type=int, default=2, help="extra memory-hog tasks on telemetry_stream")
    parser.add_argument("--oom-mb", type=int, default=8192)
    parser.add_argument("--sleep-ms", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    plan = make_plan(args.tasks, args.transient, args.permanent, args.oom, args.seed)
    print(
        f"run {plan.run_id}: {len(plan.noops)} no-op tasks over {len(NOOP_QUEUES)} queues, "
        f"{len(plan.transient)} transient failures, {len(plan.permanent)} permanent, {len(plan.oom)} OOM",
        flush=True,
    )
    enqueue(plan, args.oom_mb, args.sleep_ms)
    done, dead = wait(plan, args.timeout)
    report = verify(plan, done, dead)
    print(json.dumps(report, indent=2))
    print("LOAD TEST PASSED" if report["passed"] else "LOAD TEST FAILED")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
