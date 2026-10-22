"""Case tasks on io_light threads share the engine's async clients, so they must share one event loop."""

import asyncio
import threading


class LoopBoundClient:
    """Like the gateway client: an asyncio primitive created on first use, bound to that loop."""

    def __init__(self):
        self.lock = None

    async def call(self):
        if self.lock is None:
            self.lock = asyncio.Lock()
        async with self.lock:
            await asyncio.sleep(0)
        return asyncio.get_running_loop()


def test_coroutines_from_different_threads_run_on_one_loop_and_reuse_the_client():
    from backend.benchmark.tasks import run_async

    client, loops, errors = LoopBoundClient(), [], []

    def task():
        try:
            loops.append(run_async(client.call()))
        except Exception as exc:  # noqa: BLE001 — the old asyncio.run per task raised here
            errors.append(exc)

    threads = [threading.Thread(target=task) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    task()
    assert errors == [] and len(set(map(id, loops))) == 1
