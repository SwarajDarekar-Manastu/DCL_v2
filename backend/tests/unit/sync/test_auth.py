"""Delegated auth: encrypted token cache, silent-first token provider, device-code account check."""

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import msal
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from backend.config import PermissionOption
from backend.sync.auth import (
    EncryptedTokenCache,
    GraphAuthConfig,
    ReauthRequired,
    TokenCacheError,
    TokenProvider,
    WrongAccount,
)

USERNAME = "ai@manastuspace.com"
SCOPE_A = ["https://graph.microsoft.com/Files.SelectedOperations.Selected"]
SCOPE_B = ["https://graph.microsoft.com/Files.Read.All"]


@pytest.fixture()
def key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture()
def token_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "token"
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    return directory


@pytest.fixture()
def store(token_dir: Path, key: str) -> EncryptedTokenCache:
    return EncryptedTokenCache(token_dir / "dcl-v2.cache", token_dir, key)


def _changed_cache(marker: str) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    cache.deserialize(json.dumps({"Account": {"home.env.realm": {"username": marker}}}))
    cache.has_state_changed = True
    return cache


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _config(tmp_path: Path, key: str, option: PermissionOption = PermissionOption.A) -> GraphAuthConfig:
    return GraphAuthConfig(
        tenant_id="tenant",
        client_id="client",
        username=USERNAME,
        permission_option=option,
        token_cache_path=tmp_path / "token" / "dcl-v2.cache",
        token_dir=tmp_path / "token",
        token_cache_key=key,
    )


# ---------- encrypted cache ----------


def test_saved_cache_is_encrypted_with_mode_600_and_round_trips(store, key, token_dir):
    store.save(_changed_cache("secret-marker"))

    raw = store.path.read_bytes()
    assert b"secret-marker" not in raw
    assert b"secret-marker" in Fernet(key).decrypt(raw)
    assert _mode(store.path) == 0o600
    assert _mode(token_dir) == 0o700
    assert sorted(p.name for p in token_dir.iterdir()) == ["dcl-v2.cache"]
    assert "secret-marker" in store.load().serialize()


def test_unchanged_cache_is_not_written(store):
    store.save(msal.SerializableTokenCache())
    assert not store.path.exists()


def test_plain_v1_cache_is_refused_and_left_byte_identical(store):
    plain = json.dumps({"RefreshToken": {"x": {"secret": "v1"}}}).encode()
    store.path.write_bytes(plain)
    os.chmod(store.path, 0o600)

    with pytest.raises(TokenCacheError, match="cannot decrypt"):
        store.load()
    with pytest.raises(TokenCacheError, match="cannot decrypt"):
        store.save(_changed_cache("v2"))
    assert store.path.read_bytes() == plain


def test_cache_written_with_another_key_is_refused(store, token_dir):
    other = EncryptedTokenCache(store.path, token_dir, Fernet.generate_key().decode())
    other.save(_changed_cache("other"))
    with pytest.raises(TokenCacheError, match="cannot decrypt"):
        store.load()


def test_loose_directory_mode_is_refused(store, token_dir):
    os.chmod(token_dir, 0o755)
    with pytest.raises(TokenCacheError, match="DCL_TOKEN_DIR"):
        store.load()
    with pytest.raises(TokenCacheError, match="DCL_TOKEN_DIR"):
        store.save(_changed_cache("x"))


def test_loose_file_mode_is_refused(store):
    store.save(_changed_cache("x"))
    os.chmod(store.path, 0o644)
    with pytest.raises(TokenCacheError, match="DCL_TOKEN_CACHE_PATH"):
        store.load()


def test_missing_directory_is_created_with_mode_700(tmp_path, key):
    token_dir = tmp_path / "new" / "token"
    store = EncryptedTokenCache(token_dir / "c.cache", token_dir, key)
    store.save(_changed_cache("x"))
    assert _mode(token_dir) == 0o700
    assert _mode(store.path) == 0o600


def test_cache_path_outside_token_dir_is_refused(tmp_path, token_dir, key):
    with pytest.raises(TokenCacheError, match="inside DCL_TOKEN_DIR"):
        EncryptedTokenCache(tmp_path / "elsewhere.cache", token_dir, key)


def test_invalid_key_is_refused(token_dir):
    with pytest.raises(TokenCacheError, match="valid Fernet key"):
        EncryptedTokenCache(token_dir / "c.cache", token_dir, "not-a-key")


