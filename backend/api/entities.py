"""S1: entity curation for the Console's EntitiesPage (file 08 §4.4): ``GET /entities?query=&type=``,
``POST /entities/merge``, ``POST /entities/split``. Reviewer role; logic in ``backend/review/entities.py``."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.postgres.enums import EntityType
from backend.postgres.session import get_session
from backend.review import entities
from backend.review.entities import EntityPage, EntityView, MergeRequest, SplitRequest

router = APIRouter(prefix="/entities", tags=["entities"])
Reviewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]
Db = Annotated[Session, Depends(get_session)]


def _write(session: Session, action) -> EntityView:
    try:
        view = action()
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{exc} not found") from exc
    except entities.EntityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    return view


@router.get("")
def search(
    user: Reviewer,
    session: Db,
    query: str = "",
    entity_type: Annotated[EntityType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EntityPage:
    return entities.search(session, query, entity_type, limit, offset)


@router.post("/merge")
def merge(user: Reviewer, session: Db, body: MergeRequest) -> EntityView:
    return _write(session, lambda: entities.merge(session, body, user.email or user.oid))


@router.post("/split")
def split(user: Reviewer, session: Db, body: SplitRequest) -> EntityView:
    return _write(session, lambda: entities.split(session, body, user.email or user.oid))
