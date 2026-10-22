"""One-day lifecycle watch for the object store (object-store decision 2026-10-22, RustFS adoption step 2).

    uv run python backend/devops/ci/lifecycle_watch.py seed --endpoint URL --access-key ROOT --secret-key S
    uv run python backend/devops/ci/lifecycle_watch.py check --endpoint URL --access-key ROOT --secret-key S

`seed` applies the real rules by running backend/devops/minio_init.py against the store, then writes three
objects that the 1-day rules must remove and three controls that must stay. `check` lists every version and
delete marker of those keys and prints one line per case. S3 counts lifecycle days from the object's time
and rounds up to the next midnight UTC, so the 1-day cases are due at most two midnights after the seed.
Exit 0: all cases as expected; 1: a control lost data or a case is overdue; 2: not yet due.
"""

import argparse
import io
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from minio import Minio
from minio.credentials import StaticProvider

REPO = Path(__file__).resolve().parents[3]
PREFIX = "lifecycle-watch"


@dataclass(frozen=True)
class Case:
    name: str
    bucket: str
    key: str
    overwrite: bool
    delete: bool
    expires: bool  # True: the 1-day rules must remove every non-current trace


CASES = (
    Case("incoming noncurrent version", "dcl-raw", f"_incoming/{PREFIX}/overwritten", True, False, True),
    Case("incoming deleted object + marker", "dcl-raw", f"_incoming/{PREFIX}/deleted", False, True, True),
    Case("chat upload 1 day", "dcl-exports", f"uploads/{PREFIX}.txt", False, False, True),
    Case("raw outside _incoming keeps versions", "dcl-raw", f"{PREFIX}/overwritten", True, False, False),
    Case("export 180 days stays", "dcl-exports", f"{PREFIX}/report.txt", False, False, False),
    Case("vision cache 180 days stays", "dcl-cir", f"_vision_cache/{PREFIX}.json", False, False, False),
)


def client(args) -> Minio:
    url = urlsplit(args.endpoint)
    return Minio(
        url.netloc, credentials=StaticProvider(args.access_key, args.secret_key), secure=url.scheme == "https"
    )


def put(store: Minio, bucket: str, key: str, body: bytes) -> None:
    store.put_object(bucket, key, io.BytesIO(body), len(body))


def seed(args) -> int:
    env = dict(
        os.environ,
        DCL_MINIO_ENDPOINT=args.endpoint,
        MINIO_ROOT_USER=args.access_key,
        MINIO_ROOT_PASSWORD=args.secret_key,
        DCL_MINIO_ACCESS_KEY=args.access_key,
        DCL_MINIO_SECRET_KEY=args.secret_key,
        PYTHONPATH=str(REPO),
    )
    init = [sys.executable, str(REPO / "backend/devops/minio_init.py")]
    subprocess.run(init, env=env, check=True)  # noqa: S603 (fixed argv)
    store = client(args)
    for case in CASES:
        put(store, case.bucket, case.key, b"v1")
        if case.overwrite:
            put(store, case.bucket, case.key, b"v2")
        if case.delete:
            store.remove_object(case.bucket, case.key)
    seeded = datetime.now(UTC)
    print(f"seeded {len(CASES)} cases at {seeded:%Y-%m-%dT%H:%M:%SZ}; due by {due(seeded):%Y-%m-%dT%H:%MZ}")
    return 0


def due(seeded: datetime) -> datetime:
    return (seeded + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)


def expected_versions(case: Case) -> int:
    if case.expires:
        return 0 if case.delete else 1 if case.overwrite else 0
    return 2 if case.overwrite else 1


def check(args) -> int:
    store = client(args)
    now, states = datetime.now(UTC), []
    for case in CASES:
        found = [
            o
            for o in store.list_objects(case.bucket, prefix=case.key, include_version=True)
            if o.object_name == case.key
        ]
        seeded = min((o.last_modified for o in found), default=None)
        want = expected_versions(case)
        if len(found) == want:
            state = "ok"
        elif case.expires and len(found) > want:
            state = "PENDING" if seeded is None or now < due(seeded) + timedelta(hours=2) else "OVERDUE"
        else:
            state = "LOST"
        states.append(state)
        markers = sum(1 for o in found if o.is_delete_marker)
        print(f"{state:8} {case.name}: {len(found)} versions ({markers} markers), want {want}")
    print(f"checked at {now:%Y-%m-%dT%H:%M:%SZ}")
    if {"LOST", "OVERDUE"} & set(states):
        return 1
    return 2 if "PENDING" in states else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("seed", "check"))
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--access-key", required=True)
    parser.add_argument("--secret-key", required=True)
    args = parser.parse_args()
    return seed(args) if args.command == "seed" else check(args)


if __name__ == "__main__":
    sys.exit(main())
