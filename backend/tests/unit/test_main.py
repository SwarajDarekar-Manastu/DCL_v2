import pytest
from fastapi.testclient import TestClient

from backend import config, main
from backend.api import health, models, sync


@pytest.fixture(autouse=True)
def fresh_settings():
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.mark.parametrize("role", ["api", "models", "all"])
def test_every_role_answers_healthz_with_its_role(monkeypatch, role):
    monkeypatch.setenv("ROLE", role)
    with TestClient(main.create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "role": role}


def test_models_router_is_mounted_only_for_models_and_all():
    assert models not in main.ROUTERS_BY_ROLE[config.Role.API]
    assert models in main.ROUTERS_BY_ROLE[config.Role.MODELS]
    assert models in main.ROUTERS_BY_ROLE[config.Role.ALL]
    assert sync not in main.ROUTERS_BY_ROLE[config.Role.MODELS]
    assert health in main.ROUTERS_BY_ROLE[config.Role.MODELS]


@pytest.mark.parametrize("value", [None, "", "worker", "API "])
def test_missing_or_invalid_role_refuses_and_names_role(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ROLE", raising=False)
    else:
        monkeypatch.setenv("ROLE", value)
    with pytest.raises(config.ConfigError, match="ROLE"):
        main.create_app()
