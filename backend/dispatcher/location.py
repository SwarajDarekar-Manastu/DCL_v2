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
    web_url: str | None = None  # the OneDrive link (the parent's for a derived blob)


def _extension(name: str) -> str | None:
    suffix = PurePosixPath(name).suffix
    return suffix.casefold() or None


def _shared_folders(path: str | None, anchor: str) -> int:
    if not path:
        return 0
    shared = 0
    for a, b in zip(PurePosixPath(path).parent.parts, PurePosixPath(anchor).parent.parts, strict=False):
        if a != b:
            break
        shared += 1
    return shared


def location_near(session: Session, blob_sha256: str, anchor_path: str | None) -> Location | None:
    """``primary_location`` for a file that belongs to a document with other files: when the same bytes sit
    in several folders (test plans copy their sections), the copy sharing the most folders with
    ``anchor_path``, the document's own file, wins, so all of a document's files come from one place."""
    if anchor_path:
        items = session.scalars(
            select(DriveItem)
            .where(DriveItem.blob_sha256 == blob_sha256, DriveItem.status != DriveItemStatus.DELETED)
            .order_by(DriveItem.path_cached)
        ).all()
        if len(items) > 1:
            item = max(items, key=lambda i: _shared_folders(i.path_cached, anchor_path))
            return Location(
                item.root_name,
                item.parent_item_id,
                item.name,
                item.extension,
                item.path_cached,
                None,
                item.web_url,
            )
    return primary_location(session, blob_sha256)


def primary_location(session: Session, blob_sha256: str, _depth: int = 0) -> Location | None:
    item = session.scalar(
        select(DriveItem)
        .where(DriveItem.blob_sha256 == blob_sha256, DriveItem.status != DriveItemStatus.DELETED)
        .order_by(DriveItem.path_cached)
        .limit(1)
    )
    if item is not None:
        return Location(
            item.root_name,
            item.parent_item_id,
            item.name,
            item.extension,
            item.path_cached,
            None,
            item.web_url,
        )
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
    return Location(
        parent.root_name,
        parent.parent_item_id,
        name,
        _extension(name),
        path,
        link.member_path,
        parent.web_url,
    )
