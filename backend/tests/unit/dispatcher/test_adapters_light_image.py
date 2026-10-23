"""The dispatcher runs on io_light, whose image has no parse dependencies: S6's adapter checks must not
make a dispatch fail there (live 2026-10-23: ModuleNotFoundError lxml). Without the route module the
file's suffix decides; the route task validates the content on cpu_parse."""

import importlib

import pytest

from backend.dispatcher import adapters
from backend.postgres.enums import Route


@pytest.fixture
def light_image(monkeypatch):
    real = importlib.import_module

    def without_routes(name, *args, **kwargs):
        if name.startswith("backend.routes."):
            raise ModuleNotFoundError("No module named 'lxml'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", without_routes)


@pytest.mark.parametrize(
    ("route", "head", "name", "adapter"),
    [
        (Route.A2, b"\\documentclass{article}", "report.tex", "latex"),
        (Route.A2, b'{"objectives": []}', "T01.json", "report_json"),
        (Route.B, b"import numpy\n", "calc.py", "code"),
        (Route.E, b"<mxfile>", "feed.drawio", "diagram"),
        (Route.G, b"PK\x03\x04\x00\x00", "bundle.zip", "archive_cad"),
        (Route.G, b"AC1032\x00\x00", "assy.dwg", "archive_cad"),
    ],
)
def test_adapters_answer_without_the_route_modules(light_image, route, head, name, adapter):
    assert adapters.adapter_for(route, head, name).name == adapter


def test_a_binary_file_named_like_source_is_not_taken_by_b(light_image):
    assert adapters.adapter_for(Route.B, b"\x00\x01binary", "calc.py") is None
