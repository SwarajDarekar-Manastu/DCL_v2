"""Download one accepted item into MinIO (file 02 §6) and link it to a content-addressed blob.

1. Zero-download link: ``blobs`` already holds this ``(quick_xor_hash, size_bytes)``.
2. ``GET /content`` answers 302; the pre-authenticated target is fetched without the Graph token.
3. Stream in 8 MB chunks to ``dcl-raw/_incoming/{uuid}`` computing SHA-256 and quickXorHash.
4. Verify size and quickXorHash against Graph; on mismatch delete the temp object and raise.
5. Known SHA-256 → link. New → server-side copy to ``{sha[0:2]}/{sha[2:4]}/{sha}`` with object
   metadata, then ``INSERT … ON CONFLICT DO NOTHING`` (parallel downloads of new content make
   one blob). The item becomes ``LANDED``.

The caller owns the transaction and decides about dispatch (``processing.scope``).
"""

import base64
import hashlib
import io
import uuid
from dataclasses import dataclass
from urllib.parse import quote

import httpx
import quickxorhash
from minio import Minio
from minio.commonconfig import REPLACE, CopySource
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import Blob, DriveItem
from backend.storage.minio import RAW, raw_key, uri
from backend.sync.graph_client import GraphClient

CHUNK_BYTES = 8 * 1024 * 1024
PART_BYTES = 16 * 1024 * 1024
INCOMING_PREFIX = "_incoming/"


class DownloadMismatch(RuntimeError):
    """The bytes received do not match Graph's size or quickXorHash (truncated or changed)."""


@dataclass(frozen=True)
class Landed:
    location_id: uuid.UUID
    blob_sha256: str
    downloaded: bool
    new_blob: bool


class HashingReader(io.RawIOBase):
    """A file-like over an iterator of byte chunks that hashes everything it hands out."""

    def __init__(self, chunks) -> None:
        self._chunks = iter(chunks)
        self._buffer = b""
        self.sha256 = hashlib.sha256()
        self.quick_xor = quickxorhash.quickxorhash()
        self.size = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        while size < 0 or len(self._buffer) < size:
            chunk = next(self._chunks, None)
            if chunk is None:
                break
            self._buffer += chunk
        if size < 0:
            out, self._buffer = self._buffer, b""
        else:
            out, self._buffer = self._buffer[:size], self._buffer[size:]
        self.sha256.update(out)
        self.quick_xor.update(out)
        self.size += len(out)
        return out

    def readinto(self, target) -> int:
        data = self.read(len(target))
        target[: len(data)] = data
        return len(data)

    @property
    def quick_xor_b64(self) -> str:
        return base64.b64encode(self.quick_xor.digest()).decode()


def ascii_metadata(value: str) -> str:
    """S3 object metadata must be US-ASCII: non-ASCII characters are percent-encoded (RFC 3986)."""
    return quote(value, safe=" !#$&'()*+,-./:;=?@[]^_`{|}~")


def find_known_blob(session: Session, quick_xor_hash: str | None, size_bytes: int | None) -> str | None:
    if not quick_xor_hash or size_bytes is None:
        return None
    return session.scalar(
        select(Blob.sha256)
        .where(Blob.quick_xor_hash == quick_xor_hash, Blob.size_bytes == size_bytes)
        .limit(1)
    )


def _land(session: Session, item: DriveItem, sha256: str) -> None:
    if item.blob_sha256 is not None and item.blob_sha256 != sha256 and item.previous_blob_sha256 is None:
        item.previous_blob_sha256 = (
            item.blob_sha256
        )  # modified in place; a pending value is never overwritten
    if item.blob_sha256 != sha256:  # new bytes are inspected again (type check, secret scan): inspect.py
        item.detected_mime, item.ext_mime_mismatch = None, False
    item.blob_sha256 = sha256
    item.status = DriveItemStatus.LANDED
    item.error_last = None


