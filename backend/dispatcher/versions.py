"""Versions of a file (file 02 §5.1; decided by the user on 2026-10-27).

A file changed in OneDrive lands as new content, so it becomes a new document; its location remembers the
old bytes (``drive_items.previous_blob_sha256``, sync/downloader.py). Once the new version is searchable,
``dispatcher/routing.py replace_older`` marks the old one SUPERSEDED with ``metadata_sources.replaced_by``.

``purge_replaced`` then removes everything of such a version: its index rows (indexing/withdraw.py), its
images, its processing output (CIR) and its raw file, unless another document or a live OneDrive location
still uses those bytes; its open questions are closed. One history row stays: the documents row with its
title, dates, status and the SUPERSEDES relation to the version that replaced it. A document SUPERSEDED for
another reason (a newer revision of a standard, a reviewer's "superseded") keeps its data: it can still be
searched with ``include_superseded``.

It runs with the reconciler (every 30 minutes) and is idempotent: a run that stops half way is finished by
the next one (``purged_at`` is set last).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from backend.indexing.withdraw import withdraw
from backend.postgres.enums import DocumentStatus, DriveItemStatus, FlagStatus
from backend.postgres.models import (
    Asset,
    Blob,
    BlobDerivation,
    Document,
    DocumentSource,
    DriveItem,
    ReviewFlag,
    TelemetryRun,
)
from backend.storage.minio import BucketStore, parse_uri

OPEN = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)


@dataclass(frozen=True)
class Stores:
    raw: BucketStore
    cir: BucketStore
    assets: BucketStore


def purge_replaced(session: Session, stores: Stores, now: datetime | None = None) -> int:
    """Remove every version a newer version of its file replaced; returns how many."""
    now = now or datetime.now(UTC)
    replaced = [
        d
        for d in session.scalars(select(Document).where(Document.status == DocumentStatus.SUPERSEDED))
        if (d.metadata_sources or {}).get("replaced_by") and not (d.metadata_sources or {}).get("purged_at")
    ]
    for document in replaced:
        withdraw(session, document)
        for flag in session.scalars(
            select(ReviewFlag).where(ReviewFlag.doc_id == document.doc_id, ReviewFlag.status.in_(OPEN))
        ):
            flag.status, flag.resolved_by, flag.resolved_at = FlagStatus.AUTO_RESOLVED, "superseded", now
        shas = list(
            session.scalars(
                select(DocumentSource.blob_sha256).where(DocumentSource.doc_id == document.doc_id)
            )
        )
        session.execute(delete(DocumentSource).where(DocumentSource.doc_id == document.doc_id))
        session.flush()
        for sha in shas:
            if not _still_used(session, sha):
                _remove_blob(session, stores, sha)
        document.metadata_sources = {**(document.metadata_sources or {}), "purged_at": now.isoformat()}
    session.flush()
    return len(replaced)


def _still_used(session: Session, sha: str) -> bool:
    """Another document's source, a live location, an archive link or a run still needs these bytes."""
    checks = (
        select(DocumentSource.doc_id).where(DocumentSource.blob_sha256 == sha),
        select(DriveItem.location_id).where(
            DriveItem.blob_sha256 == sha, DriveItem.status != DriveItemStatus.DELETED
        ),
        select(BlobDerivation.child_blob_sha256).where(
            (BlobDerivation.parent_blob_sha256 == sha) | (BlobDerivation.child_blob_sha256 == sha)
        ),
        select(TelemetryRun.run_uuid).where(TelemetryRun.blob_sha256 == sha),
    )
    return any(session.scalar(check.limit(1)) is not None for check in checks)


def _remove_blob(session: Session, stores: Stores, sha: str) -> None:
    """The bytes' images, processing output and raw file, then their rows. A deleted location that pointed at
    them forgets them, so a restored file is fetched again."""
    for asset in session.scalars(select(Asset).where(Asset.blob_sha256 == sha)).all():
        stores.assets.delete(parse_uri(asset.minio_uri)[1])
        session.delete(asset)
    stores.cir.delete_prefix(f"{sha}/")
    session.execute(
        update(DriveItem)
        .where(DriveItem.blob_sha256 == sha, DriveItem.status == DriveItemStatus.DELETED)
        .values(blob_sha256=None)
    )
    blob = session.get(Blob, sha)
    if blob is not None:
        if blob.minio_uri:
            stores.raw.delete(parse_uri(blob.minio_uri)[1])
        session.delete(blob)
    session.flush()
