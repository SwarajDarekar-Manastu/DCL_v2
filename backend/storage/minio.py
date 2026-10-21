"""The one module that talks to MinIO (file 05 §1): buckets, keys, get/put, presigned GETs.

Objects are addressed as ``s3://{bucket}/{key}`` in the database (``minio_uri`` columns).
Keys never start with ``/`` and never contain empty or ``..`` segments. Originals are
content-addressed: ``dcl-raw/{sha256[0:2]}/{sha256[2:4]}/{sha256}``.
"""

import io
import re
from collections.abc import Mapping
from datetime import timedelta
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error

from backend.config import Group, Settings

RAW = "dcl-raw"
CIR = "dcl-cir"
ASSETS = "dcl-assets"
TELEMETRY = "dcl-telemetry"
EXPORTS = "dcl-exports"
BUCKETS = (RAW, CIR, ASSETS, TELEMETRY, EXPORTS)
PRESIGN_TTL = timedelta(minutes=15)
MISSING_CODES = frozenset({"NoSuchKey", "NoSuchObject"})
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class StorageError(ValueError):
    pass


def client_from_settings(settings: Settings) -> Minio:
    settings.require(Group.MINIO)
    endpoint = urlsplit(str(settings.minio_endpoint))
    return Minio(
        endpoint.netloc,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure or endpoint.scheme == "https",
    )


def check_key(key: str) -> str:
    if not key or key.startswith("/") or any(part in ("", ".", "..") for part in key.split("/")):
        raise StorageError(f"invalid object key {key!r}")
    return key


def parse_uri(minio_uri: str) -> tuple[str, str]:
    """``s3://bucket/key`` → ``(bucket, key)`` for one of the five DCL buckets."""
    parts = urlsplit(minio_uri)
    bucket, key = parts.netloc, parts.path.removeprefix("/")
    if parts.scheme != "s3" or bucket not in BUCKETS or parts.query or parts.fragment:
        raise StorageError(f"not a DCL object URI: {minio_uri!r}")
    return bucket, check_key(key)


def uri(bucket: str, key: str) -> str:
    if bucket not in BUCKETS:
        raise StorageError(f"unknown bucket {bucket!r}")
    return f"s3://{bucket}/{check_key(key)}"


def raw_key(sha256: str) -> str:
    if not SHA256_HEX.fullmatch(sha256):
        raise StorageError("raw keys are lowercase hex SHA-256 digests")
    return f"{sha256[0:2]}/{sha256[2:4]}/{sha256}"


def ensure_buckets(client: Minio) -> None:
    for bucket in BUCKETS:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)


class BucketStore:
    """Small objects of one bucket held in memory (CIR JSON, vision cache, staged payloads)."""

    def __init__(self, client: Minio, bucket: str) -> None:
        if bucket not in BUCKETS:
            raise StorageError(f"unknown bucket {bucket!r}")
        self._client = client
        self.bucket = bucket

    def get(self, key: str) -> bytes | None:
        """The object's bytes, or None when the key does not exist; any other error raises."""
        try:
            response = self._client.get_object(self.bucket, check_key(key))
        except S3Error as exc:
            if exc.code in MISSING_CODES:
                return None
            raise
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> str:
        """Write (or overwrite) one object; returns its ``s3://`` URI."""
        self._client.put_object(
            self.bucket,
            check_key(key),
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
            metadata=dict(metadata) if metadata else None,
        )
        return uri(self.bucket, key)


def presign_get(client: Minio, minio_uri: str, ttl: timedelta = PRESIGN_TTL) -> str:
    """A GET URL valid for ``ttl`` (15 minutes by default). Callers check the user's session first."""
    if ttl > PRESIGN_TTL:
        raise StorageError("presigned URLs live at most 15 minutes")
    bucket, key = parse_uri(minio_uri)
    return client.presigned_get_object(bucket, key, expires=ttl)


UPLOAD_PREFIX = "uploads/"


def presign_put(client: Minio, minio_uri: str, ttl: timedelta = PRESIGN_TTL) -> str:
    """A PUT URL for a user upload, valid for ``ttl`` (15 minutes at most); callers check identity first.

    Only ``s3://dcl-exports/uploads/…`` is allowed: a writable URL into dcl-raw or dcl-cir could
    overwrite content-addressed data.
    """
    if ttl > PRESIGN_TTL:
        raise StorageError("presigned URLs live at most 15 minutes")
    bucket, key = parse_uri(minio_uri)
    if bucket != EXPORTS or not key.startswith(UPLOAD_PREFIX):
        raise StorageError("presigned PUTs are only issued for s3://dcl-exports/uploads/…")
    return client.presigned_put_object(bucket, key, expires=ttl)
