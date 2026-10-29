"""Every kind of file the index holds today has one answer route (PLAN_query_routing.md)."""

import pytest

from backend.llm_engine.engine.answer_routes import AnswerRoute, of_document


@pytest.mark.parametrize(
    ("route", "kind", "folder", "expected"),
    [
        ("A1", "test_plan", None, AnswerRoute.DOCUMENT),
        ("A1", "standard", "library", AnswerRoute.LIBRARY),
        ("A1", "unknown", "library", AnswerRoute.LIBRARY),
        ("A2", "unknown", None, AnswerRoute.DOCUMENT),
        ("B", "code", None, AnswerRoute.SOURCE),
        ("B", "tooling_doc", None, AnswerRoute.SOURCE),
        ("C", "config", "pressure_data_files", AnswerRoute.SOURCE),
        ("C", "telemetry_run", "pressure_data_files", AnswerRoute.MEASURED),
        ("C", "engineering_table", None, AnswerRoute.TABLE),
        ("C", "test_plan", None, AnswerRoute.TABLE),
        ("D", "hardware_photo", None, AnswerRoute.VISUAL),
        ("D", "plot_figure", "pressure_data_files", AnswerRoute.VISUAL),
        ("F", "video_timeline", None, AnswerRoute.VISUAL),
        ("F", "video_transcript", None, AnswerRoute.MEETING),
        ("E", "diagram", None, AnswerRoute.DIAGRAM),
        ("G", "cad_reference", None, AnswerRoute.ARCHIVE),
        ("G", "cae_package", None, AnswerRoute.ARCHIVE),
        (None, "unknown", None, None),
    ],
)
def test_a_file_maps_to_its_answer_route(route, kind, folder, expected):
    assert of_document(route, kind, folder) == expected
