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


def find_known_blob(session: Session, quick_xor_hash: str | None, size_bytes: int | None) -> str | None:
    if not quick_xor_hash or size_bytes is None:
        return None
    return session.scalar(
        select(Blob.sha256)
        .where(Blob.quick_xor_hash == quick_xor_hash, Blob.size_bytes == size_bytes)
        .limit(1)
    )


def _land(session: Session, item: DriveItem, sha256: str) -> None:
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
    item = session.get(DriveItem, location_id, with_for_update=True)
    if item is None:
        raise LookupError(f"no drive item {location_id}")

    known = find_known_blob(session, item.quick_xor_hash, item.size_bytes)
    if known is not None:
        _land(session, item, known)
        return Landed(location_id, known, downloaded=False, new_blob=False)

    temp_key = f"{INCOMING_PREFIX}{uuid.uuid4()}"
    reader = _stream_to(graph, minio, item, temp_key, content_http)
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
                    "original_name": item.name,
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
        minio.remove_object(RAW, temp_key)
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
        minio.put_object(RAW, key, reader, length=-1, part_size=PART_BYTES)
    return reader
