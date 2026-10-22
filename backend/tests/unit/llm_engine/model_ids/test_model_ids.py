"""Model ids come from the settings when a call is made, so switching a model is an environment change."""

import pytest

from backend import config
from backend.llm_engine.model_ids import Tier, model_id
from backend.llm_engine.vision.service import TASKS, VisionCapability


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", None)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_LITE_MODEL", raising=False)
    config.get_settings.cache_clear()
    yield monkeypatch
    config.get_settings.cache_clear()


def test_defaults_are_the_decided_models(settings_env):
    assert model_id() == "gemini-3.8-flash"
    assert model_id(Tier.LITE) == "gemini-3.1-flash-lite"


def test_the_environment_switches_both_tiers_and_the_vision_tasks_follow(settings_env):
    settings_env.setenv("GEMINI_MODEL", "gemini-9-flash")
    settings_env.setenv("GEMINI_LITE_MODEL", "gemini-9-flash-lite")
    config.get_settings.cache_clear()
    assert model_id() == "gemini-9-flash"
    assert TASKS[VisionCapability.TRIAGE_PAGE].model == "gemini-9-flash-lite"
    assert TASKS[VisionCapability.TRANSCRIBE_PAGE].model == "gemini-9-flash"
