"""Answer routes (docs/sessions/PLAN_query_routing.md, user 2026-10-28): the kinds of data a question can be
about, each answered by its own method. A file's answer route follows from its ingestion route, its kind
and its folder; the engine plans by it and the benchmark labels and scores by it.
"""

from enum import StrEnum

from backend.postgres.enums import DocKind, Route


class AnswerRoute(StrEnum):
    MEASURED = "measured"  # telemetry runs: T2 over the run's data
    TABLE = "table"  # spreadsheets and engineering tables
    SOURCE = "source"  # code, tooling docs, configuration files
    DOCUMENT = "document"  # reports, test plans, LaTeX and JSON sources
    VISUAL = "visual"  # photos, plots, test-cell videos
    MEETING = "meeting"  # recordings of meetings, workshops and trainings: their transcripts
    DIAGRAM = "diagram"  # diagram graphs
    LIBRARY = "library"  # standards, papers and books in the Library folder
    ARCHIVE = "archive"  # archives, ANSYS packages, CAD: answered from the card


LIBRARY_FOLDER = "library"
SOURCE_KINDS = (DocKind.CODE, DocKind.TOOLING_DOC, DocKind.CONFIG)  # the files of the source route


def of_document(
    route: str | None, doc_kind: str | None, folder_kind: str | None = None
) -> AnswerRoute | None:
    """The answer route of one file; None for a file no route produced (failed or not yet processed)."""
    if doc_kind == DocKind.CONFIG:
        return AnswerRoute.SOURCE
    match route:
        case Route.A1:
            return AnswerRoute.LIBRARY if folder_kind == LIBRARY_FOLDER else AnswerRoute.DOCUMENT
        case Route.A2:
            return AnswerRoute.DOCUMENT
        case Route.B:
            return AnswerRoute.SOURCE
        case Route.C:
            return AnswerRoute.MEASURED if doc_kind == DocKind.TELEMETRY_RUN else AnswerRoute.TABLE
        case Route.F:
            return AnswerRoute.MEETING if doc_kind == DocKind.VIDEO_TRANSCRIPT else AnswerRoute.VISUAL
        case Route.D:
            return AnswerRoute.VISUAL
        case Route.E:
            return AnswerRoute.DIAGRAM
        case Route.G:
            return AnswerRoute.ARCHIVE
    return None
