"""M1 registry tables: sync_roots, drive_folders, drive_items, blobs, blob_derivations, jobs.

CHECK value lists are literal on purpose: a migration must keep meaning what it meant when
it was written. backend/tests/schema compares them with backend/postgres/enums.py.

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPTZ = sa.DateTime(timezone=True)
SHA256 = sa.CHAR(64)
UUID_PK_DEFAULT = sa.text("gen_random_uuid()")
FALSE = sa.text("false")


def check(column: str, *values: str) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=column)


SOURCE_ORIGIN = ("internal", "external_kept")


def upgrade() -> None:
    op.create_table(
        "sync_roots",
        sa.Column("root_name", sa.Text(), nullable=False),
        sa.Column("remote_drive_id", sa.Text(), nullable=False),
        sa.Column("remote_item_id", sa.Text(), nullable=False),
        sa.Column("delta_link", sa.Text()),
        sa.Column("next_link_checkpoint", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("auth_status", sa.Text(), nullable=False, server_default="OK"),
        sa.Column("subscription_id", sa.Text()),
        sa.Column("subscription_expires_at", TIMESTAMPTZ),
        sa.Column("cloud_allowed", sa.Boolean(), nullable=False, server_default=FALSE),
        sa.Column("default_source_origin", sa.Text(), nullable=False, server_default="internal"),
        sa.Column("last_full_crawl_at", TIMESTAMPTZ),
        sa.Column("last_delta_at", TIMESTAMPTZ),
        sa.PrimaryKeyConstraint("root_name"),
        sa.UniqueConstraint("remote_drive_id", "remote_item_id"),
        check("status", "ACTIVE", "CRAWLING", "RESYNCING", "UNREACHABLE", "PAUSED"),
        check("auth_status", "OK", "REAUTH_REQUIRED"),
        check("default_source_origin", *SOURCE_ORIGIN),
    )

    op.create_table(
        "blobs",
        sa.Column("sha256", SHA256, nullable=False),
        sa.Column("quick_xor_hash", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_detected", sa.Text()),
        sa.Column("minio_uri", sa.Text(), nullable=False),
        sa.Column("restricted", sa.Boolean(), nullable=False, server_default=FALSE),
        sa.Column("first_seen_at", TIMESTAMPTZ, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("sha256"),
    )
    op.create_index(op.f("ix_blobs_quick_xor_hash_size_bytes"), "blobs", ["quick_xor_hash", "size_bytes"])

    op.create_table(
        "drive_folders",
        sa.Column("folder_id", UUID(as_uuid=True), nullable=False, server_default=UUID_PK_DEFAULT),
        sa.Column("drive_id", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("parent_item_id", sa.Text()),
        sa.Column("root_name", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_junk", sa.Boolean(), nullable=False, server_default=FALSE),
        sa.Column("is_quarantine", sa.Boolean(), nullable=False, server_default=FALSE),
        sa.Column("source_origin_override", sa.Text()),
        sa.Column("path_cached", sa.Text()),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.PrimaryKeyConstraint("folder_id"),
        sa.UniqueConstraint("drive_id", "item_id"),
        sa.ForeignKeyConstraint(["root_name"], ["sync_roots.root_name"]),
        check("source_origin_override", *SOURCE_ORIGIN),
    )
    op.create_index(op.f("ix_drive_folders_parent_item_id"), "drive_folders", ["parent_item_id"])
    op.create_index(op.f("ix_drive_folders_root_name"), "drive_folders", ["root_name"])

    op.create_table(
        "drive_items",
        sa.Column("location_id", UUID(as_uuid=True), nullable=False, server_default=UUID_PK_DEFAULT),
        sa.Column("drive_id", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("root_name", sa.Text(), nullable=False),
        sa.Column("parent_item_id", sa.Text()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("extension", sa.Text()),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("quick_xor_hash", sa.Text()),
        sa.Column("etag", sa.Text()),
        sa.Column("web_url", sa.Text()),
        sa.Column("last_modified_at", TIMESTAMPTZ),
        sa.Column("created_at_source", TIMESTAMPTZ),
        sa.Column("path_cached", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="SEEN"),
        sa.Column("gate_reason", sa.Text()),
        sa.Column("detected_mime", sa.Text()),
        sa.Column("ext_mime_mismatch", sa.Boolean(), nullable=False, server_default=FALSE),
        sa.Column("blob_sha256", SHA256),
        sa.Column("resync_gen", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_seen_delta_at", TIMESTAMPTZ),
        sa.Column("deleted_at", TIMESTAMPTZ),
        sa.Column("error_last", sa.Text()),
        sa.PrimaryKeyConstraint("location_id"),
        sa.UniqueConstraint("drive_id", "item_id"),
        sa.ForeignKeyConstraint(["root_name"], ["sync_roots.root_name"]),
        sa.ForeignKeyConstraint(["blob_sha256"], ["blobs.sha256"]),
        check(
            "status",
            "SEEN",
            "SKIPPED_JUNK",
            "SKIPPED_EMPTY",
            "SKIPPED_SHORTCUT",
            "SKIPPED_UNSUPPORTED_PACKAGE",
            "QUARANTINED",
            "HELD_LARGE_FILE",
            "HELD_BY_SCOPE",
            "PENDING_DOWNLOAD",
            "DOWNLOAD_FAILED",
            "LANDED",
            "DELETED",
        ),
    )
    op.create_index(op.f("ix_drive_items_root_name"), "drive_items", ["root_name"])
    op.create_index(op.f("ix_drive_items_parent_item_id"), "drive_items", ["parent_item_id"])
    op.create_index(op.f("ix_drive_items_blob_sha256"), "drive_items", ["blob_sha256"])

    op.create_table(
        "blob_derivations",
        sa.Column("parent_blob_sha256", SHA256, nullable=False),
        sa.Column("member_path", sa.Text(), nullable=False),
        sa.Column("child_blob_sha256", SHA256),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("gate_reason", sa.Text()),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
        sa.PrimaryKeyConstraint("parent_blob_sha256", "member_path"),
        sa.ForeignKeyConstraint(["parent_blob_sha256"], ["blobs.sha256"]),
        sa.ForeignKeyConstraint(["child_blob_sha256"], ["blobs.sha256"]),
        check("kind", "archive_member", "pdf_attachment", "embedded_object", "redacted_copy", "replacement_upload"),
    )
    op.create_index(op.f("ix_blob_derivations_child_blob_sha256"), "blob_derivations", ["child_blob_sha256"])

    op.create_table(
        "jobs",
        sa.Column("job_id", UUID(as_uuid=True), nullable=False, server_default=UUID_PK_DEFAULT),
        sa.Column("job_key", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("blob_sha256", SHA256),
        sa.Column("doc_id", UUID(as_uuid=True)),
        sa.Column("parser_version", sa.Integer()),
        sa.Column("pipeline_version", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("celery_task_id", sa.Text()),
        sa.Column("worker", sa.Text()),
        sa.Column("started_at", TIMESTAMPTZ),
        sa.Column("finished_at", TIMESTAMPTZ),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("peak_rss_mb", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("job_key"),
        check("stage", "download", "dispatch", "parse", "enrich", "index", "resume", "reembed", "translate"),
        check("status", "queued", "running", "done", "failed"),
    )
    op.create_index(op.f("ix_jobs_blob_sha256"), "jobs", ["blob_sha256"])
    op.create_index(op.f("ix_jobs_doc_id"), "jobs", ["doc_id"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("blob_derivations")
    op.drop_table("drive_items")
    op.drop_table("drive_folders")
    op.drop_table("blobs")
    op.drop_table("sync_roots")
