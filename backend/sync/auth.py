"""Delegated Graph authentication (file 02 §1, §2).

The service account signs in once with the device-code flow; every later call uses
``acquire_token_silent``. MSAL's cache lives in v2's own file at ``DCL_TOKEN_CACHE_PATH``,
Fernet-encrypted with ``DCL_TOKEN_CACHE_KEY``, mode 600 inside a 700 directory, replaced
atomically. A file that does not decrypt (for example the v1 pipeline's plain cache) is
refused and never overwritten.

CLI, run by the operator:
    python -m backend.sync.auth sign-in    one-time device-code sign-in as DCL_DELEGATED_USERNAME
    python -m backend.sync.auth check      silent token, the four roots, the outside-share negative check
"""

import logging
import os
import stat
import sys
import tempfile
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import msal
from cryptography.fernet import Fernet, InvalidToken

from backend.config import Group, PermissionOption, Settings, get_settings
from backend.sync.graph_client import GraphClient

log = logging.getLogger(__name__)

GRAPH_SCOPES: dict[PermissionOption, list[str]] = {
    PermissionOption.A: ["https://graph.microsoft.com/Files.SelectedOperations.Selected"],
    PermissionOption.B: ["https://graph.microsoft.com/Files.Read.All"],
}
OUTSIDE_DENIED_STATUSES = (403, 404)


class AuthError(RuntimeError):
    pass


class TokenCacheError(AuthError):
    pass


class ReauthRequired(AuthError):
    """No usable account or refresh token in the cache: the operator must run the device-code sign-in."""


class WrongAccount(AuthError):
    pass


@dataclass(frozen=True)
class GraphAuthConfig:
    tenant_id: str
    client_id: str
    username: str
    permission_option: PermissionOption
    token_cache_path: Path
    token_dir: Path
    token_cache_key: str

    @property
    def scopes(self) -> list[str]:
        return GRAPH_SCOPES[self.permission_option]

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"

    @classmethod
    def from_settings(cls, settings: Settings) -> "GraphAuthConfig":
        settings.require(Group.GRAPH)
        return cls(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            username=settings.delegated_username,
            permission_option=settings.permission_option,
            token_cache_path=settings.token_cache_path,
            token_dir=settings.token_dir,
            token_cache_key=settings.token_cache_key.get_secret_value(),
        )


