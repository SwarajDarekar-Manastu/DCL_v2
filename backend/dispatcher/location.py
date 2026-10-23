"""Where a document's primary content lives in OneDrive, also for derived blobs (file 05 blob_derivations).

A blob held by a live drive item is located by that item. A blob that only exists as an embedded object,
archive member or attachment inherits its parent's location: same root and folder, its own member name,
the path ``parent path/member path``. Routes read ``root_name``, ``parent_item_id``, ``name``,
``extension`` and ``path_cached`` from here instead of querying ``drive_items``.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import BlobDerivation, DriveItem

MAX_DEPTH = 8  # a member of a member of …: deeper nesting is refused, never looped


@dataclass(frozen=True)
class Location:
    root_name: str
    parent_item_id: str | None
    name: str
    extension: str | None
    path_cached: str | None
    member_path: str | None = None  # set for a derived blob


def _extension(name: str) -> str | None:
    suffix = PurePosixPath(name).suffix
    return suffix.casefold() or None


def primary_location(session: Session, blob_sha256: str, _depth: int = 0) -> Location | None:
    item = session.scalar(
        select(DriveItem)
        .where(DriveItem.blob_sha256 == blob_sha256, DriveItem.status != DriveItemStatus.DELETED)
        .order_by(DriveItem.path_cached)
        .limit(1)
    )
    if item is not None:
        return Location(item.root_name, item.parent_item_id, item.name, item.extension, item.path_cached)
    if _depth >= MAX_DEPTH:
        return None
    link = session.scalar(
        select(BlobDerivation)
        .where(BlobDerivation.child_blob_sha256 == blob_sha256)
        .order_by(BlobDerivation.parent_blob_sha256, BlobDerivation.member_path)
        .limit(1)
    )
    if link is None:
        return None
    parent = primary_location(session, link.parent_blob_sha256, _depth + 1)
    if parent is None:
        return None
    name = PurePosixPath(link.member_path).name
    path = f"{parent.path_cached}/{link.member_path}" if parent.path_cached else None
    return Location(parent.root_name, parent.parent_item_id, name, _extension(name), path, link.member_path)
