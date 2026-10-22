"""The route adapter registry (file 03 §1.4, file 06 §3 ``UNSUPPORTED_FORMAT``).

A route is implemented file kind by file kind: Route C starts with LabJack ``.dat``, so a ``.xlsx``
typed C stays ``WAITING_FOR_ROUTE`` until its adapter lands. A document is sent to processing when its
route is enabled (``routes.<X>.enabled``) and an adapter of that route accepts its primary file. When the
registry gains an adapter, the next dispatch releases the parked documents it accepts.
"""

from collections.abc import Callable
from dataclasses import dataclass

from backend.celery_redis.queues import Queue
from backend.postgres.enums import Route
from backend.routes.c_telemetry import labjack


@dataclass(frozen=True)
class Adapter:
    name: str
    route: Route
    task: str
    queue: Queue
    can_handle: Callable[[bytes, str], bool]


ADAPTERS: tuple[Adapter, ...] = (
    Adapter("labjack_dat", Route.C, "dcl.process.route_c", Queue.TELEMETRY_STREAM, labjack.can_handle),
)


def adapter_for(route: Route | None, head: bytes, name: str) -> Adapter | None:
    """The first adapter of ``route`` that accepts the file (its first bytes and name)."""
    if route is None:
        return None
    return next((a for a in ADAPTERS if a.route == route and a.can_handle(head, name)), None)


def implemented_routes() -> frozenset[Route]:
    return frozenset(a.route for a in ADAPTERS)
