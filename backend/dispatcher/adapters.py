"""The route adapter registry (file 03 §1.4, file 06 §3 ``UNSUPPORTED_FORMAT``).

A route is implemented file kind by file kind (Route C: LabJack ``.dat``, ``.tdms``, ``.csv``, workbooks,
configuration files); a file no adapter of its route accepts stays ``WAITING_FOR_ROUTE``. A document is
sent to processing when its route is enabled (``routes.<X>.enabled``) and an adapter of that route accepts
its primary file. When the registry gains an adapter, the next dispatch releases the parked documents it
accepts.
"""

from collections.abc import Callable
from dataclasses import dataclass

from backend.celery_redis.queues import Queue
from backend.postgres.enums import Route
from backend.routes.c_telemetry import config_file, delimited, labjack, tdms, workbook


@dataclass(frozen=True)
class Adapter:
    name: str
    route: Route
    task: str
    queue: Queue
    can_handle: Callable[[bytes, str], bool]


def is_pdf(head: bytes, name: str) -> bool:
    """Route A1 reads PDFs (S2's ``process_pdf``); DOCX/PPTX/PPT wait for A1.9–A1.10."""
    return b"%PDF-" in head[:1024]


_C = ("dcl.process.route_c", Queue.TELEMETRY_STREAM)
ADAPTERS: tuple[Adapter, ...] = (
    Adapter("pdf", Route.A1, "dcl.process.route_a1", Queue.CPU_PARSE, is_pdf),
    Adapter("labjack_dat", Route.C, *_C, labjack.can_handle),
    Adapter("tdms", Route.C, *_C, tdms.can_handle),
    Adapter("delimited", Route.C, *_C, delimited.can_handle),
    Adapter("workbook", Route.C, *_C, workbook.can_handle),
    Adapter("config_file", Route.C, *_C, config_file.can_handle),
)


def adapter_for(route: Route | None, head: bytes, name: str) -> Adapter | None:
    """The first adapter of ``route`` that accepts the file (its first bytes and name)."""
    if route is None:
        return None
    return next((a for a in ADAPTERS if a.route == route and a.can_handle(head, name)), None)


def implemented_routes() -> frozenset[Route]:
    return frozenset(a.route for a in ADAPTERS)
