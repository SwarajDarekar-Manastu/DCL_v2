"""Tier 4 on landed blobs (file 02 §4): real type, extension mismatch, secret scan, quarantine.

Runs after a download and before dispatch. An item is inspected once: ``detected_mime`` is set.
A secret hit quarantines every location holding that content, moves the blob to
``dcl-raw/_restricted/{sha256}`` (never sent to Gemini, never indexed) and raises a HARD
``SENSITIVE_CONTENT`` flag per location with a redacted preview only.

CLI: ``python -m backend.sync.inspect [--limit N]`` inspects every LANDED item not yet inspected.
"""

import io
import logging
import uuid
import zipfile
from dataclasses import dataclass

from minio import Minio
from minio.commonconfig import CopySource
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import Flag, FlagAnchor, SensitiveEvidence
from backend.dispatcher.type_resolution import HEAD_BYTES, resolve_type
from backend.postgres.enums import DriveItemStatus, FlagSeverity, FlagType
from backend.postgres.models import Blob, DriveItem
from backend.review.flags import upsert_location_flag
from backend.storage.minio import RAW, parse_uri, uri
from backend.sync.gate import SECRET_VERDICT, scan_secrets, should_scan

log = logging.getLogger(__name__)

SECRET_SCAN_MAX_BYTES = 5 * 1024 * 1024
RESTRICTED_PREFIX = "_restricted/"


class RangeReader(io.RawIOBase):
    """Seekable read-only view of one object through ranged GETs (for a ZIP central directory)."""

    def __init__(self, minio: Minio, bucket: str, key: str, size: int) -> None:
        self._minio, self._bucket, self._key, self._size, self._pos = minio, bucket, key, size, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._size}[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def read(self, size: int = -1) -> bytes:
        if self._pos >= self._size:
            return b""
        length = self._size - self._pos if size < 0 else min(size, self._size - self._pos)
        response = self._minio.get_object(self._bucket, self._key, offset=self._pos, length=length)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        self._pos += len(data)
        return data


@dataclass(frozen=True)
class Inspection:
    location_id: uuid.UUID
    detected_mime: str
    ext_mismatch: bool
    secret_hits: int


def _read(minio: Minio, key: str, length: int) -> bytes:
    response = minio.get_object(RAW, key, offset=0, length=length)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _zip_names(minio: Minio, key: str, size: int) -> list[str] | None:
    try:
        with zipfile.ZipFile(RangeReader(minio, RAW, key, size)) as archive:
            return archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return None


def _restrict(session: Session, minio: Minio, blob: Blob) -> None:
    """Move the blob under ``_restricted/``; every location holding it is quarantined by the caller."""
    _, key = parse_uri(blob.minio_uri)
    target = f"{RESTRICTED_PREFIX}{blob.sha256}"
    if key != target:
        minio.copy_object(RAW, target, CopySource(RAW, key))
        stat = minio.stat_object(RAW, key)
        minio.remove_object(RAW, key, version_id=stat.version_id)
    blob.minio_uri, blob.restricted = uri(RAW, target), True


def inspect_item(session: Session, minio: Minio, location_id: uuid.UUID) -> Inspection | None:
    item = session.get(DriveItem, location_id)
    if item is None or item.status != DriveItemStatus.LANDED or item.detected_mime is not None:
        return None
    blob = session.get(Blob, item.blob_sha256)
    _, key = parse_uri(blob.minio_uri)
    head = _read(minio, key, HEAD_BYTES)
    zip_names = _zip_names(minio, key, blob.size_bytes) if head.startswith(b"PK\x03\x04") else None
    resolved = resolve_type(head, item.name, zip_names)
    item.detected_mime, item.ext_mime_mismatch = resolved.mime, resolved.ext_mismatch

    hits = []
    if should_scan(item.name) and blob.size_bytes <= SECRET_SCAN_MAX_BYTES:
        hits = scan_secrets(_read(minio, key, blob.size_bytes).decode("utf-8", errors="replace"))
    if hits:
        _restrict(session, minio, blob)
        first = hits[0]
        flag = Flag(
            flag_type=FlagType.SENSITIVE_CONTENT,
            severity=FlagSeverity.HARD,
            anchor=FlagAnchor(line=first.line),
            evidence=SensitiveEvidence(
                pattern=", ".join(sorted({h.pattern for h in hits})),
                redacted_preview=first.redacted_preview,
                line=first.line,
            ),
        )
        holders = session.scalars(select(DriveItem).where(DriveItem.blob_sha256 == blob.sha256))
        for holder in holders:
            holder.status, holder.gate_reason = SECRET_VERDICT.status, SECRET_VERDICT.gate_reason
            holder.detected_mime = holder.detected_mime or resolved.mime
            upsert_location_flag(session, holder.location_id, flag)
        log.warning("Tier 4: secret pattern in %s; blob restricted, locations quarantined", item.name)
    session.flush()
    return Inspection(location_id, resolved.mime, resolved.ext_mismatch, len(hits))


def pending_inspection(session: Session, limit: int | None = None) -> list[uuid.UUID]:
    query = select(DriveItem.location_id).where(
        DriveItem.status == DriveItemStatus.LANDED, DriveItem.detected_mime.is_(None)
    )
    return list(session.scalars(query.limit(limit) if limit else query))


def main(argv: list[str]) -> int:
    import argparse
    import os
    from pathlib import Path

    from sqlalchemy import create_engine

    from backend.config import get_settings, load_settings
    from backend.postgres.session import normalize_url
    from backend.storage.minio import client_from_settings

    parser = argparse.ArgumentParser(prog="python -m backend.sync.inspect")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    settings = load_settings(Path(args.env_file)) if args.env_file else get_settings()
    minio = client_from_settings(settings)
    engine = create_engine(
        normalize_url(os.environ.get("DCL_DATABASE_URL") or settings.stack_database_url().get_secret_value())
    )
    mismatches = secrets = inspected = 0
    with Session(engine, expire_on_commit=False) as session:
        for location_id in pending_inspection(session, args.limit):
            result = inspect_item(session, minio, location_id)
            session.commit()
            if result is None:
                continue
            inspected += 1
            mismatches += result.ext_mismatch
            secrets += result.secret_hits > 0
    print(f"inspected {inspected}: {mismatches} extension/content mismatches, {secrets} with secrets")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
