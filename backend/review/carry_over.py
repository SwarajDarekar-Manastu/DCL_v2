"""Decisions a new version of a file keeps (decided by the user on 2026-10-27).

A file changed in OneDrive becomes a new document whose questions start open (decisions are kept per
document). When the new version asks the same question with the same reading as the version it replaces,
the earlier decision carries over; anything that changed is asked again. "Same" is the flag's fingerprint
(its type and anchor) and its evidence with the image links left out, since those name each version's own
bytes. The page check's corrections (origin "review") carry over too: they apply only where the text still
reads what the person corrected (indexing/overlays.py).
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import Flag, FlagAnchor
from backend.postgres.enums import AuditEntityType, DocumentSourceRole, FlagSeverity, FlagStatus, FlagType
from backend.postgres.models import AuditEvent, Document, DocumentSource, DriveItem, ReviewFlag
from backend.review.flags import upsert_document_flag

DECIDED = (FlagStatus.RESOLVED, FlagStatus.AUTO_RESOLVED)
OPEN = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)
REVIEW_ORIGIN = "review"


def older_version(session: Session, blob_sha256: str) -> Document | None:
    """The document a location's earlier content made, while this content is its pending replacement."""
    previous = session.scalar(
        select(DriveItem.previous_blob_sha256)
        .where(DriveItem.blob_sha256 == blob_sha256, DriveItem.previous_blob_sha256.is_not(None))
        .limit(1)
    )
    if previous is None:
        return None
    return session.scalar(
        select(Document)
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .where(DocumentSource.blob_sha256 == previous, DocumentSource.role == DocumentSourceRole.PRIMARY)
    )


def reading(evidence: Any) -> Any:
    """The evidence without its image links."""
    if isinstance(evidence, dict):
        return {k: reading(v) for k, v in evidence.items() if not k.endswith("uri")}
    if isinstance(evidence, list):
        return [reading(v) for v in evidence]
    return evidence


def carry_over(session: Session, doc_id: uuid.UUID, blob_sha256: str, rows: list[ReviewFlag]) -> int:
    """Decide ``rows`` (the new version's flags) as the older version decided the same questions; copy its
    page-check corrections. Returns how many decisions carried over."""
    old = older_version(session, blob_sha256)
    if old is None:
        return 0
    earlier = list(session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == old.doc_id)))
    decided = {f.fingerprint: f for f in earlier if f.status in DECIDED and f.resolution}
    carried = 0
    for row in rows:
        before = decided.get(row.fingerprint)
        if row.status not in OPEN or before is None or reading(before.evidence) != reading(row.evidence):
            continue
        _decide_like(session, row, before, old.doc_id)
        carried += 1
    for before in (f for f in earlier if f.route == REVIEW_ORIGIN and f.status in DECIDED):
        flag = Flag(
            flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
            severity=FlagSeverity.SOFT,
            anchor=FlagAnchor.model_validate(before.anchor or {}),
        )
        row = upsert_document_flag(session, doc_id, flag, REVIEW_ORIGIN)
        if row.status in OPEN:
            _decide_like(session, row, before, old.doc_id)
            carried += 1
    session.flush()
    return carried


def _decide_like(session: Session, row: ReviewFlag, before: ReviewFlag, old_doc_id: uuid.UUID) -> None:
    row.status, row.resolution = before.status, before.resolution
    row.resolution_rule_id = before.resolution_rule_id
    row.resolved_by, row.resolved_at = before.resolved_by, before.resolved_at
    session.add(
        AuditEvent(
            actor="pipeline",
            entity_type=AuditEntityType.FLAG,
            entity_id=str(row.flag_id),
            action="carry_over",
            before=None,
            after={
                "status": row.status,
                "resolution": row.resolution,
                "from_flag": str(before.flag_id),
                "from_doc": str(old_doc_id),
            },
        )
    )
