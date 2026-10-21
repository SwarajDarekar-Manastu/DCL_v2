"""Read-only audit log for the Console AuditPage (file 08 §4.2, §4.4; file 05 §4.5). Owner: S3.

`GET /audit` lists `audit_events` newest first with filters and a cursor. A case's history is
`entity_type=case&entity_id=<case_key>`; `entity_id` may repeat to add the case's flag ids.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.postgres.enums import AuditEntityType
from backend.postgres.models import AuditEvent
from backend.postgres.session import get_session


class AuditItem(BaseModel):
    event_id: int
    at: datetime
    actor: str
    entity_type: AuditEntityType
    entity_id: str
    action: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class AuditPage(BaseModel):
    items: list[AuditItem]
    next_cursor: str | None


class AuditFilters(BaseModel):
    entity_type: AuditEntityType | None = None
    entity_id: list[str] = []
    actor: str | None = None
    action: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    cursor: str | None = Field(default=None, pattern=r"^\d+$", description="next_cursor of the previous page")
    limit: int = Field(default=100, ge=1, le=500)


def query_audit(session: Session, filters: AuditFilters) -> AuditPage:
    stmt = select(AuditEvent).order_by(AuditEvent.event_id.desc())
    if filters.entity_type:
        stmt = stmt.where(AuditEvent.entity_type == filters.entity_type)
    if filters.entity_id:
        stmt = stmt.where(AuditEvent.entity_id.in_(filters.entity_id))
    if filters.actor:
        stmt = stmt.where(AuditEvent.actor == filters.actor)
    if filters.action:
        stmt = stmt.where(AuditEvent.action == filters.action)
    if filters.since:
        stmt = stmt.where(AuditEvent.at >= filters.since)
    if filters.until:
        stmt = stmt.where(AuditEvent.at < filters.until)
    if filters.cursor:
        stmt = stmt.where(AuditEvent.event_id < int(filters.cursor))
    rows = session.scalars(stmt.limit(filters.limit + 1)).all()
    page = rows[: filters.limit]
    return AuditPage(
        items=[AuditItem.model_validate(row, from_attributes=True) for row in page],
        next_cursor=str(page[-1].event_id) if len(rows) > filters.limit else None,
    )


router = APIRouter(prefix="/audit", tags=["audit"])
Reviewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]


@router.get("")
def list_audit(
    user: Reviewer,
    session: Annotated[Session, Depends(get_session)],
    filters: Annotated[AuditFilters, Query()],
) -> AuditPage:
    return query_audit(session, filters)
