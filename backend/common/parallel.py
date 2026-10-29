"""Model calls side by side, and the turns a long processing task works in (user decision 2026-10-27).

A route task waits on the network for most of its run: hundreds of model calls of seconds each. Made one
after another they kept a 420-page manual past the worker's 60-minute limit (2026-10-27). `map_parallel`
makes up to `AT_ONCE` calls at a time, the model client's own limit per model. A task also works in turns
(file 03 time budget): past its `deadline` nothing new starts, the calls already running finish (their
replies are cached), and `TurnOver` sends the document to the back of its queue, to go on from what was
saved. So no file is too large for the worker's time limit, and a large one does not hold the worker from
the others.
"""

import time
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

AT_ONCE = 8


class TurnOver(Exception):
    """The task's turn ended: what it finished is saved and the document is sent to its queue again."""


def past(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def check(deadline: float | None) -> None:
    if past(deadline):
        raise TurnOver("the turn ended")


def map_parallel[T, R](
    fn: Callable[[T], R], items: Iterable[T], *, deadline: float | None = None, at_once: int = AT_ONCE
) -> list[R]:
    """``fn`` over ``items``, ``at_once`` at a time, results in the order of ``items``. An error in one call
    is raised once the calls running beside it have finished; past ``deadline`` it is ``TurnOver``."""
    todo = deque(enumerate(items))
    results: list = [None] * len(todo)
    stopped = False
    with ThreadPoolExecutor(max_workers=at_once) as pool:
        running: dict[Future, int] = {}
        while todo or running:
            while todo and len(running) < at_once and not stopped:
                if past(deadline):
                    stopped = True
                    break
                index, item = todo.popleft()
                running[pool.submit(fn, item)] = index
            if not running:
                break
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                results[running.pop(future)] = future.result()
    if stopped:
        raise TurnOver("the turn ended")
    return results