def land_item(
    session: Session,
    graph: GraphClient,
    minio: Minio,
    location_id: uuid.UUID,
    content_http: httpx.Client,
) -> Landed:
    item = session.get(DriveItem, location_id, with_for_update=True, populate_existing=True)
    if item is None:
        raise LookupError(f"no drive item {location_id}")
    if item.status != DriveItemStatus.PENDING_DOWNLOAD:  # another worker landed it during the lock wait
        return Landed(location_id, item.blob_sha256, downloaded=False, new_blob=False)

    known = find_known_blob(session, item.quick_xor_hash, item.size_bytes)
    if known is not None:
        _land(session, item, known)
        return Landed(location_id, known, downloaded=False, new_blob=False)

    temp_key = f"{INCOMING_PREFIX}{uuid.uuid4()}"
    reader, temp_version = _stream_to(graph, minio, item, temp_key, content_http)
    try:
        if item.size_bytes is not None and reader.size != item.size_bytes:
            raise DownloadMismatch(f"size {reader.size} != Graph size {item.size_bytes}")
        if item.quick_xor_hash and reader.quick_xor_b64 != item.quick_xor_hash:
            raise DownloadMismatch("quickXorHash differs from Graph's value")
        sha256 = reader.sha256.hexdigest()
        exists = session.scalar(select(Blob.sha256).where(Blob.sha256 == sha256)) is not None
        if not exists:
            minio.copy_object(
                RAW,
                raw_key(sha256),
                CopySource(RAW, temp_key),
                metadata={
                    "original_name": ascii_metadata(item.name),
                    "first_location_id": str(item.location_id),
                    "source": "onedrive",
                },
                metadata_directive=REPLACE,
            )
            inserted = session.execute(
                insert(Blob)
                .values(
                    sha256=sha256,
                    quick_xor_hash=reader.quick_xor_b64,
                    size_bytes=reader.size,
                    minio_uri=uri(RAW, raw_key(sha256)),
                )
                .on_conflict_do_nothing(index_elements=["sha256"])
            )
            exists = inserted.rowcount == 0
    finally:
        # dcl-raw is versioned: removing the exact version deletes the temp bytes instead of hiding them
        minio.remove_object(RAW, temp_key, version_id=temp_version)
    _land(session, item, sha256)
    return Landed(location_id, sha256, downloaded=True, new_blob=not exists)


def _stream_to(graph: GraphClient, minio: Minio, item: DriveItem, key: str, content_http: httpx.Client):
    response = graph.get(f"/drives/{item.drive_id}/items/{item.item_id}/content")
    if response.status_code not in (301, 302, 303, 307, 308):
        response.raise_for_status()
        raise RuntimeError(f"expected a redirect from /content, got HTTP {response.status_code}")
    with content_http.stream("GET", response.headers["Location"]) as content:
        content.raise_for_status()
        reader = HashingReader(content.iter_bytes(CHUNK_BYTES))
        written = minio.put_object(RAW, key, reader, length=-1, part_size=PART_BYTES)
    return reader, written.version_id


def main(argv: list[str]) -> int:
    """Host-side landing of PENDING_DOWNLOAD items, optionally only inside given folder subtrees."""
    import argparse
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine

    from backend.celery_redis.tasks_sync import Outcome, download_one
    from backend.config import get_settings, load_settings
    from backend.postgres.session import normalize_url
    from backend.storage.minio import client_from_settings
    from backend.sync.auth import GraphAuthConfig, TokenProvider
    from backend.sync.export_blobs import folder_paths, items_under

    parser = argparse.ArgumentParser(prog="python -m backend.sync.downloader")
    parser.add_argument(
        "--folder-id", action="append", default=[], help="only items inside this folder subtree"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4, help="parallel downloads (file 02 §3.4 allows 8)")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    from pathlib import Path

    settings = load_settings(Path(args.env_file)) if args.env_file else get_settings()
    engine = create_engine(
        normalize_url(os.environ.get("DCL_DATABASE_URL") or settings.stack_database_url().get_secret_value())
    )
    tokens = TokenProvider.create(GraphAuthConfig.from_settings(settings))
    minio = client_from_settings(settings)
    counts: dict[str, int] = {}
    with Session(engine, expire_on_commit=False) as session:
        if args.folder_id:
            ids = [
                item.location_id
                for path in folder_paths(session, args.folder_id).values()
                for item in items_under(session, path, DriveItemStatus.PENDING_DOWNLOAD)
            ]
        else:
            ids = list(
                session.scalars(
                    select(DriveItem.location_id).where(DriveItem.status == DriveItemStatus.PENDING_DOWNLOAD)
                )
            )
    selected = ids[: args.limit]
    lock = threading.Lock()

    def land(location_id) -> None:
        with Session(engine, expire_on_commit=False) as own, httpx.Client(timeout=120.0) as own_http:
            outcome = Outcome.RETRY
            try:
                for attempt in range(3):
                    outcome = download_one(own, graph, minio, own_http, location_id, attempt)
                    if outcome != Outcome.RETRY:
                        break
            except Exception as exc:  # one bad item must not stop the run; it stays PENDING_DOWNLOAD
                own.rollback()
                outcome = "error"
                print(f"  error on {location_id}: {type(exc).__name__}: {exc}", flush=True)
        with lock:
            counts[outcome] = counts.get(outcome, 0) + 1
            done = sum(counts.values())
            if done % 100 == 0:
                print(f"  {done}/{len(selected)} {counts}", flush=True)

    with GraphClient(tokens.access_token) as graph, ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(land, selected))
    print(f"{len(ids[: args.limit])} items: {counts}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
