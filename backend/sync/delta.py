"""Metadata crawl and incremental delta per root (file 02 §2, §3.1, §3.1a, §3.2, §5.1).

One run per root: ``GET /drives/{d}/items/{root}/delta`` (or the stored link), page by page.
Every page is upserted and committed together with ``next_link_checkpoint``, so a crash resumes
at the next page; the new ``delta_link`` is stored only after the last page and the final pass.

Paths are never taken from Graph: after the last page the folder tree of the root is walked
(the root's own name first) and ``path_cached`` is recomputed. The gate (tiers 1–3, read from
``pipeline_config``) and the download scope then decide every item that is new or changed
(``SEEN``) and every item under a folder whose path changed (rename, move, quarantine in/out).
Accepted items whose blob still matches stay ``LANDED``; others become ``PENDING_DOWNLOAD``.

Nothing is downloaded here, and nothing is removed: a deleted facet marks the row deleted.

CLI (operator, after the device-code sign-in): ``python -m backend.sync.delta crawl [--root NAME]``.
"""

import logging
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.config import Settings, get_settings, load_settings
from backend.dispatcher.type_resolution import extension_of
from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus, SyncRootStatus
from backend.postgres.models import Blob, DriveFolder, DriveItem, SyncRoot
from backend.sync.gate import GateConfig, GateInput, folder_flags, gate_item
from backend.sync.graph_client import GraphClient
from backend.sync.scope import HELD_BY_DOWNLOAD_SCOPE, in_scope

log = logging.getLogger(__name__)

DELTA_SELECT = (
    "id,name,size,file,folder,parentReference,eTag,lastModifiedDateTime,createdDateTime,"
    "webUrl,deleted,package,shortcut,remoteItem"
)
THROTTLE_STATUSES = (429, 503)
MAX_THROTTLE_RETRIES = 8
DEFAULT_RETRY_AFTER_S = 10.0
TIER3_AT_UPSERT = frozenset({DriveItemStatus.SKIPPED_UNSUPPORTED_PACKAGE, DriveItemStatus.SKIPPED_SHORTCUT})
KEEP_ON_REGATE = frozenset({DriveItemStatus.DELETED, *TIER3_AT_UPSERT})


class ResyncRequired(RuntimeError):
    """HTTP 410 on the stored delta link; ``location`` is Graph's fresh enumeration (file 02 §3.5)."""

    def __init__(self, location: str | None) -> None:
        super().__init__("delta token expired (410); a resync is required")
        self.location = location


class GraphCallFailed(RuntimeError):
    pass


@dataclass
class CrawlStats:
    root_name: str
    finished: bool = False
    resynced: bool = False
    deleted_after_check: int = 0
    kept_after_check: int = 0
    pages: int = 0
    folders_seen: int = 0
    items_seen: int = 0
    regated: int = 0
    orphans: int = 0
    by_status: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------- roots


def seed_roots(session: Session, settings: Settings) -> list[SyncRoot]:
    """One ``sync_roots`` row per configured folder (root name = last segment of its path)."""
    roots = []
    for folder_id, path in zip(settings.folder_ids, settings.folder_paths, strict=True):
        name = path.rstrip("/").rsplit("/", 1)[-1]
        root = session.get(SyncRoot, name)
        if root is None:
            root = SyncRoot(root_name=name, remote_drive_id=settings.drive_id, remote_item_id=folder_id)
            session.add(root)
        roots.append(root)
    session.flush()
    return roots


# ---------------------------------------------------------------- Graph paging


def _get_page(graph: GraphClient, url: str, params: Mapping[str, str] | None, sleep: Callable[[float], None]):
    for _ in range(MAX_THROTTLE_RETRIES):
        response = graph.get(url, params=params)
        if response.status_code in THROTTLE_STATUSES:
            wait = float(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER_S))
            log.warning("Graph throttled (%s); pausing %.0f s", response.status_code, wait)
            sleep(wait)
            continue
        if response.status_code == 410:
            raise ResyncRequired(response.headers.get("Location"))
        if response.status_code != 200:
            raise GraphCallFailed(f"delta page answered HTTP {response.status_code}")
        return response.json()
    raise GraphCallFailed("Graph kept throttling; the run stops and resumes from its checkpoint")


