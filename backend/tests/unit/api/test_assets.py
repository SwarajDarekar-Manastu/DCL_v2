from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import assets, auth


class FakeMinio:
    def __init__(self):
        self.calls = []

    def presigned_get_object(self, bucket, key, expires):
        self.calls.append((bucket, key, expires))
        return f"https://minio.example/{bucket}/{key}?X-Amz-Expires={int(expires.total_seconds())}"


@pytest.fixture
def minio():
    return FakeMinio()


@pytest.fixture
def client(auth_config, key_resolver, minio):
    app = FastAPI()
    app.include_router(assets.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    app.dependency_overrides[assets.get_minio] = lambda: minio
    return TestClient(app)


def get(client, token, uri):
    return client.get("/assets/url", params={"uri": uri}, headers={"Authorization": f"Bearer {token()}"})


def test_presigns_an_asset_for_fifteen_minutes(client, token, minio):
    response = get(client, token, "s3://dcl-assets/sparklines/run-1/pt_101.png")
    assert response.status_code == 200
    assert response.json() == {
        "url": "https://minio.example/dcl-assets/sparklines/run-1/pt_101.png?X-Amz-Expires=900",
        "expires_in_s": 900,
    }
    assert minio.calls == [("dcl-assets", "sparklines/run-1/pt_101.png", timedelta(minutes=15))]


@pytest.mark.parametrize(
    ("uri", "code"),
    [
        ("s3://dcl-raw/9f/86/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08", 403),
        ("s3://dcl-telemetry/run-1/normalized.parquet", 403),
        ("s3://dcl-assets/../dcl-raw/x", 400),
        ("https://evil.example/x.png", 400),
        ("s3://other-bucket/x.png", 400),
    ],
)
def test_refuses_everything_but_assets(client, token, minio, uri, code):
    assert get(client, token, uri).status_code == code
    assert minio.calls == []


def test_requires_sign_in(client, minio):
    assert client.get("/assets/url", params={"uri": "s3://dcl-assets/a.png"}).status_code == 401


class UploadMinio(FakeMinio):
    def presigned_put_object(self, bucket, key, expires):
        self.calls.append(("PUT", bucket, key, expires))
        return f"https://minio.example/{bucket}/{key}?put"


@pytest.fixture
def pipe_client(minio, monkeypatch):
    from types import SimpleNamespace

    from pydantic import SecretStr

    from backend.api import engine

    settings = SimpleNamespace(pipe_shared_secret=SecretStr("s3cret"))
    settings.require = lambda *groups: settings
    monkeypatch.setattr(engine, "get_settings", lambda: settings)
    upload_minio = UploadMinio()
    app = FastAPI()
    app.include_router(assets.router)
    app.dependency_overrides[assets.get_minio] = lambda: upload_minio
    return TestClient(app), upload_minio


def signed(body: bytes, user_id="owui/u 1"):
    import time

    from backend.api.engine import sign_identity

    ts = str(int(time.time()))
    return {
        "X-DCL-User-Id": user_id,
        "X-DCL-User-Email": "asha@manastuspace.com",
        "X-DCL-User-Groups": "",
        "X-DCL-Timestamp": ts,
        "X-DCL-Signature": sign_identity("s3cret", ts, user_id, "asha@manastuspace.com", "", body),
        "Content-Type": "application/json",
    }


def test_upload_slot_for_the_pipe(pipe_client):
    client, upload_minio = pipe_client
    body = b'{"file_name": "bed.png", "mime_type": "image/png", "size_bytes": 2048}'
    response = client.post("/assets/upload", content=body, headers=signed(body))
    assert response.status_code == 201
    slot = response.json()
    assert slot["object_uri"].startswith("s3://dcl-exports/uploads/owui_u_1/")
    key = slot["object_uri"].removeprefix("s3://dcl-exports/")
    assert slot["upload_url"] == f"https://minio.example/dcl-exports/{key}?put"
    assert slot["get_url"].startswith(f"https://minio.example/dcl-exports/{key}?X-Amz-Expires=900")
    assert slot["expires_in_s"] == 900


def test_upload_refuses_unsigned_and_oversized(pipe_client):
    client, upload_minio = pipe_client
    body = b'{"file_name": "a", "mime_type": "text/plain", "size_bytes": 1}'
    assert client.post("/assets/upload", content=body).status_code == 422  # identity headers missing
    tampered = signed(body) | {"X-DCL-User-Id": "someone-else"}
    assert client.post("/assets/upload", content=body, headers=tampered).status_code == 401
    big = b'{"file_name": "scan.pdf", "mime_type": "application/pdf", "size_bytes": 26214401}'
    response = client.post("/assets/upload", content=big, headers=signed(big))
    assert response.status_code == 413
    assert upload_minio.calls == []
