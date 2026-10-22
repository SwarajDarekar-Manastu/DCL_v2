"""S3 compatibility check for DCL's object store (docs/architecture/05 §1, §6; 09 §H.1 object-store decision).

    uv run python backend/devops/ci/s3_compat_check.py --endpoint http://127.0.0.1:9000 \\
        --access-key KEY --secret-key SECRET [--name minio]

Exercises exactly what DCL relies on, with the minio-py client S1's storage code uses: bucket create and
list, put/get/stat with user metadata, multipart upload, bucket versioning (two versions, read an old version,
delete marker, version-exact delete), lifecycle rules (prefix expiration, noncurrent-version expiration,
expired delete markers) read back after set, presigned GET over plain HTTP, and DuckDB httpfs reading
Parquet. Prints one line per check and a JSON summary; exit 1 when a required check fails.
"""

import argparse
import io
import json
import sys
import uuid
from collections.abc import Callable
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from minio import Minio
from minio.commonconfig import ENABLED, Filter
from minio.lifecycleconfig import Expiration, LifecycleConfig, NoncurrentVersionExpiration, Rule
from minio.versioningconfig import VersioningConfig

REQUIRED = (
    "bucket_create",
    "put_get_metadata",
    "multipart_upload",
    "versioning",
    "version_exact_delete",
    "lifecycle_prefix_expiration",
    "lifecycle_noncurrent_expiration",
    "presigned_get",
    "duckdb_httpfs_parquet",
)


