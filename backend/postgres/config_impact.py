"""What a pipeline_config change does to the registry (file 08 §3.2 apply semantics; file 02 §3.1a, §4).

``preview`` counts the effect of a candidate change without writing; ``apply_effects`` performs the part
that is not picked up by the next run on its own:

- ``sync.download_scope``: widening moves HELD_BY_SCOPE items inside the new scope to PENDING_DOWNLOAD
  (LANDED when their content is already stored), and beat's ``dcl.sync.enqueue_downloads`` fetches them in
  batches; narrowing holds items not fetched yet (PENDING_DOWNLOAD, DOWNLOAD_FAILED). Landed content stays.
- ``processing.scope`` and ``routes.<X>.enabled``: the dispatcher reads both on every run; the caller
  starts a dispatch after the commit (``dispatch_needed``). A disabled route parks new documents as
  WAITING_FOR_ROUTE; enabling it releases them.
- ``gate.*``: applies to new and changed items at the next delta; the preview counts landed items the new
  gate would reject (they stay indexed).

The Gemini cost estimate for widening ``processing.scope`` is the mean cost per document over the priced
``llm_calls`` rows (at least ``COST_SAMPLE_MIN`` documents) times the files that enter; null otherwise.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.routing import folder_tree
from backend.postgres import pipeline_config
from backend.postgres.enums import DocumentStatus, DriveItemStatus
from backend.postgres.models import Blob, Document, DocumentSource, DriveItem
from backend.sync.gate import GateConfig, GateInput, gate_item
from backend.sync.scope import HELD_BY_DOWNLOAD_SCOPE, in_scope

NOT_FETCHED = (DriveItemStatus.PENDING_DOWNLOAD, DriveItemStatus.DOWNLOAD_FAILED)
NO_COST = "no priced llm_calls yet (set models.prices); counts only"
COST_SAMPLE_MIN = 5  # documents with priced calls before an average is shown


@dataclass
class Impact:
    key: str
    summary: str
    counts: dict[str, int] = field(default_factory=dict)
    bytes: int = 0
    by_extension: dict[str, int] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    cost_note: str | None = None


@dataclass
class Effects:
    released: int = 0
    held: int = 0
    dispatch_needed: bool = False


def _ancestors(session: Session):
    _, chains = folder_tree(session)
    return lambda item: chains.get(item.parent_item_id or "", [])


def _download_moves(session: Session, scope: list[str]) -> tuple[list[DriveItem], list[DriveItem]]:
    """(held items the scope now covers, not-fetched items it no longer covers)."""
    chain = _ancestors(session)
    items = session.scalars(
        select(DriveItem).where(
            DriveItem.status.in_([DriveItemStatus.HELD_BY_SCOPE, *NOT_FETCHED]),
            DriveItem.path_cached.is_not(None),
            DriveItem.deleted_at.is_(None),
        )
    ).all()
    release, hold = [], []
    for item in items:
        inside = in_scope(scope, item.root_name, chain(item), item.path_cached)
        if item.status == DriveItemStatus.HELD_BY_SCOPE and inside:
            release.append(item)
        elif item.status != DriveItemStatus.HELD_BY_SCOPE and not inside:
            hold.append(item)
    return release, hold


def _sizes(items: list[DriveItem]) -> tuple[int, dict[str, int]]:
    return sum(i.size_bytes or 0 for i in items), dict(Counter((i.extension or "").lower() for i in items))


def _download_scope_impact(session: Session, key: str, scope: list[str]) -> Impact:
    release, hold = _download_moves(session, scope)
    size, by_ext = _sizes(release)
    return Impact(
        key,
        f"{len(release)} held items will download; {len(hold)} not-yet-downloaded items will be held",
        {"to_download": len(release), "to_hold": len(hold)},
        size,
        by_ext,
    )


def _unclaimed_landed(session: Session) -> list[DriveItem]:
    claimed = select(DocumentSource.blob_sha256)
    return list(
        session.scalars(
            select(DriveItem)
            .join(Blob, Blob.sha256 == DriveItem.blob_sha256)
            .where(
                DriveItem.status == DriveItemStatus.LANDED,
                DriveItem.detected_mime.is_not(None),
                DriveItem.path_cached.is_not(None),
                Blob.restricted.is_(False),
                DriveItem.blob_sha256.not_in(claimed),
            )
        )
    )


def _processing_scope_impact(session: Session, key: str, scope: list[str]) -> Impact:
    chain = _ancestors(session)
    old = pipeline_config.processing_scope(session)
    entering, leaving = [], 0
    seen: set[str] = set()
    for item in _unclaimed_landed(session):
        if item.blob_sha256 in seen:
            continue  # one document per content, as in the dispatcher
        now_in = in_scope(scope, item.root_name, chain(item), item.path_cached)
        was_in = in_scope(old, item.root_name, chain(item), item.path_cached)
        if now_in and not was_in:
            seen.add(item.blob_sha256)
            entering.append(item)
        elif was_in and not now_in:
            seen.add(item.blob_sha256)
            leaving += 1
    size, by_ext = _sizes(entering)
    per_doc, sample = _mean_cost_per_document(session)
    return Impact(
        key,
        f"{len(entering)} landed files will be processed; {leaving} waiting files will no longer be",
        {"to_process": len(entering), "no_longer_processed": leaving},
        size,
        by_ext,
        estimated_cost_usd=round(per_doc * len(entering), 2) if per_doc is not None else None,
        cost_note=f"mean ${per_doc:.4f} per document over {sample} documents"
        if per_doc is not None
        else NO_COST,
    )


def _mean_cost_per_document(session: Session) -> tuple[float | None, int]:
    from sqlalchemy import func

    from backend.postgres.models import LlmCall

    per_doc = (
        select(func.sum(LlmCall.cost_estimate).label("cost"))
        .where(LlmCall.doc_id.is_not(None), LlmCall.cost_estimate.is_not(None))
        .group_by(LlmCall.doc_id)
        .subquery()
    )
    mean, sample = session.execute(select(func.avg(per_doc.c.cost), func.count())).one()
    return (float(mean), sample) if sample >= COST_SAMPLE_MIN and mean is not None else (None, sample)


def _route_impact(session: Session, key: str, enabled: bool) -> Impact:
    route = key.split(".")[1]
    waiting = len(
        session.scalars(
            select(Document.doc_id).where(
                Document.route == route, Document.status == DocumentStatus.WAITING_FOR_ROUTE
            )
        ).all()
    )
    summary = (
        f"{waiting} parked documents of route {route} will be processed"
        if enabled
        else f"new route {route} documents will be parked ({waiting} parked now)"
    )
    return Impact(key, summary, {"waiting_for_route": waiting})


def _gate_impact(session: Session, gate_changes: Mapping[str, Any]) -> Impact:
    merged = {k.removeprefix(pipeline_config.GATE_PREFIX): v for k, v in gate_changes.items()}
    current = {
        k.removeprefix(pipeline_config.GATE_PREFIX): v
        for k, v in pipeline_config.get_prefix(session, pipeline_config.GATE_PREFIX).items()
    }
    gate = GateConfig.from_mapping({**current, **merged})
    rejected: Counter[str] = Counter()
    landed = session.scalars(
        select(DriveItem).where(
            DriveItem.status == DriveItemStatus.LANDED, DriveItem.path_cached.is_not(None)
        )
    )
    for item in landed:
        verdict = gate_item(
            GateInput(
                name=item.name, size_bytes=item.size_bytes, folder_names=item.path_cached.split("/")[:-1]
            ),
            gate,
        )
        if verdict is not None:
            rejected[verdict.gate_reason] += 1
    total = sum(rejected.values())
    return Impact(
        "gate.*",
        f"{total} currently landed files would now be rejected (they stay indexed; new and changed items "
        "are gated with the new rules)",
        {"would_reject": total, **dict(rejected)},
    )


def preview(session: Session, values: Mapping[str, Any]) -> list[Impact]:
    """Impact of validated ``values`` (``pipeline_config.validate_changes``) against the current state."""
    impacts = []
    gate_changes = {k: v for k, v in values.items() if k.startswith(pipeline_config.GATE_PREFIX)}
    for key, value in values.items():
        if key == pipeline_config.DOWNLOAD_SCOPE:
            impacts.append(_download_scope_impact(session, key, list(value)))
        elif key == pipeline_config.PROCESSING_SCOPE:
            impacts.append(_processing_scope_impact(session, key, list(value)))
        elif key.startswith("routes.") and key.endswith(".enabled"):
            impacts.append(_route_impact(session, key, bool(value)))
    if gate_changes:
        impacts.append(_gate_impact(session, gate_changes))
    return impacts


def apply_effects(session: Session, keys: set[str]) -> Effects:
    """Run after the new versions are written (same transaction): the scope moves; flags the dispatch."""
    effects = Effects()
    if pipeline_config.DOWNLOAD_SCOPE in keys:
        release, hold = _download_moves(session, pipeline_config.download_scope(session))
        stored = dict(
            session.execute(
                select(Blob.sha256, Blob.quick_xor_hash).where(
                    Blob.sha256.in_([i.blob_sha256 for i in release if i.blob_sha256])
                )
            ).all()
        )
        for item in release:
            known = stored.get(item.blob_sha256 or "")
            item.status = (
                DriveItemStatus.LANDED
                if known is not None and known == item.quick_xor_hash
                else DriveItemStatus.PENDING_DOWNLOAD
            )
            item.gate_reason = None
        for item in hold:
            item.status, item.gate_reason = HELD_BY_DOWNLOAD_SCOPE.status, HELD_BY_DOWNLOAD_SCOPE.gate_reason
        effects.released, effects.held = len(release), len(hold)
    effects.dispatch_needed = pipeline_config.PROCESSING_SCOPE in keys or any(
        k.startswith("routes.") and k.endswith(".enabled") for k in keys
    )
    session.flush()
    return effects
