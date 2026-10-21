"""MinIO store: keys and URIs without a server; get/put/presign against a disposable server.

Set DCL_TEST_MINIO_ENDPOINT (plus DCL_TEST_MINIO_ACCESS_KEY / DCL_TEST_MINIO_SECRET_KEY) to a
throwaway MinIO; the server tests create the five buckets there.
"""

import os
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from minio import Minio

from backend.storage.minio import (
    CIR,
    BucketStore,
    StorageError,
    check_key,
    ensure_buckets,
    parse_uri,
    presign_get,
    presign_put,
    raw_key,
    uri,
)

SHA = "0123456789abcdef" * 4


def test_raw_keys_are_content_addressed():
    assert raw_key(SHA) == f"01/23/{SHA}"
    with pytest.raises(StorageError):
        raw_key("ABC")


@pytest.mark.parametrize("bad", ["", "/abs", "a//b", "a/../b", "a/./b", "trailing/"])
def test_bad_keys_are_refused(bad):
    with pytest.raises(StorageError):
        check_key(bad)


def test_uris_round_trip_and_stay_inside_the_dcl_buckets():
    key = "_vision_cache/gemini-3.8-flash/v3/" + SHA + ".json"
    assert parse_uri(uri(CIR, key)) == (CIR, key)
    for bad in ["s3://other-bucket/x", "https://dcl-cir/x", "s3://dcl-cir/", "s3://dcl-cir/a?versionId=1"]:
        with pytest.raises(StorageError):
            parse_uri(bad)
    with pytest.raises(StorageError):
        BucketStore(client=None, bucket="other")


# ---------- against a disposable server ----------


@pytest.fixture(scope="module")
def client() -> Minio:
    endpoint = os.environ.get("DCL_TEST_MINIO_ENDPOINT")
    if not endpoint:
        pytest.skip("DCL_TEST_MINIO_ENDPOINT is not set")
    parts = urlsplit(endpoint)
    minio = Minio(
        parts.netloc,
        access_key=os.environ.get("DCL_TEST_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("DCL_TEST_MINIO_SECRET_KEY", "minioadmin"),
        secure=parts.scheme == "https",
    )
    ensure_buckets(minio)
    return minio


def test_put_then_get_returns_the_bytes_and_a_missing_key_is_none(client):
    store = BucketStore(client, CIR)
    key = f"_vision_cache/m/v1/{SHA}.json"
    assert store.put(key, b'{"ok": true}', content_type="application/json") == f"s3://dcl-cir/{key}"
    assert store.get(key) == b'{"ok": true}'
    assert store.get("_vision_cache/m/v1/missing.json") is None


def test_ensure_buckets_is_idempotent(client):
    ensure_buckets(client)
    ensure_buckets(client)
    assert {b.name for b in client.list_buckets()} >= {
        "dcl-raw",
        "dcl-cir",
        "dcl-assets",
        "dcl-telemetry",
        "dcl-exports",
    }


def test_presigned_get_downloads_and_expires_in_15_minutes(client):
    store = BucketStore(client, "dcl-assets")
    minio_uri = store.put("pages/" + SHA + "/0001.png", b"\x89PNG fake", content_type="image/png")
    url = presign_get(client, minio_uri)
    assert parse_qs(urlsplit(url).query)["X-Amz-Expires"] == ["900"]
    assert httpx.get(url).content == b"\x89PNG fake"
    with pytest.raises(StorageError, match="at most 15 minutes"):
        presign_get(client, minio_uri, ttl=timedelta(hours=1))


def test_presigned_puts_only_for_user_uploads(client):
    for uri_ in (
        "s3://dcl-raw/01/23/x",
        "s3://dcl-cir/_vision_cache/x.json",
        "s3://dcl-exports/benchmarks/run.json",
    ):
        with pytest.raises(StorageError, match="uploads"):
            presign_put(client, uri_)
    with pytest.raises(StorageError, match="at most 15 minutes"):
        presign_put(client, "s3://dcl-exports/uploads/u1/a", ttl=timedelta(hours=1))


def test_presigned_put_uploads_and_expires_in_15_minutes(client):
    url = presign_put(client, "s3://dcl-exports/uploads/user-1/attachment-1")
    assert parse_qs(urlsplit(url).query)["X-Amz-Expires"] == ["900"]
    assert httpx.put(url, content=b"attachment").status_code == 200
    assert BucketStore(client, "dcl-exports").get("uploads/user-1/attachment-1") == b"attachment"
