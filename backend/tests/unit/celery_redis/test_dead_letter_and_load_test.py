import json

import pytest

from backend.celery_redis import app as celery_app
from backend.celery_redis import load_test
from backend.celery_redis.queues import DEAD_LETTER_KEY, MAX_DELIVERIES


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def delete(self, key):
        self.values.pop(key, None)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    def lrange(self, key, start, end):
        return self.lists.get(key, [])[start : end + 1]

    def pipeline(self):
        return self

    def execute(self):
        return []


@pytest.fixture
def fake(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(celery_app, "broker", lambda: fake)
    return fake


@celery_app.app.task(name="dcl.test.echo", bind=True)
def echo(self, value):
    return value


def call_delivered(task, task_id, *args):
    task.push_request(id=task_id, is_eager=False, delivery_info={"routing_key": "io_light"}, retries=0)
    try:
        return task(*args)
    finally:
        task.pop_request()


def test_successful_delivery_clears_its_counter(fake):
    assert call_delivered(echo, "t-1", 5) == 5
    assert fake.values == {}


def test_task_lost_max_deliveries_times_is_stopped_as_poison(fake):
    key = celery_app.DELIVERY_KEY.format("t-2")
    fake.values[key] = MAX_DELIVERIES
    with pytest.raises(celery_app.PoisonTask, match=f"lost {MAX_DELIVERIES} times"):
        call_delivered(echo, "t-2", 1)


def test_final_failure_is_recorded_in_the_dead_letter_list(fake):
    echo.push_request(id="t-3", delivery_info={"routing_key": "cpu_parse"}, retries=3)
    try:
        echo.on_failure(ValueError("boom"), "t-3", ("run", 7), {"k": "v"}, None)
    finally:
        echo.pop_request()
    [entry] = celery_app.dead_letters()
    assert entry["task"] == "dcl.test.echo" and entry["queue"] == "cpu_parse"
    assert entry["error"] == "ValueError: 'boom'" and entry["retries"] == 3
    assert json.loads(fake.lists[DEAD_LETTER_KEY][0])["task_id"] == "t-3"


def test_dead_letter_list_is_capped(fake, monkeypatch):
    monkeypatch.setattr(celery_app, "DEAD_LETTER_MAX", 3)
    for i in range(5):
        celery_app.record_dead_letter(f"t{i}", "x", "io_light", (), {}, RuntimeError("e"), 0)
    assert [e["task_id"] for e in celery_app.dead_letters()] == ["t4", "t3", "t2"]


def test_plan_spreads_tasks_and_failure_kinds():
    plan = load_test.make_plan(tasks=600, transient=0.05, permanent=0.01, oom_tasks=2, seed=1)
    queues = [q for q, _ in plan.noops.values()]
    assert {queues.count(q) for q in load_test.NOOP_QUEUES} == {100}
    assert plan.permanent and plan.transient and plan.oom == [600, 601]


def test_verify_passes_only_when_every_task_is_accounted_for_and_routed():
    plan = load_test.make_plan(tasks=12, transient=0.0, permanent=0.0, oom_tasks=1, seed=1)
    plan.noops[0] = (plan.noops[0][0], 1)
    plan.noops[1] = (plan.noops[1][0], 9)
    done = {
        i: {"expected": q, "routed": q, "worker": q, "retries": f}
        for i, (q, f) in plan.noops.items()
        if i != 1
    }
    dead = {1: {"error": "InjectedFailure: x"}, 12: {"error": "PoisonTask: lost 3 times"}}
    assert load_test.verify(plan, done, dead)["passed"] is True
    missing = {i: r for i, r in done.items() if i != 5}
    report = load_test.verify(plan, missing, dead)
    assert report["passed"] is False and report["lost"] == [5]
    misrouted = {**done, 2: {**done[2], "worker": "embed"}}
    assert load_test.verify(plan, misrouted, dead)["misrouted"] == [2]