# ---------------------------------------------------------------- upsert


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _last_occurrence(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        by_id.pop(item["id"], None)
        by_id[item["id"]] = item
    return list(by_id.values())


def upsert_page(
    session: Session,
    root: SyncRoot,
    raw_items: Sequence[dict[str, Any]],
    now: datetime,
    resync_gen: int | None = None,
) -> tuple[int, int]:
    """Write one page of delta items; returns ``(folders, items)`` touched. During a resync every item
    seen is stamped with ``resync_gen``."""
    page = _last_occurrence(raw_items)
    drive = root.remote_drive_id
    ids = [item["id"] for item in page]
    folders = {
        f.item_id: f
        for f in session.scalars(
            select(DriveFolder).where(DriveFolder.drive_id == drive, DriveFolder.item_id.in_(ids))
        )
    }
    files = {
        i.item_id: i
        for i in session.scalars(
            select(DriveItem).where(DriveItem.drive_id == drive, DriveItem.item_id.in_(ids))
        )
    }
    n_folders = n_items = 0
    for raw in page:
        item_id = raw["id"]
        parent = (raw.get("parentReference") or {}).get("id")
        deleted = "deleted" in raw
        is_folder = "folder" in raw or (deleted and item_id in folders)
        if is_folder:
            n_folders += 1
            folder = folders.get(item_id)
            if folder is None:
                if deleted:
                    continue
                folder = DriveFolder(
                    drive_id=drive, item_id=item_id, root_name=root.root_name, name=raw.get("name", "")
                )
                session.add(folder)
            if deleted:
                folder.deleted_at = folder.deleted_at or now
                continue
            folder.name = raw.get("name", folder.name)
            folder.parent_item_id = parent if item_id != root.remote_item_id else None
            folder.deleted_at = None
            continue

        n_items += 1
        row = files.get(item_id)
        if row is None:
            if deleted:
                continue
            row = DriveItem(
                drive_id=drive, item_id=item_id, root_name=root.root_name, name=raw.get("name", "")
            )
            row.status = DriveItemStatus.SEEN
            session.add(row)
        if resync_gen is not None:
            row.resync_gen = resync_gen
        if deleted:
            row.status = DriveItemStatus.DELETED
            row.deleted_at = row.deleted_at or now
            row.last_seen_delta_at = now
            continue
        new_hash = ((raw.get("file") or {}).get("hashes") or {}).get("quickXorHash")
        if row.status == DriveItemStatus.DELETED or (row.quick_xor_hash and new_hash != row.quick_xor_hash):
            row.status = DriveItemStatus.SEEN
            row.deleted_at = None
        row.name = raw.get("name", row.name)
        row.extension = extension_of(row.name) or None
        row.size_bytes = raw.get("size")
        row.quick_xor_hash = new_hash
        row.etag = raw.get("eTag")
        row.web_url = raw.get("webUrl")
        row.last_modified_at = _ts(raw.get("lastModifiedDateTime"))
        row.created_at_source = _ts(raw.get("createdDateTime"))
        row.parent_item_id = parent
        row.last_seen_delta_at = now
        if "package" in raw:
            row.status, row.gate_reason = DriveItemStatus.SKIPPED_UNSUPPORTED_PACKAGE, "T3:package"
        elif "shortcut" in raw or "remoteItem" in raw:
            row.status, row.gate_reason = DriveItemStatus.SKIPPED_SHORTCUT, "T3:shortcut"
    session.flush()
    return n_folders, n_items


# ---------------------------------------------------------------- paths, gate, scope


def _folder_paths(root: SyncRoot, folders: Sequence[DriveFolder]) -> dict[str, list[str] | None]:
    """Folder item id → names from the root down (root name first), or None when the chain is broken."""
    by_id = {f.item_id: f for f in folders if f.deleted_at is None}
    resolved: dict[str, list[str] | None] = {root.remote_item_id: [root.root_name]}

    def walk(item_id: str) -> list[str] | None:
        chain = []
        current: str | None = item_id
        while current is not None and current not in resolved:
            folder = by_id.get(current)
            if folder is None or current in chain:
                for seen in chain:
                    resolved[seen] = None
                return None
            chain.append(current)
            current = folder.parent_item_id
        base = resolved.get(current) if current is not None else None
        for seen in reversed(chain):
            base = None if base is None else [*base, by_id[seen].name]
            resolved[seen] = base
        return resolved[item_id]

    for item_id in by_id:
        walk(item_id)
    return resolved


def finalize_root(
    session: Session, root: SyncRoot, gate: GateConfig, download_scope: Sequence[str], stats: CrawlStats
) -> None:
    drive = root.remote_drive_id
    folders = list(session.scalars(select(DriveFolder).where(DriveFolder.root_name == root.root_name)))
    names_by_folder = _folder_paths(root, folders)
    parent_of = {f.item_id: f.parent_item_id for f in folders}

    changed_folders: set[str] = set()
    for folder in folders:
        names = names_by_folder.get(folder.item_id)
        path = "/".join(names) if names else None
        is_junk, is_quarantine = folder_flags(names or [], gate)
        if (folder.path_cached, folder.is_junk, folder.is_quarantine) != (path, is_junk, is_quarantine):
            folder.path_cached, folder.is_junk, folder.is_quarantine = path, is_junk, is_quarantine
            changed_folders.add(folder.item_id)
    if root.remote_item_id not in {f.item_id for f in folders}:
        names_by_folder[root.remote_item_id] = [root.root_name]

    ancestors_cache: dict[str, list[str]] = {}

    def ancestors(folder_id: str | None) -> list[str]:
        if folder_id is None:
            return []
        if folder_id not in ancestors_cache:
            ancestors_cache[folder_id] = [folder_id, *ancestors(parent_of.get(folder_id))]
        return ancestors_cache[folder_id]

    candidates = select(DriveItem).where(
        DriveItem.drive_id == drive,
        DriveItem.root_name == root.root_name,
        or_(
            DriveItem.status == DriveItemStatus.SEEN,
            DriveItem.path_cached.is_(None),
            DriveItem.parent_item_id.in_(
                [f.item_id for f in folders if changed_folders & set(ancestors(f.item_id))] or [""]
            ),
        ),
    )
    blob_hash = (
        dict(session.execute(select(Blob.sha256, Blob.quick_xor_hash)).all()) if changed_folders else {}
    )
    for item in session.scalars(candidates):
        folder_names = names_by_folder.get(item.parent_item_id or "")
        if folder_names is None:
            stats.orphans += item.status != DriveItemStatus.DELETED
            continue
        item.path_cached = "/".join([*folder_names, item.name])
        if item.status in KEEP_ON_REGATE:
            continue
        verdict = gate_item(
            GateInput(name=item.name, size_bytes=item.size_bytes, folder_names=folder_names), gate
        )
        if verdict is None and not in_scope(
            download_scope, root.root_name, ancestors(item.parent_item_id), item.path_cached
        ):
            verdict = HELD_BY_DOWNLOAD_SCOPE
        stats.regated += 1
        if verdict is not None:
            item.status, item.gate_reason = verdict.status, verdict.gate_reason
            continue
        item.gate_reason = None
        if item.blob_sha256 is not None:
            known = blob_hash.get(item.blob_sha256) or session.scalar(
                select(Blob.quick_xor_hash).where(Blob.sha256 == item.blob_sha256)
            )
            if known is not None and known == item.quick_xor_hash:
                item.status = DriveItemStatus.LANDED
                continue
        if item.status != DriveItemStatus.DOWNLOAD_FAILED:
            item.status = DriveItemStatus.PENDING_DOWNLOAD
    session.flush()


# ---------------------------------------------------------------- resync (file 02 §3.5)


def _max_resync_gen(session: Session, root: SyncRoot) -> int:
    return (
        session.scalar(select(func.max(DriveItem.resync_gen)).where(DriveItem.root_name == root.root_name))
        or 0
    )


def _begin_resync(root: SyncRoot, session: Session, location: str | None) -> int:
    """Not committed here: the status change is committed together with the first stamped page."""
    log.error("resync of %s started (%s)", root.root_name, "410 from Graph" if location else "forced")
    root.status = SyncRootStatus.RESYNCING
    root.next_link_checkpoint = None
    return _max_resync_gen(session, root) + 1


def _confirm_missing(
    session: Session, graph: GraphClient, root: SyncRoot, generation: int, now: datetime, stats: CrawlStats
) -> None:
    """Items the enumeration did not return are deleted only if Graph confirms with a 404."""
    missing = session.scalars(
        select(DriveItem).where(
            DriveItem.root_name == root.root_name,
            DriveItem.status != DriveItemStatus.DELETED,
            DriveItem.resync_gen < generation,
        )
    )
    for item in missing:
        status = graph.get(
            f"/drives/{item.drive_id}/items/{item.item_id}", params={"$select": "id"}
        ).status_code
        if status == 404:
            item.status, item.deleted_at = DriveItemStatus.DELETED, now
            stats.deleted_after_check += 1
        else:
            item.resync_gen = generation
            stats.kept_after_check += 1
            log.warning("resync: %s missing from the enumeration but answers %s; kept", item.item_id, status)
    session.flush()


# ---------------------------------------------------------------- one run


def run_root(
    session: Session,
    graph: GraphClient,
    root: SyncRoot,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    force_resync: bool = False,
) -> CrawlStats:
    """Crawl (no delta link yet), incremental delta, or resync for one root; commits after every page.

    With a ``deadline`` (a ``clock()`` value) the run stops after the first committed page past it,
    leaving ``next_link_checkpoint`` for the next run; ``finished`` says whether the root completed.

    Resync (HTTP 410, or ``force_resync``; file 02 §3.5): the root becomes RESYNCING and every item
    seen is stamped with generation g = max(resync_gen) + 1. The status change is committed with the
    first stamped page, so a resumed resync (status already RESYNCING) continues with g = max. After
    the last page, unstamped items are deleted only if a direct GET answers 404.
    """
    stats = CrawlStats(root.root_name)
    first_crawl = root.delta_link is None and not force_resync
    fresh = (f"/drives/{root.remote_drive_id}/items/{root.remote_item_id}/delta", {"$select": DELTA_SELECT})
    resync_gen: int | None = None
    if root.status == SyncRootStatus.RESYNCING:
        resync_gen = _max_resync_gen(session, root)
    elif force_resync:
        resync_gen = _begin_resync(root, session, None)
    if root.next_link_checkpoint:
        url, params = root.next_link_checkpoint, None
    elif root.delta_link and resync_gen is None:
        url, params = root.delta_link, None
    else:
        url, params = fresh
    if first_crawl and root.status != SyncRootStatus.CRAWLING:
        root.status = SyncRootStatus.CRAWLING
        session.commit()

    while True:
        try:
            body = _get_page(graph, url, params, sleep)
        except ResyncRequired as expired:
            if resync_gen is not None:
                raise
            resync_gen = _begin_resync(root, session, expired.location)
            url, params = (expired.location, None) if expired.location else fresh
            continue
        n_folders, n_items = upsert_page(session, root, body.get("value", []), now(), resync_gen)
        stats.pages += 1
        stats.folders_seen += n_folders
        stats.items_seen += n_items
        next_link = body.get("@odata.nextLink")
        if next_link:
            root.next_link_checkpoint = next_link
            session.commit()
            if deadline is not None and clock() >= deadline:
                return stats
            url, params = next_link, None
            continue
        finalize_root(
            session,
            root,
            pipeline_config.gate_config(session),
            pipeline_config.download_scope(session),
            stats,
        )
        if resync_gen is not None:
            _confirm_missing(session, graph, root, resync_gen, now(), stats)
            stats.resynced = True
        root.delta_link = body.get("@odata.deltaLink")
        root.next_link_checkpoint = None
        root.status = SyncRootStatus.ACTIVE
        root.last_delta_at = now()
        if first_crawl:
            root.last_full_crawl_at = root.last_delta_at
        session.commit()
        stats.finished = True
        break

    counts = session.execute(
        select(DriveItem.status, func.count())
        .where(DriveItem.root_name == root.root_name)
        .group_by(DriveItem.status)
    )
    stats.by_status = {status: n for status, n in counts.all()}
    return stats


def main(argv: list[str]) -> int:
    import argparse
    import os
    from pathlib import Path

    from sqlalchemy import create_engine

    from backend.postgres.session import normalize_url
    from backend.sync.auth import GraphAuthConfig, TokenProvider

    parser = argparse.ArgumentParser(prog="python -m backend.sync.delta")
    parser.add_argument("command", choices=["crawl", "resync"], help="resync = forced 410 procedure (drill)")
    parser.add_argument("--root", help="one root name; default all")
    parser.add_argument(
        "--env-file", type=Path, default=None, help="settings file (default: the repository .env)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    settings = load_settings(args.env_file) if args.env_file else get_settings()
    provider = TokenProvider.create(GraphAuthConfig.from_settings(settings))
    engine = create_engine(
        normalize_url(os.environ.get("DCL_DATABASE_URL") or settings.stack_database_url().get_secret_value())
    )
    with Session(engine, expire_on_commit=False) as session, GraphClient(provider.access_token) as graph:
        pipeline_config.seed_gate(session, pipeline_config.load_gate_yaml())
        pipeline_config.seed_sanity_ranges(session)
        roots = seed_roots(session, settings)
        session.commit()
        for root in roots:
            if args.root and root.root_name != args.root:
                continue
            started = time.monotonic()
            stats = run_root(session, graph, root, force_resync=args.command == "resync")
            elapsed = time.monotonic() - started
            print(
                f"{stats.root_name}: {stats.pages} pages, {stats.items_seen} items, "
                f"{stats.folders_seen} folders, {stats.orphans} orphans, {elapsed:.0f} s"
            )
            print(f"  by status: {dict(sorted(stats.by_status.items()))}")
            if stats.resynced:
                deleted, kept = stats.deleted_after_check, stats.kept_after_check
                print(f"  resync: {deleted} deleted after a 404, {kept} kept")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
