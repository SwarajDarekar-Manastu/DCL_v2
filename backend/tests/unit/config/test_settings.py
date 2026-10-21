import pytest

from backend import config
from backend.config import ConfigError, Group, PermissionOption, ThinkingLevel, load_settings

SECRET = "s3cr3t-value-that-must-never-leak"

COMPLETE = {
    "DCL_TENANT_ID": "tenant-1",
    "DCL_CLIENT_ID": "client-1",
    "DCL_AUTH_MODE": "delegated",
    "DCL_DELEGATED_USERNAME": "ai@manastuspace.com",
    "DCL_PERMISSION_OPTION": "A",
    "DCL_TOKEN_CACHE_PATH": "/var/lib/dcl/token_cache.bin",
    "DCL_TOKEN_DIR": "/var/lib/dcl",
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
