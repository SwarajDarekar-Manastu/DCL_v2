"""Prompt registry (file 08 §3.3): list with versions and pins, show, diff, run on sample (reviewers)."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import auth, engine
from backend.llm_engine.gemini_types import GenerateResult, Usage
from backend.llm_engine.prompts import registry

REVIEWERS = "group-reviewers"


@pytest.fixture
def client(auth_config, key_resolver):
    app = FastAPI()
    app.include_router(engine.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    return TestClient(app)


def test_the_registry_lists_versions_and_marks_what_the_code_pins():
    by_version = {(p.area, p.version): p for p in registry.list_prompts()}
    old, new = by_version[("vision", "transcribe_page.v2")], by_version[("vision", "transcribe_page.v3")]
    assert (old.latest, old.in_use) == (False, False) and (new.latest, new.in_use) == (True, True)
    assert by_version[("engine", "telemetry_args.v1")].in_use  # named by stem in the workflow
    assert by_version[("engine", "synthesis.v1")].variables == ["analysis", "evidence", "question"]


def test_routes_list_show_and_diff(client, token):
    assert client.get("/v1/prompts").status_code == 401
    viewer = {"Authorization": f"Bearer {token()}"}
    listed = client.get("/v1/prompts", headers=viewer).json()
    assert any(p["version"] == "chitchat.v2" and p["in_use"] for p in listed)
    shown = client.get("/v1/prompts/engine/chitchat.v2", headers=viewer).json()
    assert "out_of_scope" in shown["system"] and "$question" in shown["user_template"]
    diff = client.get("/v1/prompts/engine/diff/chitchat.v1/chitchat.v2", headers=viewer).json()
    assert diff["unified"].startswith("--- engine/chitchat.v1") and "+- out_of_scope" in diff["unified"]
    assert client.get("/v1/prompts/engine/nope.v1", headers=viewer).status_code == 404
    assert client.get("/v1/prompts/engine/diff/chitchat.v1/../x", headers=viewer).status_code == 404
    assert client.get("/v1/prompts/../diff/chitchat.v1/chitchat.v2", headers=viewer).status_code == 404
    with pytest.raises(registry.PromptNotFound):
        registry.diff_prompts("..", "prompts.v1", "chitchat.v2")


class Client:
    def __init__(self):
        self.calls = []

    async def generate(self, *, model, messages, context, **options):
        self.calls.append((model, messages, context))
        return GenerateResult("Hallo!", None, (), Usage(12, 3), model, "stop", "r", 5)


def test_run_on_sample_fills_the_template_and_logs_the_preview(monkeypatch):
    fake = Client()
    result = asyncio.run(
        registry.run_prompt(
            fake,
            "engine",
            "chitchat.v2",
            registry.PromptRun(variables={"question": "Wie geht's?"}),
            user="a@b",
        )
    )
    [(model, messages, context)] = fake.calls
    user_text = messages[1].parts[0].text
    assert "Wie geht's?" in user_text and "$language" in user_text  # a missing variable stays visible
    assert context.purpose == "console.prompt_preview" and context.prompt_version == "chitchat.v2"
    assert (result.text, result.input_tokens, result.output_tokens) == ("Hallo!", 12, 3)


def test_running_a_prompt_needs_a_reviewer(client, token, monkeypatch):
    viewer = {"Authorization": f"Bearer {token()}"}
    assert client.post("/v1/prompts/engine/chitchat.v2/run", json={}, headers=viewer).status_code == 403
    fake = Client()
    monkeypatch.setitem(engine._ENGINE, "gemini", fake)
    reviewer = {"Authorization": f"Bearer {token(groups=[REVIEWERS])}"}
    response = client.post(
        "/v1/prompts/engine/chitchat.v2/run", json={"variables": {"question": "hi"}}, headers=reviewer
    )
    assert response.status_code == 200 and response.json()["text"] == "Hallo!"
