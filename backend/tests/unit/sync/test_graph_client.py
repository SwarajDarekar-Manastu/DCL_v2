"""Read-only Graph client and the root / outside-share access check."""

import httpx
import pytest

from backend.sync.auth import check_access
from backend.sync.graph_client import GraphClient

ROOTS = {"root-1": "APU Injector", "root-2": "APU"}


def _client(handler) -> GraphClient:
    return GraphClient(lambda: "token-1", transport=httpx.MockTransport(handler))


def _graph(outside_status: int, seen: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        item_id = request.url.path.rsplit("/", 1)[-1]
        if item_id in ROOTS:
            return httpx.Response(200, json={"id": item_id, "name": ROOTS[item_id], "folder": {}})
        return httpx.Response(outside_status, json={"error": {"code": "itemNotFound"}})

    return handler


def _check(client, outside_item="outside-1", outside_drive=None):
    return check_access(client, "drive-a", list(ROOTS), list(ROOTS.values()), outside_item, outside_drive)


@pytest.mark.parametrize("status", [403, 404])
def test_roots_readable_and_outside_item_denied_passes(status):
    report = _check(_client(_graph(status)))
    assert [(r.expected_name, r.status, r.name) for r in report.roots] == [
        ("APU Injector", 200, "APU Injector"),
        ("APU", 200, "APU"),
    ]
    assert report.outside.passed
    assert report.ok


@pytest.mark.parametrize("status", [200, 401, 500])
def test_outside_item_readable_or_erroring_fails(status):
    report = _check(_client(_graph(status)))
    assert not report.outside.passed
    assert not report.ok


def test_missing_outside_item_id_fails_the_check():
    report = _check(_client(_graph(404)), outside_item=None)
    assert report.outside is None
    assert not report.ok


def test_outside_check_targets_the_outside_drive_and_falls_back_to_the_roots_drive():
    seen: list[httpx.Request] = []
    report = _check(_client(_graph(404, seen)), outside_drive="drive-b")
    assert seen[-1].url.path == "/v1.0/drives/drive-b/items/outside-1"
    assert report.outside.drive_id == "drive-b"

    seen.clear()
    report = _check(_client(_graph(404, seen)))
    assert seen[-1].url.path == "/v1.0/drives/drive-a/items/outside-1"
    assert report.outside.drive_id == "drive-a"


def test_unreachable_root_fails_the_check():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if request.url.path.endswith("root-2") else 200, json={"name": "x"})

    report = _check(_client(handler))
    assert [r.ok for r in report.roots] == [True, False]
    assert not report.ok


def test_every_request_carries_the_bearer_token_and_is_a_get():
    seen: list[httpx.Request] = []
    _check(_client(_graph(404, seen)))
    assert {(r.method, r.headers["Authorization"]) for r in seen} == {("GET", "Bearer token-1")}


def test_client_has_no_write_methods():
    for name in ("post", "put", "patch", "delete", "request", "send"):
        assert not hasattr(GraphClient, name)


def test_absolute_graph_links_are_allowed_and_other_hosts_refused():
    seen: list[httpx.Request] = []
    client = _client(_graph(404, seen))
    client.get("https://graph.microsoft.com/v1.0/drives/drive-a/items/root-1/delta?token=abc")
    assert seen[0].url.host == "graph.microsoft.com"
    with pytest.raises(ValueError, match="other than graph.microsoft.com"):
        client.get("https://evil.example.com/steal")
    with pytest.raises(ValueError, match="start with '/'"):
        client.get("drives/x")
