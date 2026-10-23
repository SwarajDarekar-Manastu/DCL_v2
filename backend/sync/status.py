"""Per-root sync state for the Console (file 08 §3.2 Sources, §4.2 OpsPage): auth, crawl and delta
times, how the root is kept current (webhook or 5-minute poll) and the item counts by status, with the
landed files the processing scope would dispatch and recent download errors."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import DriveItem, SyncRoot
from backend.sync.webhooks import ENABLED_KEY

RECENT_ERRORS = 5


class RootCounts(BaseModel):
    items: int
    by_status: dict[str, int]
    held_by_scope: int
    pending_download: int
    download_failed: int
    landed: int
    waiting_dispatch: int


class RootError(BaseModel):
    path: str | None
    error: str


class RootView(BaseModel):
    root_name: str
    status: str
    auth_status: str
    cloud_allowed: bool
    default_source_origin: str
    last_full_crawl_at: datetime | None
    last_delta_at: datetime | None
    crawl_in_progress: bool
    kept_current_by: str  # "webhook" | "poll"
    subscription_expires_at: datetime | None
    counts: RootCounts
    recent_errors: list[RootError]


def _waiting(session: Session) -> dict[str, int]:
    """Landed files inside processing.scope that no document holds yet, per root."""
    from backend.postgres.config_impact import _ancestors, _unclaimed_landed
    from backend.sync.scope import in_scope

    scope = pipeline_config.processing_scope(session)
    chain = _ancestors(session)
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for item in _unclaimed_landed(session):
        if item.blob_sha256 in seen or not in_scope(scope, item.root_name, chain(item), item.path_cached):
            continue
        seen.add(item.blob_sha256)
        counts[item.root_name] = counts.get(item.root_name, 0) + 1
    return counts


def root_views(session: Session) -> list[RootView]:
    webhooks_on = pipeline_config.get(session, ENABLED_KEY, default=False) is True
    by_status: dict[str, dict[str, int]] = {}
    for root, status, n in session.execute(
        select(DriveItem.root_name, DriveItem.status, func.count()).group_by(
            DriveItem.root_name, DriveItem.status
        )
    ):
        by_status.setdefault(root, {})[status] = n
    waiting = _waiting(session)
    views = []
    for root in session.scalars(select(SyncRoot).order_by(SyncRoot.root_name)):
        statuses = by_status.get(root.root_name, {})
        errors = session.execute(
            select(DriveItem.path_cached, DriveItem.error_last)
            .where(DriveItem.root_name == root.root_name, DriveItem.status == DriveItemStatus.DOWNLOAD_FAILED)
            .order_by(DriveItem.path_cached)
            .limit(RECENT_ERRORS)
        ).all()
        views.append(
            RootView(
                root_name=root.root_name,
                status=root.status,
                auth_status=root.auth_status,
                cloud_allowed=root.cloud_allowed,
                default_source_origin=root.default_source_origin,
                last_full_crawl_at=root.last_full_crawl_at,
                last_delta_at=root.last_delta_at,
                crawl_in_progress=root.next_link_checkpoint is not None,
                kept_current_by="webhook" if webhooks_on and root.subscription_id else "poll",
                subscription_expires_at=root.subscription_expires_at if webhooks_on else None,
                counts=RootCounts(
                    items=sum(statuses.values()),
                    by_status=statuses,
                    held_by_scope=statuses.get(DriveItemStatus.HELD_BY_SCOPE, 0),
                    pending_download=statuses.get(DriveItemStatus.PENDING_DOWNLOAD, 0),
                    download_failed=statuses.get(DriveItemStatus.DOWNLOAD_FAILED, 0),
                    landed=statuses.get(DriveItemStatus.LANDED, 0),
                    waiting_dispatch=waiting.get(root.root_name, 0),
                ),
                recent_errors=[RootError(path=p, error=e or "") for p, e in errors],
            )
        )
    return views
