"""install_functions.py against a fake Open WebUI that mimics the v0.12.3 admin routes it uses."""

import json

import httpx
import pytest

from frontend.openwebui.install_functions import ACTIONS_ID, MODEL_ID, PIPE_ID, Target, install

TARGET = Target(
    owui_url="http://owui.test",
    engine_url="http://api:8200",
    console_url="https://console.test",
    shared_secret="never-print-me",
)


class FakeOpenWebUI:
    """Functions, valves and workspace models, with the same flip semantics as the real toggle route."""

    def __init__(self):
        self.functions: dict[str, dict] = {}
        self.valves: dict[str, dict] = {}
        self.models: dict[str, dict] = {}
        self.writes: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        if method == "POST":
            self.writes.append(path)
        if path.startswith("/api/v1/functions/id/"):
            fid, _, action = path.removeprefix("/api/v1/functions/id/").partition("/")
            function = self.functions.get(fid)
            if method == "GET" and not action:
                return httpx.Response(200 if function else 404, json=function or {"detail": "not found"})
            if function is None:
                return httpx.Response(404, json={"detail": "not found"})
            if action == "update":
                function.update(content=body["content"], name=body["name"])
                return httpx.Response(200, json=function)
            if action == "toggle":
                function["is_active"] = not function["is_active"]
                return httpx.Response(200, json=function)
            if action == "valves/update":
                self.valves[fid] = body
                return httpx.Response(200, json=body)
        if path == "/api/v1/functions/create":
            self.functions[body["id"]] = {
                "id": body["id"],
                "name": body["name"],
                "content": body["content"],
                "is_active": False,
                "is_global": False,
            }
            return httpx.Response(200, json=self.functions[body["id"]])
        if path == "/api/v1/models/model" and method == "GET":
            model = self.models.get(request.url.params["id"])
            return httpx.Response(200 if model else 404, json=model)
        if path in ("/api/v1/models/create", "/api/v1/models/model/update"):
            self.models[body["id"]] = body
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"detail": f"unexpected {method} {path}"})


def run(fake, dry_run=False):
    lines = []
    with httpx.Client(base_url=TARGET.owui_url, transport=httpx.MockTransport(fake)) as http:
        install(http, TARGET, dry_run=dry_run, log=lines.append)
    return lines


def test_first_run_creates_activates_and_configures():
    fake = FakeOpenWebUI()
    lines = run(fake)
    assert {f: fn["is_active"] for f, fn in fake.functions.items()} == {PIPE_ID: True, ACTIONS_ID: True}
    assert fake.functions[PIPE_ID]["content"].startswith('"""\ntitle: Manastu Propulsion Engine')
    assert fake.valves[PIPE_ID] == {
        "ENGINE_URL": "http://api:8200",
        "ENGINE_SHARED_SECRET": "never-print-me",
        "CONSOLE_URL": "https://console.test",
    }
    assert fake.valves[ACTIONS_ID] == {
        "ENGINE_URL": "http://api:8200",
        "ENGINE_SHARED_SECRET": "never-print-me",
    }
    model = fake.models[MODEL_ID]
    assert model["meta"]["actionIds"] == [ACTIONS_ID] and model["base_model_id"] is None
    assert not any(fn["is_global"] for fn in fake.functions.values())  # actions only on the engine model
    assert all("never-print-me" not in line for line in lines)


def test_second_run_converges_without_toggling_off():
    fake = FakeOpenWebUI()
    run(fake)
    fake.models[MODEL_ID]["meta"]["actionIds"] = ["other_action", ACTIONS_ID]
    fake.writes.clear()
    lines = run(fake)
    assert {f: fn["is_active"] for f, fn in fake.functions.items()} == {PIPE_ID: True, ACTIONS_ID: True}
    assert not any(w.endswith("/toggle") for w in fake.writes)
    assert "/api/v1/functions/create" not in fake.writes
    assert fake.models[MODEL_ID]["meta"]["actionIds"] == ["other_action", ACTIONS_ID]
    assert lines[0] == f"update function {PIPE_ID}"


def test_dry_run_writes_nothing():
    fake = FakeOpenWebUI()
    lines = run(fake, dry_run=True)
    assert fake.writes == [] and fake.functions == {}
    assert lines[0] == f"create function {PIPE_ID}"


def test_refusals_stop_with_the_reason():
    def refuse(request):
        if request.method == "GET":
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(401, json={"detail": "Your session has expired or the token is invalid."})

    with httpx.Client(base_url=TARGET.owui_url, transport=httpx.MockTransport(refuse)) as http:
        with pytest.raises(SystemExit) as stop:
            install(http, TARGET, log=lambda line: None)
    assert "create manastu_engine failed: HTTP 401" in str(stop.value)
