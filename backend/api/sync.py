"""S1: sync routes. Console (file 08 §3.2 Sources, §4.2 OpsPage):

- ``GET /sync/roots`` (reviewer): per root auth, crawl and delta times, webhook or poll, item counts,
  landed files waiting for dispatch, recent download errors
- ``POST /sync/sign-in`` / ``GET /sync/sign-in`` (admin): start the device-code sign-in (it runs on
  io_light, where the token cache lives) and read its code and outcome
- ``POST /sync/process-everything`` (admin): ``processing.scope`` emptied through the audited settings path
- ``GET|POST /sync/redispatch?route=X`` (admin): "re-process affected documents", count first

Graph webhook receiver (file 02 §3.3). Graph calls it without a user token; the clientState secret
is the check. Off (404) until ``sync.webhooks_enabled`` and the webhook env values are set.

``POST /sync/webhook?validationToken=…`` echoes the token as text/plain (subscription validation).
A notification batch answers 202 at once; valid ones start one debounced ``dcl.sync.delta_root`` per root.
"""

import json
import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.config import get_settings
from backend.postgres.enums import AuditEntityType, Route
from backend.postgres.models import AuditEvent, SyncRoot
from backend.postgres.session import get_session
from backend.sync.status import RootView, root_views
from backend.sync.webhooks import debounce, roots_to_sync, webhook_config

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])
Db = Annotated[Session, Depends(get_session)]


def _redis():
    import redis

    return redis.Redis.from_url(get_settings().redis_url)


def _start_delta(root: str, countdown: int) -> None:
    from backend.celery_redis.app import app

    app.send_task("dcl.sync.delta_root", args=[root], queue="io_light", countdown=countdown)


@router.post("/webhook", response_model=None)
async def graph_webhook(
    request: Request,
    session: Db,
    validation_token: Annotated[str | None, Query(alias="validationToken")] = None,
) -> Response:
    config = webhook_config(session, get_settings())
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "webhooks are off")
    if validation_token is not None:
        return PlainTextResponse(validation_token)
    try:
        body: Any = await request.json()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not JSON") from None
    notifications = body.get("value", []) if isinstance(body, dict) else []
    by_subscription = dict(
        session.execute(
            select(SyncRoot.subscription_id, SyncRoot.root_name).where(SyncRoot.subscription_id.is_not(None))
        ).all()
    )
    roots, refused = roots_to_sync(notifications, config.client_state, by_subscription)
    if refused:
        log.warning("refused %d Graph notifications (clientState or subscription id)", refused)
    if roots:
        debounce(_redis(), roots, _start_delta)
    return Response(status_code=status.HTTP_202_ACCEPTED)


# ---------------------------------------------------------------- Console: Sources and Ops

Admin = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.ADMIN))]
Reviewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]
SIGN_IN_KEY = "sync:sign_in"


class SignInState(BaseModel):
    state: str  # idle | starting | pending | signed_in | failed
    user_code: str | None = None
    verification_uri: str | None = None
    expires_at: datetime | None = None
    detail: str | None = None


class RedispatchPreview(BaseModel):
    route: Route
    documents: int
    sample: list[str]


class RedispatchResult(BaseModel):
    route: Route
    redispatched: int
    started: bool


@router.get("/roots")
def list_roots(user: Reviewer, session: Db) -> list[RootView]:
    return root_views(session)


def _send(name: str, args: list | None = None, queue: str = "io_light") -> bool:
    try:
        from backend.celery_redis.app import app

        app.send_task(name, args=args or [], queue=queue)
        return True
    except Exception:
        log.warning("could not start %s", name, exc_info=True)
        return False


@router.post("/sign-in")
def start_sign_in(user: Admin) -> SignInState:
    state = SignInState(state="starting")
    _redis().set(SIGN_IN_KEY, state.model_dump_json(), ex=1800)
    if not _send("dcl.sync.sign_in"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the task queue is unreachable")
    return state


@router.get("/sign-in")
def sign_in_state(user: Admin) -> SignInState:
    raw = _redis().get(SIGN_IN_KEY)
    return SignInState.model_validate(json.loads(raw)) if raw else SignInState(state="idle")


@router.post("/process-everything")
def process_everything(user: Admin, session: Db):
    """Empty ``processing.scope`` (= everything) through the settings path: versioned, audited, previewed."""
    from backend.api.settings import ApplyResponse, _apply
    from backend.postgres import pipeline_config

    response: ApplyResponse = _apply(
        session,
        [pipeline_config.Change(key=pipeline_config.PROCESSING_SCOPE, value=[])],
        user,
        "process everything (Console Sources)",
        "update",
    )
    return response


@router.get("/redispatch")
def redispatch_preview(user: Admin, session: Db, route: Route) -> RedispatchPreview:
    from backend.dispatcher.routing import redispatch_candidates

    documents = redispatch_candidates(session, route)
    return RedispatchPreview(
        route=route, documents=len(documents), sample=[d.title or "" for d in documents[:20]]
    )


@router.post("/redispatch")
def redispatch(user: Admin, session: Db, route: Route) -> RedispatchResult:
    """Re-run every committed document of ``route`` (after a parser or configuration change)."""
    from backend.dispatcher.routing import redispatch as run

    releases = run(session, route)
    session.add(
        AuditEvent(
            actor=user.email or user.oid,
            entity_type=AuditEntityType.CONFIG,
            entity_id=f"routes.{route}",
            action="redispatch",
            before=None,
            after={"documents": len(releases)},
        )
    )
    session.commit()
    started = all(_send(r.task, [str(r.doc_id)], r.queue) for r in releases) if releases else True
    return RedispatchResult(route=route, redispatched=len(releases), started=started)
