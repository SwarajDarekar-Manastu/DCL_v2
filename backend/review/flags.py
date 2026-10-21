"""Flag rows (``review_flags``) written from the contract's ``Flag``: upserted by fingerprint (file 06 §5).

A re-raised flag keeps its status and resolution; only evidence and suggestion are refreshed.
Location-level flags (no document yet) are unique on ``(location_id, fingerprint)``.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import Flag
from backend.postgres.models import ReviewFlag


def upsert_location_flag(
    session: Session, location_id: uuid.UUID, flag: Flag, route: str | None = None
) -> ReviewFlag:
    row = session.scalar(
        select(ReviewFlag).where(
            ReviewFlag.location_id == location_id,
            ReviewFlag.doc_id.is_(None),
            ReviewFlag.fingerprint == flag.fingerprint,
        )
    )
    dumped = flag.model_dump(mode="json")
    if row is None:
        row = ReviewFlag(
            case_key=f"{location_id}:{flag.page_or_sheet}",
            location_id=location_id,
            page_or_sheet=flag.page_or_sheet,
            fingerprint=flag.fingerprint,
            flag_type=flag.flag_type,
            severity=flag.severity,
            route=route,
            anchor=flag.anchor.model_dump(mode="json", exclude_none=True),
        )
        session.add(row)
    row.evidence = dumped["evidence"]
    row.suggested_resolution = dumped["suggested_resolution"]
    session.flush()
    return row


def upsert_document_flag(
    session: Session, doc_id: uuid.UUID, flag: Flag, route: str | None = None
) -> ReviewFlag:
    row = session.scalar(
        select(ReviewFlag).where(ReviewFlag.doc_id == doc_id, ReviewFlag.fingerprint == flag.fingerprint)
    )
    dumped = flag.model_dump(mode="json")
    if row is None:
        row = ReviewFlag(
            case_key=f"{doc_id}:{flag.page_or_sheet}",
            doc_id=doc_id,
            page_or_sheet=flag.page_or_sheet,
            fingerprint=flag.fingerprint,
            flag_type=flag.flag_type,
            severity=flag.severity,
            route=route,
            anchor=flag.anchor.model_dump(mode="json", exclude_none=True),
        )
        session.add(row)
    row.evidence = dumped["evidence"]
    row.suggested_resolution = dumped["suggested_resolution"]
    session.flush()
    return row
