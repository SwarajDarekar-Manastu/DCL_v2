"""The minute tick sends a sweep only when nothing waits on the benchmark queue, so a stopped worker does not
come back to one sweep per minute it was away."""

from backend.benchmark import tasks


class Queues:
    def __init__(self, waiting):
        self.waiting = waiting

    def llen(self, name):
        return self.waiting[name]


def test_a_sweep_is_sent_only_while_the_benchmark_queue_is_empty(monkeypatch):
    sent, queues = [], Queues({"benchmark": 0})
    monkeypatch.setattr(tasks, "broker", lambda: queues)
    monkeypatch.setattr(tasks.sweep, "delay", lambda: sent.append("sweep"))
    assert tasks.tick() is True
    queues.waiting["benchmark"] = 1  # the worker is stopped: the sweep stays queued
    assert [tasks.tick() for _ in range(3)] == [False, False, False]
    assert sent == ["sweep"]