def run(endpoint: str, access_key: str, secret_key: str, name: str) -> dict:
    url = urlsplit(endpoint)
    client = Minio(url.netloc, access_key=access_key, secret_key=secret_key, secure=url.scheme == "https")
    bucket = f"dcl-compat-{uuid.uuid4().hex[:8]}"
    results: dict[str, tuple[bool, str]] = {}

    def check(key: str, fn: Callable[[], str]) -> None:
        try:
            results[key] = (True, fn())
        except Exception as exc:  # noqa: BLE001 - every failure is a finding
            results[key] = (False, f"{type(exc).__name__}: {str(exc)[:160]}")
        ok, detail = results[key]
        print(f"[{name}] {'PASS' if ok else 'FAIL'} {key}: {detail}", flush=True)

    def bucket_create() -> str:
        client.make_bucket(bucket)
        assert bucket in [b.name for b in client.list_buckets()]
        return "created and listed"

    def put_get_metadata() -> str:
        client.put_object(
            bucket, "a/b/one.bin", io.BytesIO(b"hello"), 5, metadata={"original-name": "one.bin"}
        )
        stat = client.stat_object(bucket, "a/b/one.bin")
        meta = {k.lower(): v for k, v in (stat.metadata or {}).items()}
        assert client.get_object(bucket, "a/b/one.bin").read() == b"hello"
        assert any(v == "one.bin" for k, v in meta.items() if "original-name" in k), meta
        keys = [o.object_name for o in client.list_objects(bucket, prefix="a/", recursive=True)]
        assert keys == ["a/b/one.bin"], keys
        return "bytes, user metadata and prefix listing round-trip"

    def multipart_upload() -> str:
        data = uuid.uuid4().bytes * (20 * 1024 * 1024 // 16)
        client.put_object(bucket, "big.bin", io.BytesIO(data), len(data), part_size=5 * 1024 * 1024)
        assert client.get_object(bucket, "big.bin").read() == data
        return f"{len(data) // (1024 * 1024)} MiB in 5 MiB parts"

    versions: dict[str, str] = {}

    def versioning() -> str:
        client.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
        assert client.get_bucket_versioning(bucket).status == ENABLED
        first = client.put_object(bucket, "v/key.txt", io.BytesIO(b"v1"), 2).version_id
        second = client.put_object(bucket, "v/key.txt", io.BytesIO(b"v2"), 2).version_id
        assert first and second and first != second, (first, second)
        assert client.get_object(bucket, "v/key.txt", version_id=first).read() == b"v1"
        client.remove_object(bucket, "v/key.txt")
        listed = list(client.list_objects(bucket, prefix="v/", include_version=True))
        markers = [o for o in listed if o.is_delete_marker]
        assert len(listed) == 3 and len(markers) == 1, [(o.version_id, o.is_delete_marker) for o in listed]
        versions.update(first=first, second=second)
        return "two versions, old version readable, delete leaves a marker"

    def version_exact_delete() -> str:
        client.remove_object(bucket, "v/key.txt", version_id=versions["first"])
        remaining = [o.version_id for o in client.list_objects(bucket, prefix="v/", include_version=True)]
        assert versions["first"] not in remaining and len(remaining) == 2, remaining
        return "deleting a version id removes exactly that version"

    def lifecycle_prefix_expiration() -> str:
        rules = [
            Rule(
                ENABLED,
                rule_filter=Filter(prefix="_vision_cache/"),
                rule_id="r1",
                expiration=Expiration(days=180),
            )
        ]
        client.set_bucket_lifecycle(bucket, LifecycleConfig(rules))
        back = client.get_bucket_lifecycle(bucket).rules
        assert [(r.rule_id, r.rule_filter.prefix, r.expiration.days) for r in back] == [
            ("r1", "_vision_cache/", 180)
        ]
        return "prefix expiration set and read back"

    def lifecycle_noncurrent_expiration() -> str:
        rules = [
            Rule(
                ENABLED,
                rule_filter=Filter(prefix="_incoming/"),
                rule_id="r2",
                noncurrent_version_expiration=NoncurrentVersionExpiration(noncurrent_days=1),
                expiration=Expiration(expired_object_delete_marker=True),
            )
        ]
        client.set_bucket_lifecycle(bucket, LifecycleConfig(rules))
        [back] = client.get_bucket_lifecycle(bucket).rules
        assert back.noncurrent_version_expiration.noncurrent_days == 1
        assert back.expiration.expired_object_delete_marker is True
        return "noncurrent-version expiry and delete-marker cleanup set and read back"

    def presigned_get() -> str:
        link = client.presigned_get_object(bucket, "a/b/one.bin", expires=timedelta(minutes=15))
        response = httpx.get(link, timeout=20)
        assert response.status_code == 200 and response.content == b"hello", response.status_code
        return "15-minute link served the object"

    def duckdb_httpfs_parquet() -> str:
        import duckdb
        import pyarrow as pa
        import pyarrow.parquet as pq

        sink = io.BytesIO()
        pq.write_table(pa.table({"t_rel_ms": [0, 1, 2], "thrust_n": [1.0, 3.0, 2.0]}), sink)
        client.put_object(bucket, "run/normalized.parquet", io.BytesIO(sink.getvalue()), sink.tell())
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(
            "CREATE SECRET s (TYPE s3, KEY_ID ?, SECRET ?, ENDPOINT ?, URL_STYLE 'path', USE_SSL ?, "
            "REGION 'us-east-1')",
            [access_key, secret_key, url.netloc, url.scheme == "https"],
        )
        parquet = f"s3://{bucket}/run/normalized.parquet"
        peak = con.execute("SELECT max(thrust_n) FROM read_parquet(?)", [parquet]).fetchone()[0]
        assert peak == 3.0, peak
        return "DuckDB read_parquet over s3:// returned max(thrust_n) = 3.0"

    for key, fn in (
        ("bucket_create", bucket_create),
        ("put_get_metadata", put_get_metadata),
        ("multipart_upload", multipart_upload),
        ("versioning", versioning),
        ("version_exact_delete", version_exact_delete),
        ("lifecycle_prefix_expiration", lifecycle_prefix_expiration),
        ("lifecycle_noncurrent_expiration", lifecycle_noncurrent_expiration),
        ("presigned_get", presigned_get),
        ("duckdb_httpfs_parquet", duckdb_httpfs_parquet),
    ):
        check(key, fn)
    summary = {
        "store": name,
        "passed": [k for k, (ok, _) in results.items() if ok],
        "failed": {k: d for k, (ok, d) in results.items() if not ok},
    }
    summary["all_required_passed"] = all(results.get(k, (False, ""))[0] for k in REQUIRED)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--access-key", required=True)
    parser.add_argument("--secret-key", required=True)
    parser.add_argument("--name", default="store")
    args = parser.parse_args(argv)
    summary = run(args.endpoint, args.access_key, args.secret_key, args.name)
    print(json.dumps(summary, indent=2))
    return 0 if summary["all_required_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