class EncryptedTokenCache:
    """Load and save an MSAL ``SerializableTokenCache`` as one Fernet token on disk."""

    def __init__(self, path: Path, token_dir: Path, key: str) -> None:
        if not path.resolve().is_relative_to(token_dir.resolve()):
            raise TokenCacheError("DCL_TOKEN_CACHE_PATH must be inside DCL_TOKEN_DIR")
        try:
            self._fernet = Fernet(key)
        except ValueError:
            raise TokenCacheError("DCL_TOKEN_CACHE_KEY is not a valid Fernet key") from None
        self.path = path
        self.token_dir = token_dir

    def load(self) -> msal.SerializableTokenCache:
        cache = msal.SerializableTokenCache()
        if self.token_dir.exists():
            _refuse_loose_mode(self.token_dir, "DCL_TOKEN_DIR", 0o700)
        if self.path.exists():
            cache.deserialize(self._read_plaintext())
        return cache

    def save(self, cache: msal.SerializableTokenCache) -> None:
        if not cache.has_state_changed:
            return
        self._ensure_dir()
        if self.path.exists():
            self._read_plaintext()  # refuses to replace a file this key cannot read
        payload = self._fernet.encrypt(cache.serialize().encode())
        fd, tmp_name = tempfile.mkstemp(dir=self.token_dir, prefix=".token-cache-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        _fsync_dir(self.token_dir)
        cache.has_state_changed = False

    def _read_plaintext(self) -> str:
        _refuse_loose_mode(self.path, "DCL_TOKEN_CACHE_PATH", 0o600)
        try:
            return self._fernet.decrypt(self.path.read_bytes()).decode()
        except InvalidToken:
            raise TokenCacheError(
                "DCL_TOKEN_CACHE_PATH holds a file that DCL_TOKEN_CACHE_KEY cannot decrypt (the v1 plain "
                "cache, or a different key); it is left untouched. "
                "Point DCL_TOKEN_CACHE_PATH at v2's own file."
            ) from None

    def _ensure_dir(self) -> None:
        if not self.token_dir.exists():
            self.token_dir.mkdir(parents=True, mode=0o700)
            os.chmod(self.token_dir, 0o700)
        _refuse_loose_mode(self.token_dir, "DCL_TOKEN_DIR", 0o700)


def _refuse_loose_mode(path: Path, name: str, allowed: int) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & ~allowed:
        raise TokenCacheError(f"{name} must not be accessible beyond mode {allowed:o} (found {mode:o})")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class TokenProvider:
    """Silent token acquisition for the configured account; device-code sign-in when the operator asks."""

    def __init__(
        self,
        app: msal.PublicClientApplication,
        store: EncryptedTokenCache,
        cache: msal.SerializableTokenCache,
        config: GraphAuthConfig,
    ) -> None:
        self._app = app
        self._store = store
        self._cache = cache
        self._config = config
        self._lock = threading.Lock()

    @classmethod
    def create(cls, config: GraphAuthConfig) -> "TokenProvider":
        store = EncryptedTokenCache(config.token_cache_path, config.token_dir, config.token_cache_key)
        cache = store.load()
        app = msal.PublicClientApplication(config.client_id, authority=config.authority, token_cache=cache)
        return cls(app, store, cache, config)

    def access_token(self) -> str:
        with self._lock:
            accounts = self._app.get_accounts(username=self._config.username)
            if not accounts:
                raise ReauthRequired(
                    f"no cached account for {self._config.username}; run the device-code sign-in"
                )
            result = self._app.acquire_token_silent(self._config.scopes, account=accounts[0])
            self._store.save(self._cache)
        if not result or "access_token" not in result:
            error = (result or {}).get("error", "no_token")
            raise ReauthRequired(f"silent token acquisition failed ({error}); run the device-code sign-in")
        return result["access_token"]

    def sign_in(self, show: Callable[[str], None]) -> str:
        """Device-code flow. ``show`` receives MSAL's message with the code and verification URL."""
        flow = self._app.initiate_device_flow(scopes=self._config.scopes)
        if "user_code" not in flow:
            raise AuthError(f"device flow could not start ({flow.get('error', 'unknown')})")
        show(flow["message"])
        with self._lock:
            result = self._app.acquire_token_by_device_flow(flow)
            if "access_token" not in result:
                raise AuthError(f"device-code sign-in failed ({result.get('error', 'unknown')})")
            signed_in = result.get("id_token_claims", {}).get("preferred_username", "")
            if signed_in.casefold() != self._config.username.casefold():
                for account in self._app.get_accounts(username=signed_in):
                    self._app.remove_account(account)
                self._cache.has_state_changed = False
                raise WrongAccount(f"signed in as {signed_in or 'unknown'}, expected {self._config.username}")
            self._store.save(self._cache)
        return signed_in


@dataclass(frozen=True)
class RootAccess:
    folder_id: str
    expected_name: str
    status: int
    name: str | None

    @property
    def ok(self) -> bool:
        return self.status == 200


@dataclass(frozen=True)
class OutsideCheck:
    drive_id: str
    item_id: str
    status: int

    @property
    def passed(self) -> bool:
        return self.status in OUTSIDE_DENIED_STATUSES


@dataclass(frozen=True)
class AccessReport:
    roots: list[RootAccess]
    outside: OutsideCheck | None

    @property
    def ok(self) -> bool:
        return all(root.ok for root in self.roots) and self.outside is not None and self.outside.passed


def check_access(
    client: GraphClient,
    drive_id: str,
    folder_ids: Sequence[str],
    folder_paths: Sequence[str],
    outside_item_id: str | None,
    outside_drive_id: str | None = None,
) -> AccessReport:
    """Each root must answer 200; the outside item must answer 403 or 404 from its own drive."""
    roots = []
    for folder_id, expected in zip(folder_ids, folder_paths, strict=True):
        response = client.get(f"/drives/{drive_id}/items/{folder_id}", params={"$select": "id,name,folder"})
        name = response.json().get("name") if response.status_code == 200 else None
        roots.append(
            RootAccess(folder_id=folder_id, expected_name=expected, status=response.status_code, name=name)
        )
    outside = None
    if outside_item_id:
        target_drive = outside_drive_id or drive_id
        response = client.get(f"/drives/{target_drive}/items/{outside_item_id}", params={"$select": "id"})
        outside = OutsideCheck(drive_id=target_drive, item_id=outside_item_id, status=response.status_code)
        log.info("outside-share check on drive %s returned %s", target_drive, response.status_code)
    return AccessReport(roots=roots, outside=outside)


def _report_lines(report: AccessReport) -> list[str]:
    lines = []
    for root in report.roots:
        verdict = "ok" if root.ok else "FAILED"
        lines.append(f"root {root.expected_name}: HTTP {root.status} {verdict} (Graph name: {root.name})")
    if report.outside is None:
        lines.append("outside-share check: FAILED (DCL_TEST_OUTSIDE_ITEM_ID is not set)")
    else:
        verdict = "passed" if report.outside.passed else "FAILED: the identity can see it or the call errored"
        lines.append(
            f"outside-share check on drive {report.outside.drive_id}: HTTP {report.outside.status} {verdict}"
        )
    return lines


def main(argv: Sequence[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if len(argv) != 1 or argv[0] not in ("sign-in", "check"):
        print("usage: python -m backend.sync.auth sign-in | check", file=sys.stderr)
        return 2
    settings = get_settings()
    provider = TokenProvider.create(GraphAuthConfig.from_settings(settings))
    if argv[0] == "sign-in":
        print(f"signed in as {provider.sign_in(print)}")
        return 0
    with GraphClient(provider.access_token) as client:
        report = check_access(
            client,
            settings.drive_id,
            settings.folder_ids,
            settings.folder_paths,
            settings.test_outside_item_id,
            settings.test_outside_drive_id,
        )
    print("\n".join(_report_lines(report)))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
