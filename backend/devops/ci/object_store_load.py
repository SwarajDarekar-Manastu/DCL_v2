"""M6-scale object-store load test (object-store decision 2026-10-22, RustFS adoption step 3).

    uv run python backend/devops/ci/object_store_load.py --endpoint URL --access-key K --secret-key S \\
        [--name rustfs] [--blobs 5200] [--threads 16]

Writes the M6 object count with S1's key layout and the minio-py client the pipeline uses: one raw blob per
document (lognormal sizes, median about 200 KB, capped at 4 MB) in versioned dcl-raw, one CIR JSON per
document in versioned dcl-cir, two page assets per document in dcl-assets. Then lists every bucket in full,
stats and reads back a sample (content checked by sha256). The data is seeded, so every store gets identical
bytes. Prints p50/p95/p99 per operation, throughput and errors as JSON; exit 1 on any error or mismatch.
"""

# ruff: noqa: S311  (seeded test data, identical across stores; not security-relevant)

import argparse
import hashlib
import io
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

from minio import Minio
from minio.commonconfig import ENABLED
from minio.credentials import StaticProvider
from minio.versioningconfig import VersioningConfig

RAW, CIR, ASSETS = "dcl-raw", "dcl-cir", "dcl-assets"
MAX_RAW = 4 * 1024 * 1024


@dataclass(frozen=True)
class Obj:
    bucket: str
    key: str
    seed: int
    size: int


def body(obj: Obj) -> bytes:
    return random.Random(obj.seed).randbytes(obj.size)


def plan(blobs: int) -> list[Obj]:
    rng = random.Random(6)
    objects: list[Obj] = []
    for i in range(blobs):
        sha = hashlib.sha256(f"doc-{i}".encode()).hexdigest()
        raw_size = min(MAX_RAW, max(1024, int(rng.lognormvariate(12.2, 1.1))))
        objects.append(Obj(RAW, f"{sha[0:2]}/{sha[2:4]}/{sha}", i * 4, raw_size))
        objects.append(Obj(CIR, f"{sha}/cir.json", i * 4 + 1, rng.randint(4_000, 60_000)))
        for page in (1, 2):
            objects.append(
                Obj(ASSETS, f"{sha}/page-{page:04d}.png", i * 4 + 1 + page, rng.randint(60_000, 300_000))
            )
    return objects


def pct(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    q = statistics.quantiles(values, n=100, method="inclusive")
    return {"n": len(values), "p50_ms": q[49], "p95_ms": q[94], "p99_ms": q[98], "max_ms": max(values)}


def timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--access-key", required=True)
    parser.add_argument("--secret-key", required=True)
    parser.add_argument("--name", default="store")
    parser.add_argument("--blobs", type=int, default=5200)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--sample", type=int, default=2000)
    args = parser.parse_args()
    url = urlsplit(args.endpoint)
    store = Minio(
        url.netloc, credentials=StaticProvider(args.access_key, args.secret_key), secure=url.scheme == "https"
    )
    for bucket in (RAW, CIR, ASSETS):
        if not store.bucket_exists(bucket):
            store.make_bucket(bucket)
    for bucket in (RAW, CIR):
        store.set_bucket_versioning(bucket, VersioningConfig(ENABLED))

    objects = plan(args.blobs)
    errors: list[str] = []
    lat: dict[str, list[float]] = {"put_raw": [], "put_cir": [], "put_assets": [], "stat": [], "get": []}

    def put(obj: Obj) -> None:
        data = body(obj)
        try:
            ms = timed(lambda: store.put_object(obj.bucket, obj.key, io.BytesIO(data), len(data)))
            lat[f"put_{obj.bucket.removeprefix('dcl-')}"].append(ms)
        except Exception as exc:  # noqa: BLE001 (counted and reported)
            errors.append(f"put {obj.bucket}/{obj.key}: {type(exc).__name__}")

    started = time.perf_counter()
    with ThreadPoolExecutor(args.threads) as pool:
        list(pool.map(put, objects))
    put_s = time.perf_counter() - started
    total_bytes = sum(o.size for o in objects)

    listing: dict[str, dict[str, float]] = {}
    for bucket in (RAW, CIR, ASSETS):
        start = time.perf_counter()
        count = sum(1 for _ in store.list_objects(bucket, recursive=True))
        listing[bucket] = {"objects": count, "seconds": round(time.perf_counter() - start, 3)}
        expected = sum(1 for o in objects if o.bucket == bucket)
        if count != expected:
            errors.append(f"list {bucket}: {count} objects, expected {expected}")

    sample = random.Random(7).sample(objects, min(args.sample, len(objects)))

    def read(obj: Obj) -> None:
        try:
            lat["stat"].append(timed(lambda: store.stat_object(obj.bucket, obj.key)))
            got: list[bytes] = []

            def fetch() -> None:
                response = store.get_object(obj.bucket, obj.key)
                try:
                    got.append(response.read())
                finally:
                    response.close()
                    response.release_conn()

            lat["get"].append(timed(fetch))
            if hashlib.sha256(got[0]).digest() != hashlib.sha256(body(obj)).digest():
                errors.append(f"content mismatch {obj.bucket}/{obj.key}")
        except Exception as exc:  # noqa: BLE001 (counted and reported)
            errors.append(f"read {obj.bucket}/{obj.key}: {type(exc).__name__}")

    with ThreadPoolExecutor(args.threads) as pool:
        list(pool.map(read, sample))

    summary = {
        "name": args.name,
        "objects": len(objects),
        "bytes": total_bytes,
        "threads": args.threads,
        "put_seconds": round(put_s, 1),
        "put_objects_per_s": round(len(objects) / put_s, 1),
        "put_mib_per_s": round(total_bytes / put_s / 2**20, 1),
        "latency": {op: {k: round(v, 1) for k, v in pct(values).items()} for op, values in lat.items()},
        "list": listing,
        "errors": len(errors),
        "first_errors": errors[:5],
    }
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
