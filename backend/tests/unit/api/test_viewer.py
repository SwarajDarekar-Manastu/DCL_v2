import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import auth, viewer
from backend.api.assets import get_minio
from backend.api.viewer import ViewerPayload, viewer_path
from backend.dispatcher.contract import AnchorError, format_anchor, parse_anchor
from backend.postgres.session import get_session

HASH = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
DOC = uuid.UUID("0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90")


@pytest.mark.parametrize(
    ("param", "fields"),
    [
        (f"page:12:{HASH}", {"page_no": 12, "content_sha256": HASH}),
        ("page:3:", {"page_no": 3}),
        ("page:3", {"page_no": 3}),
        ("line:120:ab12cd34ef56ab78", {"line_start": 120, "content_sha256": "ab12cd34ef56ab78"}),
        ("t:0:", {"t_start_ms": 0}),
        ("t:83500:", {"t_start_ms": 83500}),
        (
            "cells:Run 1!A1:D20:0c1d2e3f4a5b6c7d",
            {"sheet_name": "Run 1", "cell_range": "A1:D20", "content_sha256": "0c1d2e3f4a5b6c7d"},
        ),
        ("cells:Hot fire: 30 bar!B7:", {"sheet_name": "Hot fire: 30 bar", "cell_range": "B7"}),
        ("cells:Q&A!x!C3:", {"sheet_name": "Q&A!x", "cell_range": "C3"}),
    ],
)
def test_parse_and_round_trip(param, fields):
    assert parse_anchor(param) == fields
    assert parse_anchor(format_anchor(fields)) == fields


@pytest.mark.parametrize(
    "param",
    [
        "12",
        "page::",
        "page:0:",
        "page:-1:",
        "page:12:NOTHEX",
        "page:12:abc",
        "line:x:",
        "t:1.5:",
        "cells:A1:D20:",
        "cells:Sheet!:",
        "cells:Sheet!a1:",
        "node:5f0c:",
    ],
)
def test_malformed_anchors_are_refused(param):
    with pytest.raises(AnchorError):
        parse_anchor(param)


def test_format_refuses_an_anchor_without_locator():
    with pytest.raises(AnchorError):
        format_anchor({"content_sha256": HASH})


def test_viewer_path_is_a_readable_link_the_viewer_parses_back():
    path = viewer_path(DOC, {"sheet_name": "Run 1", "cell_range": "A1:D20", "content_sha256": HASH[:16]})
    assert path == f"/docs/{DOC}/viewer?anchor=cells:Run%201!A1:D20:{HASH[:16]}"
    anchor = parse_qs(urlsplit(path).query)["anchor"][0]
    assert parse_anchor(anchor)["sheet_name"] == "Run 1"


def test_payload_serializes_each_view_kind():
    base = {
        "anchor": f"page:12:{HASH}",
        "document": {
            "doc_id": str(DOC),
            "title": "TP30 hot-fire report",
            "doc_kind": "test_report",
            "source_origin": "internal",
            "trust_tier": 2,
            "status": "ACTIVE",
        },
        "resolution": {"status": "page_fallback", "message": "content changed"},
        "links": {},
        "translation": {},
    }
    views = [
        {
            "kind": "page",
            "page_no": 12,
            "page_count": 40,
            "image_url": "u",
            "width": 1240,
            "height": 1754,
            "regions": [{"bbox": [0.1, 0.2, 0.5, 0.3], "kind": "cited"}],
        },
        {"kind": "image", "image_kind": "photo", "image_url": "u", "width": 800, "height": 600},
        {"kind": "table", "rows": [["a", "b"], ["1", "2"]], "highlight": [1, 0, 1, 1]},
        {"kind": "code", "language": "python", "first_line": 10, "lines": ["x = 1"], "highlight": [10, 10]},
        {"kind": "text", "text": "plain"},
        {"kind": "video", "video_url": "u", "t_ms": 83500},
    ]
    for view in views:
        payload = ViewerPayload.model_validate({**base, "view": view})
        assert payload.view.kind == view["kind"]
        assert "node_id" not in payload.model_dump_json()


class NoDocuments:
    """Stands in for a Session over an empty database (the real path is in tests/integration/api)."""

    def get(self, model, key):
        return None


@pytest.fixture
def client(auth_config, key_resolver):
    app = FastAPI()
    app.include_router(viewer.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    app.dependency_overrides[get_session] = lambda: NoDocuments()
    app.dependency_overrides[get_minio] = lambda: None
    return TestClient(app)


def test_route_requires_sign_in(client):
    assert client.get(f"/docs/{DOC}/viewer?anchor=page:1:").status_code == 401


def test_route_refuses_a_bad_anchor(client, token):
    response = client.get(
        f"/docs/{DOC}/viewer", params={"anchor": "node:abc:"}, headers={"Authorization": f"Bearer {token()}"}
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith("unknown anchor kind")


def test_route_answers_404_for_an_unknown_document(client, token):
    response = client.get(
        f"/docs/{DOC}/viewer", params={"anchor": "page:1:"}, headers={"Authorization": f"Bearer {token()}"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == f"no document {DOC}"
