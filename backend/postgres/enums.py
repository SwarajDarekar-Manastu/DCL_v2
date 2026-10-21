"""Every lifecycle or kind column is ``text`` with a named CHECK built from one StrEnum.

File 05 marks these columns with ✓. No native PostgreSQL enum types are used.
Migrations hard-code the value lists they create; the schema tests compare the
CHECK in the database with the enums below, so an enum edit without a migration
fails CI.
"""

from enum import StrEnum

from sqlalchemy import CheckConstraint


def enum_check(column: str, enum: type[StrEnum]) -> CheckConstraint:
    """Named CHECK ``ck_<table>_<column>`` allowing exactly the enum's values (NULL passes)."""
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=column)


class SyncRootStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CRAWLING = "CRAWLING"
    RESYNCING = "RESYNCING"
    UNREACHABLE = "UNREACHABLE"
    PAUSED = "PAUSED"


class AuthStatus(StrEnum):
    OK = "OK"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"


class SourceOrigin(StrEnum):
    """Origin stored on registry rows and documents. ``web_live`` exists only at answer time."""

    INTERNAL = "internal"
    EXTERNAL_KEPT = "external_kept"


class DriveItemStatus(StrEnum):
    SEEN = "SEEN"
    SKIPPED_JUNK = "SKIPPED_JUNK"
    SKIPPED_EMPTY = "SKIPPED_EMPTY"
    SKIPPED_SHORTCUT = "SKIPPED_SHORTCUT"
    SKIPPED_UNSUPPORTED_PACKAGE = "SKIPPED_UNSUPPORTED_PACKAGE"
    QUARANTINED = "QUARANTINED"
    HELD_LARGE_FILE = "HELD_LARGE_FILE"
    HELD_BY_SCOPE = "HELD_BY_SCOPE"
    PENDING_DOWNLOAD = "PENDING_DOWNLOAD"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    LANDED = "LANDED"
    DELETED = "DELETED"


class BlobDerivationKind(StrEnum):
    ARCHIVE_MEMBER = "archive_member"
    PDF_ATTACHMENT = "pdf_attachment"
    EMBEDDED_OBJECT = "embedded_object"
    REDACTED_COPY = "redacted_copy"
    REPLACEMENT_UPLOAD = "replacement_upload"


class JobStage(StrEnum):
    DOWNLOAD = "download"
    DISPATCH = "dispatch"
    PARSE = "parse"
    ENRICH = "enrich"
    INDEX = "index"
    RESUME = "resume"
    REEMBED = "reembed"
    TRANSLATE = "translate"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
