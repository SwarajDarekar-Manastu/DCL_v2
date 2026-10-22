"""Settings API over ``pipeline_config`` for the Console Settings pages (file 08 §3.2, 05 §4.6). Owner: S1.

- ``GET /settings?prefix=`` current value and version of every key
- ``GET /settings/{key}/history`` every version of a key, newest first
- ``POST /settings/preview`` validate a batch and count its effect (nothing written)
- ``PUT /settings`` apply a batch atomically: one new version and one ``audit_events`` row per changed key
- ``POST /settings/rollback`` write each key's value at an earlier version as a new version

Admin only. Unknown keys or values are 422 with ``{"errors": {key: reason}}``; an ``expected_version`` older
than the current one is 409. After a commit that changes ``processing.scope`` or ``routes.<X>.enabled`` the
dispatch task is started; released downloads are started the same way (both run on beat as well).
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, JsonValue, PositiveInt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.postgres import config_impact, pipeline_config
from backend.postgres.pipeline_config import Change, InvalidConfig, VersionConflict
from backend.postgres.session import get_session

log = logging.getLogger(__name__)


class ConfigEntry(BaseModel):
    key: str
    version: int
    value: JsonValue
    updated_by: str
    updated_at: datetime
    description: str | None


class ConfigList(BaseModel):
    items: list[ConfigEntry]


class ChangeBatch(BaseModel):
    changes: list[Change] = Field(min_length=1)
    description: str | None = Field(default=None, description="why; stored with every new version")


class RollbackRequest(BaseModel):
    versions: dict[str, PositiveInt] = Field(min_length=1, description="key → version to restore")
    description: str | None = None


class ImpactView(BaseModel):
    key: str
    summary: str
    counts: dict[str, int]
    bytes: int
    by_extension: dict[str, int]
    estimated_cost_usd: float | None
    cost_note: str | None


class PreviewResponse(BaseModel):
    impacts: list[ImpactView]


class AppliedView(BaseModel):
    key: str
    version: int
    before: JsonValue
    after: JsonValue


class ApplyResponse(BaseModel):
    applied: list[AppliedView]
    impacts: list[ImpactView]
    released_downloads: int
    held_downloads: int
    dispatch_started: bool


router = APIRouter(prefix="/settings", tags=["settings"])
Admin = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.ADMIN))]
Db = Annotated[Session, Depends(get_session)]


def start_task(name: str) -> bool:
    """Best effort: beat runs the same task on its schedule if the broker is unreachable now."""
    try:
        from backend.celery_redis.app import app

        app.send_task(name)
        return True
    except Exception:  # broker down or not configured for this role
        log.warning("could not start %s; beat will run it on schedule", name, exc_info=True)
        return False


def _impacts(impacts: list[config_impact.Impact]) -> list[ImpactView]:
    return [ImpactView.model_validate(i, from_attributes=True) for i in impacts]


def _invalid(exc: InvalidConfig) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": exc.errors})


def _apply(session: Session, changes: list[Change], user: ConsoleUser, description: str | None, action: str):
    actor = user.email or user.oid
    try:
        values = pipeline_config.validate_changes(session, {c.key: c.value for c in changes})
        impacts = config_impact.preview(session, values)
        applied = pipeline_config.apply_changes(session, changes, actor, description, action=action)
        effects = config_impact.apply_effects(session, {a.key for a in applied})
        session.commit()
    except InvalidConfig as exc:
        session.rollback()
        raise _invalid(exc) from exc
    except VersionConflict as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IntegrityError as exc:  # a concurrent writer took the same version
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "a concurrent change won; reload and retry") from exc
    if effects.released:
        start_task("dcl.sync.enqueue_downloads")
    dispatched = effects.dispatch_needed and start_task("dcl.process.dispatch")
    return ApplyResponse(
        applied=[AppliedView(key=a.key, version=a.version, before=a.before, after=a.after) for a in applied],
        impacts=_impacts(impacts),
        released_downloads=effects.released,
        held_downloads=effects.held,
        dispatch_started=dispatched,
    )


@router.get("")
def list_settings(user: Admin, session: Db, prefix: Annotated[str, Query()] = "") -> ConfigList:
    rows = pipeline_config.current_entries(session, prefix)
    return ConfigList(items=[ConfigEntry.model_validate(r, from_attributes=True) for r in rows])


@router.get("/{key}/history")
def key_history(user: Admin, session: Db, key: str) -> ConfigList:
    rows = pipeline_config.history(session, key)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{key} has no versions")
    return ConfigList(items=[ConfigEntry.model_validate(r, from_attributes=True) for r in rows])


@router.post("/preview")
def preview(user: Admin, session: Db, body: ChangeBatch) -> PreviewResponse:
    try:
        values = pipeline_config.validate_changes(session, {c.key: c.value for c in body.changes})
    except InvalidConfig as exc:
        raise _invalid(exc) from exc
    return PreviewResponse(impacts=_impacts(config_impact.preview(session, values)))


@router.put("")
def apply(user: Admin, session: Db, body: ChangeBatch) -> ApplyResponse:
    return _apply(session, body.changes, user, body.description, "update")


@router.post("/rollback")
def rollback(user: Admin, session: Db, body: RollbackRequest) -> ApplyResponse:
    try:
        changes = pipeline_config.rollback_changes(session, body.versions)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _apply(session, changes, user, body.description, "rollback")
