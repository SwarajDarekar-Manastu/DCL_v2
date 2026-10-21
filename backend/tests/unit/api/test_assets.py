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
