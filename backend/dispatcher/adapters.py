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


OFFICE_EXTENSIONS = (".pdf", ".docx", ".doc", ".rtf", ".odt", ".pptx", ".ppt", ".odp")


def is_office(head: bytes, name: str) -> bool:
    """Route A1 (S2's ``process_office``): PDFs by magic bytes, Word family and slides by name."""
    return b"%PDF-" in head[:1024] or name.casefold().endswith(OFFICE_EXTENSIONS[1:])


def a2_tex(head: bytes, name: str) -> bool:
    """S6's check, imported when called so the dispatcher never loads Route A2's parsers."""
    from backend.routes.a2_source import route as a2

    return a2.can_handle_tex(head, name)


def a2_json(head: bytes, name: str) -> bool:
    from backend.routes.a2_source import route as a2

    return a2.can_handle_json(head, name)


def code(head: bytes, name: str) -> bool:
    from backend.routes.b_code import route as b

    return b.can_handle(head, name)


def diagram(head: bytes, name: str) -> bool:
    from backend.routes.e_diagrams import route as e

    return e.can_handle(head, name)


def archive_cad(head: bytes, name: str) -> bool:
    from backend.routes.g_archives import route as g

    return g.can_handle(head, name)


def any_file(head: bytes, name: str) -> bool:
    """Routes D and F take every file type resolution sent them (images, videos)."""
    return True


_C = ("dcl.process.route_c", Queue.TELEMETRY_STREAM)
_A2 = ("dcl.process.route_a2", Queue.CPU_PARSE)
ADAPTERS: tuple[Adapter, ...] = (
    Adapter("office", Route.A1, "dcl.process.route_a1", Queue.CPU_PARSE, is_office),
    Adapter("latex", Route.A2, *_A2, a2_tex),
    Adapter("report_json", Route.A2, *_A2, a2_json),
    Adapter("code", Route.B, "dcl.process.route_b", Queue.CPU_PARSE, code),
    Adapter("diagram", Route.E, "dcl.process.route_e", Queue.CPU_PARSE, diagram),
    Adapter("archive_cad", Route.G, "dcl.process.route_g", Queue.CPU_PARSE, archive_cad),
    Adapter("photo", Route.D, "dcl.process.route_d", Queue.MEDIA, any_file),
    Adapter("video", Route.F, "dcl.process.route_f", Queue.MEDIA, any_file),
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


def task_for_route(route: Route) -> tuple[str, Queue] | None:
    """The task and queue that process documents of ``route`` (all adapters of a route share them)."""
    adapter = next((a for a in ADAPTERS if a.route == route), None)
    return (adapter.task, adapter.queue) if adapter else None
