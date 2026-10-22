import re

import pytest

from backend import config
from backend.config import (
    ConfigError,
    Environment,
    Group,
    PermissionOption,
    Role,
    ThinkingLevel,
    load_settings,
)

SECRET = "s3cr3t-value-that-must-never-leak"

COMPLETE = {
    "DCL_TENANT_ID": "tenant-1",
    "DCL_CLIENT_ID": "client-1",
    "DCL_AUTH_MODE": "delegated",
    "DCL_DELEGATED_USERNAME": "ai@manastuspace.com",
    "DCL_PERMISSION_OPTION": "A",
    "DCL_TOKEN_CACHE_PATH": "/var/lib/dcl/token_cache.bin",
    "DCL_TOKEN_DIR": "/var/lib/dcl",
    "DCL_TOKEN_CACHE_KEY": "Wb2zbXq0mkC9w3dE0t2tHhpG6fZcUaFsr3o5rQyPqLM=",
    "DCL_DRIVE_ID": "drive-1",
    "DCL_FOLDER_IDS": "id1, id2,id3,id4",
    "DCL_FOLDER_PATHS": "APU Injector,APU,APS - Library,APU Heater",
    "DCL_TEST_OUTSIDE_ITEM_ID": "outside-1",
    "GEMINI_BACKEND": "gateway",
    "GEMINI_GATEWAY_URL": "https://gateway.internal.test/v1",
    "GEMINI_GATEWAY_KEY": SECRET,
    "GEMINI_THINKING_LEVEL": "low",
    "GEMINI_INCLUDE_THOUGHTS": "false",
    "GEMINI_CONTEXT_CACHE": "1",
    "GEMINI_CACHE_TTL_S": "3600",
    "DCL_ALERT_WEBHOOK_URL": f"https://hooks.test/{SECRET}",
    "DCL_DB_USER": "dcl",
    "DCL_DB_PASSWORD": SECRET,
    "DCL_DB_PORT": "5432",
    "DCL_DATABASE_URL": f"postgresql://dcl:{SECRET}@localhost:5432/dcl",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in list(config.CONTRACT_NAMES) + list(config.FORBIDDEN_NAMES):
        monkeypatch.delenv(name, raising=False)


def set_env(monkeypatch, values):
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def load_with(monkeypatch, **overrides):
    set_env(monkeypatch, {**COMPLETE, **overrides})
    return load_settings(env_file=None)


def test_complete_env_loads_typed_values(monkeypatch):
    settings = load_with(monkeypatch)
    assert settings.permission_option is PermissionOption.A
    assert settings.folder_ids == ["id1", "id2", "id3", "id4"]
    assert settings.folder_paths == ["APU Injector", "APU", "APS - Library", "APU Heater"]
    assert settings.gemini_thinking_level is ThinkingLevel.LOW
    assert settings.gemini_include_thoughts is False
    assert settings.gemini_context_cache is True
    assert settings.gemini_cache_ttl_s == 3600
    assert settings.db_port == 5432
    assert settings.gemini_gateway_key.get_secret_value() == SECRET
    assert settings.require(Group.GRAPH, Group.GEMINI, Group.ALERTS) is settings


def test_permission_option_b_is_accepted(monkeypatch):
    assert load_with(monkeypatch, DCL_PERMISSION_OPTION="B").permission_option is PermissionOption.B


def test_empty_environment_loads_and_role_is_optional(monkeypatch):
    settings = load_settings(env_file=None)
    assert settings.role is None
    assert settings.bind_host == "127.0.0.1"


@pytest.mark.parametrize("value", ["", "anything", SECRET])
def test_google_api_key_in_environment_is_refused_even_empty(monkeypatch, value):
    monkeypatch.setenv("GOOGLE_API_KEY", value)
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY") as exc:
        load_with(monkeypatch)
    assert SECRET not in str(exc.value)


def test_google_api_key_in_env_file_is_refused(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DCL_TENANT_ID=t\nGOOGLE_API_KEY={SECRET}\n")
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY") as exc:
        load_settings(env_file=env_file)
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize(
    "placeholder",
    [
        "<tenant-id>",
        "changeme",
        "CHANGE_ME",
        "replace-me",
        "TODO",
        "tbd",
        "xxxx",
        "your-key-here",
        "${GEMINI_GATEWAY_KEY}",
        "...",
        "placeholder",
        "fill-in",
    ],
)
def test_placeholder_values_are_refused_by_name(monkeypatch, placeholder):
    with pytest.raises(ConfigError, match="GEMINI_GATEWAY_KEY") as exc:
        load_with(monkeypatch, GEMINI_GATEWAY_KEY=placeholder)
    assert str(exc.value) == "placeholder values must be replaced in .env: GEMINI_GATEWAY_KEY"


def test_placeholder_in_env_file_is_refused(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('DCL_TENANT_ID="<your tenant>"\n')
    with pytest.raises(ConfigError, match="DCL_TENANT_ID"):
        load_settings(env_file=env_file)


def test_real_values_resembling_words_are_not_placeholders(monkeypatch):
    settings = load_with(monkeypatch, DCL_DELEGATED_USERNAME="todo.list@manastuspace.com")
    assert settings.delegated_username == "todo.list@manastuspace.com"


@pytest.mark.parametrize("value", ["C", "a", "Files.Read.All", "AB"])
def test_permission_option_other_than_a_or_b_is_refused(monkeypatch, value):
    with pytest.raises(ConfigError, match="DCL_PERMISSION_OPTION"):
        load_with(monkeypatch, DCL_PERMISSION_OPTION=value)


def test_auth_mode_other_than_delegated_is_refused(monkeypatch):
    with pytest.raises(ConfigError, match="DCL_AUTH_MODE"):
        load_with(monkeypatch, DCL_AUTH_MODE="application")


@pytest.mark.parametrize("value", ["vertex", "developer", "direct"])
def test_gemini_backend_other_than_gateway_is_refused(monkeypatch, value):
    with pytest.raises(ConfigError, match="GEMINI_BACKEND"):
        load_with(monkeypatch, GEMINI_BACKEND=value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GEMINI_CACHE_TTL_S", "-5"),
        ("GEMINI_CACHE_TTL_S", "an hour"),
        ("DCL_DB_PORT", "70000"),
        ("GEMINI_INCLUDE_THOUGHTS", "maybe"),
        ("GEMINI_THINKING_LEVEL", "extreme"),
        ("GEMINI_GATEWAY_URL", "not a url"),
        ("ROLE", "worker"),
    ],
)
def test_malformed_typed_values_are_refused_by_name(monkeypatch, name, value):
    with pytest.raises(ConfigError, match=name):
        load_with(monkeypatch, **{name: value})


def test_folder_lists_of_different_length_are_refused(monkeypatch):
    with pytest.raises(ConfigError, match="DCL_FOLDER_IDS and DCL_FOLDER_PATHS"):
        load_with(monkeypatch, DCL_FOLDER_IDS="id1,id2,id3")


@pytest.mark.parametrize(
    ("group", "dropped"),
    [
        (Group.GEMINI, "GEMINI_GATEWAY_URL"),
        (Group.GEMINI, "GEMINI_GATEWAY_KEY"),
        (Group.GRAPH, "DCL_PERMISSION_OPTION"),
        (Group.GRAPH, "DCL_FOLDER_IDS"),
        (Group.ALERTS, "DCL_ALERT_WEBHOOK_URL"),
    ],
)
def test_require_names_missing_values_of_the_group(monkeypatch, group, dropped):
    values = {k: v for k, v in COMPLETE.items() if k != dropped}
    if dropped == "DCL_FOLDER_IDS":
        values.pop("DCL_FOLDER_PATHS")
    set_env(monkeypatch, values)
    settings = load_settings(env_file=None)
    with pytest.raises(ConfigError, match=dropped):
        settings.require(group)


def test_empty_value_counts_as_missing(monkeypatch):
    settings = load_with(monkeypatch, GEMINI_GATEWAY_KEY="")
    assert settings.gemini_gateway_key is None
    with pytest.raises(ConfigError, match="GEMINI_GATEWAY_KEY"):
        settings.require(Group.GEMINI)


def test_missing_gemini_values_do_not_stop_a_process_that_does_not_need_them(monkeypatch):
    values = {k: v for k, v in COMPLETE.items() if not k.startswith("GEMINI_")}
    set_env(monkeypatch, values)
    assert load_settings(env_file=None).require(Group.GRAPH).tenant_id == "tenant-1"


def test_secrets_never_appear_in_repr_or_errors(monkeypatch):
    settings = load_with(monkeypatch)
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert SECRET not in str(settings.model_dump())
    with pytest.raises(ConfigError) as exc:
        load_with(monkeypatch, DCL_DB_PORT=SECRET)
    assert SECRET not in str(exc.value)


def test_process_environment_overrides_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DCL_PERMISSION_OPTION=B\nDCL_TENANT_ID=from-file\n")
    monkeypatch.setenv("DCL_PERMISSION_OPTION", "A")
    settings = load_settings(env_file=env_file)
    assert settings.permission_option is PermissionOption.A
    assert settings.tenant_id == "from-file"


def test_settings_are_frozen(monkeypatch):
    settings = load_with(monkeypatch)
    with pytest.raises(Exception, match="frozen"):
        settings.tenant_id = "other"


REPO = config.DEFAULT_ENV_FILE.parent


def contract_names_in_manual() -> set[str]:
    text = (REPO / "docs/architecture/01_system_overview_and_tech_stack.md").read_text()
    section = text.split("### 7.1", 1)[1].split("\n## 8", 1)[0]
    return set(re.findall(r"`((?:DCL|GEMINI|GOOGLE)_[A-Z0-9_]+)", section))


def test_env_example_lists_every_manual_name_without_values():
    example = (REPO / ".env.example").read_text()
    names = dict(line.split("=", 1) for line in example.splitlines() if line and not line.startswith("#"))
    expected = contract_names_in_manual() - set(config.FORBIDDEN_NAMES)
    assert expected <= set(names), sorted(expected - set(names))
    assert {k for k, v in names.items() if v.strip()} == set()


def test_loader_reads_every_manual_name():
    assert contract_names_in_manual() - set(config.FORBIDDEN_NAMES) <= config.CONTRACT_NAMES


def test_dev_defaults_apply_only_in_dev(monkeypatch):
    dev = load_settings(env_file=None)
    assert dev.env is Environment.DEV
    assert dev.redis_url == "redis://redis:6379/0"
    assert str(dev.minio_endpoint) == "http://minio:9000/"
    assert str(dev.models_url) == "http://models:8500/"
    assert dev.console_allowed_origins == ["http://localhost:8100"]
    assert dev.require(Group.REDIS, Group.MODELS, Group.LINKS) is dev
    monkeypatch.setenv("DCL_ENV", "prod")
    prod = load_settings(env_file=None)
    assert prod.redis_url is None and prod.minio_endpoint is None and prod.console_allowed_origins == []
    with pytest.raises(ConfigError, match="DCL_REDIS_URL"):
        prod.require(Group.REDIS)
    with pytest.raises(ConfigError, match="DCL_API_BASE_URL, DCL_CONSOLE_BASE_URL"):
        prod.require("links")


def test_explicit_values_override_dev_defaults(monkeypatch):
    monkeypatch.setenv("DCL_REDIS_URL", "redis://localhost:6390/2")
    assert load_settings(env_file=None).redis_url == "redis://localhost:6390/2"


@pytest.mark.parametrize("value", ["qa", "production", "DEV2"])
def test_unknown_environment_is_refused(monkeypatch, value):
    monkeypatch.setenv("DCL_ENV", value)
    with pytest.raises(ConfigError, match="DCL_ENV"):
        load_settings(env_file=None)


def test_redis_url_scheme_is_checked(monkeypatch):
    monkeypatch.setenv("DCL_REDIS_URL", "http://redis:6379")
    with pytest.raises(ConfigError, match="DCL_REDIS_URL"):
        load_settings(env_file=None)


def test_minio_group_needs_the_access_key_pair_even_in_dev(monkeypatch):
    with pytest.raises(ConfigError, match="DCL_MINIO_ACCESS_KEY, DCL_MINIO_SECRET_KEY"):
        load_settings(env_file=None).require(Group.MINIO)
    set_env(
        monkeypatch,
        {"DCL_MINIO_ACCESS_KEY": "dcl-app", "DCL_MINIO_SECRET_KEY": SECRET, "DCL_MINIO_SECURE": "true"},
    )
    settings = load_settings(env_file=None).require(Group.MINIO)
    assert settings.minio_secure is True
    assert SECRET not in repr(settings)


def test_console_auth_group_and_attribute_names(monkeypatch):
    set_env(
        monkeypatch,
        {
            "DCL_TENANT_ID": "tenant-1",
            "DCL_CONSOLE_API_AUDIENCE": "api://dcl-console",
            "DCL_CONSOLE_GROUP_REVIEWERS": "g-rev",
            "DCL_CONSOLE_GROUP_ADMINS": "g-adm",
            "DCL_CONSOLE_GROUP_EXTERNAL_SEARCH": "g-ext",
            "DCL_CONSOLE_ALLOWED_ORIGINS": "https://console.manastu.test, http://localhost:8100",
            "DCL_ENV": "staging",
        },
    )
    s = load_settings(env_file=None).require(Group.CONSOLE_AUTH)
    assert (s.tenant_id, s.console_api_audience) == ("tenant-1", "api://dcl-console")
    assert (s.console_group_reviewers, s.console_group_admins, s.console_group_external_search) == (
        "g-rev",
        "g-adm",
        "g-ext",
    )
    assert s.console_allowed_origins == ["https://console.manastu.test", "http://localhost:8100"]
    monkeypatch.delenv("DCL_CONSOLE_GROUP_EXTERNAL_SEARCH")
    with pytest.raises(ConfigError, match="DCL_CONSOLE_GROUP_EXTERNAL_SEARCH"):
        load_settings(env_file=None).require(Group.CONSOLE_AUTH)


def test_pipe_secret_is_secret_and_required_by_its_group(monkeypatch):
    with pytest.raises(ConfigError, match="DCL_PIPE_SHARED_SECRET"):
        load_settings(env_file=None).require(Group.PIPE)
    monkeypatch.setenv("DCL_PIPE_SHARED_SECRET", SECRET)
    settings = load_settings(env_file=None).require(Group.PIPE)
    assert settings.pipe_shared_secret.get_secret_value() == SECRET
    assert SECRET not in repr(settings)


def test_dcl_role_wins_over_deprecated_role(monkeypatch, caplog):
    monkeypatch.setenv("ROLE", "models")
    assert load_settings(env_file=None).role is Role.MODELS
    assert "ROLE is deprecated" in caplog.text
    monkeypatch.setenv("DCL_ROLE", "api")
    assert load_settings(env_file=None).role is Role.API


def test_gateway_key_falls_back_to_legacy_alias(monkeypatch):
    monkeypatch.setenv("DCL_GEMINI_API_KEY", "legacy-gateway-credential")
    assert load_settings(env_file=None).gemini_gateway_key.get_secret_value() == "legacy-gateway-credential"
    monkeypatch.setenv("GEMINI_GATEWAY_KEY", "")
    assert load_settings(env_file=None).gemini_gateway_key.get_secret_value() == "legacy-gateway-credential"
    monkeypatch.setenv("GEMINI_GATEWAY_KEY", "primary-credential")
    assert load_settings(env_file=None).gemini_gateway_key.get_secret_value() == "primary-credential"


def test_legacy_alias_satisfies_the_gemini_group(monkeypatch):
    set_env(
        monkeypatch,
        {"GEMINI_BACKEND": "gateway", "GEMINI_GATEWAY_URL": "https://gw.test", "DCL_GEMINI_API_KEY": "k"},
    )
    assert load_settings(env_file=None).require(Group.GEMINI)


@pytest.mark.parametrize("name", ["GEMINI_GATEWAY_KEY", "DCL_GEMINI_API_KEY"])
def test_developer_key_format_is_refused_for_both_names(monkeypatch, tmp_path, name):
    developer_key = "AIzaSyD-" + "x" * 31
    monkeypatch.setenv(name, developer_key)
    with pytest.raises(ConfigError, match=f"{name} has the Google Developer API key format") as exc:
        load_settings(env_file=None)
    assert developer_key not in str(exc.value)
    monkeypatch.delenv(name)
    env_file = tmp_path / ".env"
    env_file.write_text(f"{name}={developer_key}\n")
    with pytest.raises(ConfigError, match=name):
        load_settings(env_file=env_file)


def test_stack_database_url_is_built_from_parts_and_escaped(monkeypatch):
    set_env(monkeypatch, {"DCL_DB_USER": "dcl", "DCL_DB_PASSWORD": "p@ss/w:rd"})
    url = load_settings(env_file=None).stack_database_url().get_secret_value()
    assert url == "postgresql+psycopg://dcl:p%40ss%2Fw%3Ard@postgres:5432/dcl_v2"


def test_database_url_wins_when_set(monkeypatch):
    set_env(
        monkeypatch,
        {"DCL_DB_USER": "dcl", "DCL_DB_PASSWORD": "x", "DCL_DATABASE_URL": "postgresql+psycopg://h/db"},
    )
    assert load_settings(env_file=None).stack_database_url().get_secret_value() == "postgresql+psycopg://h/db"


def test_database_group_names_missing_parts(monkeypatch):
    monkeypatch.setenv("DCL_DB_USER", "dcl")
    with pytest.raises(ConfigError, match="DCL_DB_PASSWORD"):
        load_settings(env_file=None).stack_database_url()


@pytest.mark.parametrize("value", ["not-a-key", "c2hvcnQ=", "Wb2zbXq0mkC9w3dE0t2tHhpG6fZcUaFsr3o5rQyPqLM"])
def test_token_cache_key_must_be_a_fernet_key(monkeypatch, value):
    with pytest.raises(ConfigError, match="DCL_TOKEN_CACHE_KEY") as exc:
        load_with(monkeypatch, DCL_TOKEN_CACHE_KEY=value)
    assert value not in str(exc.value)


def test_graph_group_requires_the_token_cache_key(monkeypatch):
    set_env(monkeypatch, {k: v for k, v in COMPLETE.items() if k != "DCL_TOKEN_CACHE_KEY"})
    with pytest.raises(ConfigError, match="DCL_TOKEN_CACHE_KEY"):
        load_settings(env_file=None).require(Group.GRAPH)


def test_outside_drive_id_is_optional_without_default(monkeypatch):
    settings = load_with(monkeypatch)
    assert settings.test_outside_drive_id is None
    assert load_with(monkeypatch, DCL_TEST_OUTSIDE_DRIVE_ID="drive-x").test_outside_drive_id == "drive-x"


def test_model_ids_default_in_every_environment(monkeypatch):
    for env in ("dev", "prod"):
        monkeypatch.setenv("DCL_ENV", env)
        settings = load_settings(env_file=None)
        assert (settings.gemini_model, settings.gemini_lite_model) == (
            "gemini-3.8-flash",
            "gemini-3.1-flash-lite",
        )
    monkeypatch.setenv("GEMINI_LITE_MODEL", "gemini-3.5-flash-lite")
    assert load_settings(env_file=None).gemini_lite_model == "gemini-3.5-flash-lite"