# ---------- token provider ----------


class FakeApp:
    """Stands in for msal.PublicClientApplication; records the calls the provider makes."""

    def __init__(self, cache, accounts=(), silent_result=None, device_username=USERNAME):
        self.cache = cache
        self.accounts = [{"username": name} for name in accounts]
        self.silent_result = silent_result
        self.device_username = device_username
        self.calls: list[tuple] = []

    def get_accounts(self, username=None):
        return [
            a for a in self.accounts if username is None or a["username"].casefold() == username.casefold()
        ]

    def acquire_token_silent(self, scopes, account):
        self.calls.append(("silent", scopes, account["username"]))
        return self.silent_result

    def initiate_device_flow(self, scopes):
        self.calls.append(("initiate_device_flow", scopes))
        return {"user_code": "ABC123", "message": "Open https://microsoft.com/devicelogin and enter ABC123"}

    def acquire_token_by_device_flow(self, flow):
        self.calls.append(("acquire_token_by_device_flow", flow["user_code"]))
        self.accounts.append({"username": self.device_username})
        self.cache.has_state_changed = True
        return {"access_token": "fresh", "id_token_claims": {"preferred_username": self.device_username}}

    def remove_account(self, account):
        self.calls.append(("remove_account", account["username"]))
        self.accounts.remove(account)


def _provider(tmp_path, key, **app_kwargs):
    config = _config(tmp_path, key)
    (tmp_path / "token").mkdir(mode=0o700, exist_ok=True)
    os.chmod(tmp_path / "token", 0o700)
    store = EncryptedTokenCache(config.token_cache_path, config.token_dir, key)
    cache = store.load()
    app = FakeApp(cache, **app_kwargs)
    return TokenProvider(app, store, cache, config), app, store


def test_access_token_is_silent_with_the_configured_scope(tmp_path, key):
    provider, app, _ = _provider(tmp_path, key, accounts=[USERNAME], silent_result={"access_token": "tok"})
    assert provider.access_token() == "tok"
    assert app.calls == [("silent", SCOPE_A, USERNAME)]


def test_no_cached_account_requires_reauth_without_starting_a_device_flow(tmp_path, key):
    provider, app, _ = _provider(tmp_path, key, accounts=["someone@else.com"])
    with pytest.raises(ReauthRequired):
        provider.access_token()
    assert app.calls == []


def test_failed_silent_refresh_requires_reauth(tmp_path, key):
    provider, _, _ = _provider(tmp_path, key, accounts=[USERNAME], silent_result={"error": "invalid_grant"})
    with pytest.raises(ReauthRequired, match="invalid_grant"):
        provider.access_token()


def test_device_code_sign_in_as_the_service_account_saves_the_cache(tmp_path, key):
    provider, app, store = _provider(tmp_path, key)
    shown: list[str] = []

    assert provider.sign_in(shown.append) == USERNAME
    assert shown == ["Open https://microsoft.com/devicelogin and enter ABC123"]
    assert app.calls[0] == ("initiate_device_flow", SCOPE_A)
    assert store.path.exists()


def test_device_code_sign_in_as_another_account_is_rejected_and_not_saved(tmp_path, key):
    provider, app, store = _provider(tmp_path, key, device_username="intruder@manastuspace.com")
    with pytest.raises(WrongAccount, match="intruder@manastuspace.com"):
        provider.sign_in(lambda _: None)
    assert ("remove_account", "intruder@manastuspace.com") in app.calls
    assert app.accounts == []
    assert not store.path.exists()


@pytest.mark.parametrize(("option", "scopes"), [(PermissionOption.A, SCOPE_A), (PermissionOption.B, SCOPE_B)])
def test_scope_follows_the_permission_option(tmp_path, key, option, scopes):
    assert _config(tmp_path, key, option).scopes == scopes


def test_config_from_settings_maps_the_env_contract(tmp_path, key):
    settings = SimpleNamespace(
        tenant_id="t",
        client_id="c",
        delegated_username=USERNAME,
        permission_option=PermissionOption.B,
        token_cache_path=tmp_path / "token" / "c.cache",
        token_dir=tmp_path / "token",
        token_cache_key=SecretStr(key),
        require=lambda *groups: settings,
    )
    config = GraphAuthConfig.from_settings(settings)
    assert config.authority == "https://login.microsoftonline.com/t"
    assert config.token_cache_key == key
    assert config.scopes == SCOPE_B
