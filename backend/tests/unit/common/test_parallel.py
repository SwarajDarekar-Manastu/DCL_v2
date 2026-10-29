"""Model calls side by side within a turn (common/parallel.py)."""

import threading
import time

import pytest

from backend.common.parallel import TurnOver, map_parallel


def test_calls_run_side_by_side_and_results_keep_the_order():
    lock, running, most = threading.Lock(), [0], [0]

    def call(n):
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        time.sleep(0.02 * (5 - n % 5))  # later items finish first
        with lock:
            running[0] -= 1
        return n * 10

    assert map_parallel(call, range(20), at_once=4) == [n * 10 for n in range(20)]
    assert most[0] == 4


def test_past_the_deadline_nothing_new_starts_and_the_running_calls_finish():
    started, finished = [], []

    def call(n):
        started.append(n)
        time.sleep(0.05)
        finished.append(n)

    with pytest.raises(TurnOver):
        map_parallel(call, range(10), deadline=time.monotonic() + 0.02, at_once=2)
    assert sorted(started) == [0, 1] and sorted(finished) == [0, 1]


def test_an_error_is_raised_after_the_calls_beside_it_finish():
    finished = []

    def call(n):
        if n == 0:
            raise ValueError("bad reply")
        time.sleep(0.05)
        finished.append(n)

    with pytest.raises(ValueError, match="bad reply"):
        map_parallel(call, range(3), at_once=3)
    assert sorted(finished) == [1, 2]
