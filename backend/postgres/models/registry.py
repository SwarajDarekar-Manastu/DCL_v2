"""Registry tables written in M1 (file 05 §4.1): what exists in OneDrive and MinIO, and the job ledger.

Identity of items and folders is ``(drive_id, item_id)``; other tables reference the
surrogate keys. ``parent_item_id`` deliberately has no FK (children can arrive before
their parent in a delta feed). Document state never lives here (it is on ``documents``).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.postgres.base import Base, Tier, tier
from backend.postgres.enums import (
    AuthStatus,
    BlobDerivationKind,
    DriveItemStatus,
    JobStage,
    JobStatus,
    SourceOrigin,
    SyncRootStatus,
    enum_check,
)

TIMESTAMPTZ = DateTime(timezone=True)
SHA256 = CHAR(64)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


class SyncRoot(Base):
    """One row per shared folder that is crawled."""

    __tablename__ = "sync_roots"
    __table_args__ = (
        UniqueConstraint("remote_drive_id", "remote_item_id"),
        enum_check("status", SyncRootStatus),
        enum_check("auth_status", AuthStatus),
        enum_check("default_source_origin", SourceOrigin),
        {"info": tier(Tier.REGISTRY)},
    )

    root_name: Mapped[str] = mapped_column(Text, primary_key=True)
    remote_drive_id: Mapped[str] = mapped_column(Text)
    remote_item_id: Mapped[str] = mapped_column(Text)
    delta_link: Mapped[str | None] = mapped_column(Text)
    next_link_checkpoint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=SyncRootStatus.ACTIVE.value)
    auth_status: Mapped[str] = mapped_column(Text, server_default=AuthStatus.OK.value)
    subscription_id: Mapped[str | None] = mapped_column(Text)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    cloud_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    default_source_origin: Mapped[str] = mapped_column(Text, server_default=SourceOrigin.INTERNAL.value)
    last_full_crawl_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    last_delta_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class DriveFolder(Base):
    """Folder tree: the only source of paths and of O(1) junk/quarantine decisions."""

    __tablename__ = "drive_folders"
    __table_args__ = (
        UniqueConstraint("drive_id", "item_id"),
        enum_check("source_origin_override", SourceOrigin),
        {"info": tier(Tier.REGISTRY)},
    )

    folder_id: Mapped[uuid.UUID] = _uuid_pk()
    drive_id: Mapped[str] = mapped_column(Text)
    item_id: Mapped[str] = mapped_column(Text)
    parent_item_id: Mapped[str | None] = mapped_column(Text, index=True)
    root_name: Mapped[str] = mapped_column(Text, ForeignKey("sync_roots.root_name"), index=True)
    name: Mapped[str] = mapped_column(Text)
    is_junk: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_quarantine: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    source_origin_override: Mapped[str | None] = mapped_column(Text)
    path_cached: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class DriveItem(Base):
    """One OneDrive file item: a location of content. Phase 1 state only."""

    __tablename__ = "drive_items"
    __table_args__ = (
        UniqueConstraint("drive_id", "item_id"),
        enum_check("status", DriveItemStatus),
        Index(
            "ix_drive_items_previous_blob_sha256",
            "previous_blob_sha256",
            postgresql_where=text("previous_blob_sha256 IS NOT NULL"),
        ),
        {"info": tier(Tier.REGISTRY)},
    )

    location_id: Mapped[uuid.UUID] = _uuid_pk()
    drive_id: Mapped[str] = mapped_column(Text)
    item_id: Mapped[str] = mapped_column(Text)
    root_name: Mapped[str] = mapped_column(Text, ForeignKey("sync_roots.root_name"), index=True)
    parent_item_id: Mapped[str | None] = mapped_column(Text, index=True)
    name: Mapped[str] = mapped_column(Text)
    extension: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    quick_xor_hash: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    web_url: Mapped[str | None] = mapped_column(Text)
    last_modified_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at_source: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    path_cached: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=DriveItemStatus.SEEN.value)
    gate_reason: Mapped[str | None] = mapped_column(Text)
    detected_mime: Mapped[str | None] = mapped_column(Text)
    ext_mime_mismatch: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    blob_sha256: Mapped[str | None] = mapped_column(SHA256, ForeignKey("blobs.sha256"), index=True)
    previous_blob_sha256: Mapped[str | None] = mapped_column(SHA256)  # in-place replacement, pending dispatch
    resync_gen: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_seen_delta_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    error_last: Mapped[str | None] = mapped_column(Text)


class Blob(Base):
    """Content-addressed object in MinIO. Inserted with ON CONFLICT DO NOTHING."""

    __tablename__ = "blobs"
    __table_args__ = (
        Index(None, "quick_xor_hash", "size_bytes"),
        {"info": tier(Tier.REGISTRY)},
    )

    sha256: Mapped[str] = mapped_column(SHA256, primary_key=True)
    quick_xor_hash: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_detected: Mapped[str | None] = mapped_column(Text)
    minio_uri: Mapped[str] = mapped_column(Text)
    restricted: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    first_seen_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("now()"))


class BlobDerivation(Base):
    """Parent-to-child blob link: archive member, attachment, embedded object, redacted or replacement copy.

    ``child_blob_sha256`` is NULL for archive members the gate skipped (``gate_reason`` says why).
    """

    __tablename__ = "blob_derivations"
    __table_args__ = (
        enum_check("kind", BlobDerivationKind),
        {"info": tier(Tier.REGISTRY)},
    )

    parent_blob_sha256: Mapped[str] = mapped_column(SHA256, ForeignKey("blobs.sha256"), primary_key=True)
    member_path: Mapped[str] = mapped_column(Text, primary_key=True)
    child_blob_sha256: Mapped[str | None] = mapped_column(SHA256, ForeignKey("blobs.sha256"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    gate_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, server_default="system")


class Job(Base):
    """Idempotency ledger and task history.

    ``job_key`` = ``{stage}:{blob_sha256 or doc_id}:v{parser_version}.{pipeline_version}``, never a
    location id. ``blob_sha256`` and ``doc_id`` are indexed but carry no FK: the ledger must not
    block the blob purge, and job rows are kept independently of document lifecycles.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("stage", JobStage),
        enum_check("status", JobStatus),
        {"info": tier(Tier.REGISTRY)},
    )

    job_id: Mapped[uuid.UUID] = _uuid_pk()
    job_key: Mapped[str] = mapped_column(Text, unique=True)
    stage: Mapped[str] = mapped_column(Text)
    blob_sha256: Mapped[str | None] = mapped_column(SHA256, index=True)
    doc_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    parser_version: Mapped[int | None] = mapped_column(Integer)
    pipeline_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default=JobStatus.QUEUED.value)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    celery_task_id: Mapped[str | None] = mapped_column(Text)
    worker: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    peak_rss_mb: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    @staticmethod
    def key_for(
        stage: JobStage,
        parser_version: int,
        pipeline_version: int,
        *,
        blob_sha256: str | None = None,
        doc_id: uuid.UUID | None = None,
    ) -> str:
        """``{stage}:{blob_sha256 or doc_id}:v{parser_version}.{pipeline_version}`` (file 02 §7.1).

        Content, not location: a second copy of known content is the same job.
        """
        if (blob_sha256 is None) == (doc_id is None):
            raise ValueError("a job key names exactly one of blob_sha256 or doc_id")
        return f"{stage}:{blob_sha256 or doc_id}:v{parser_version}.{pipeline_version}"
