"""S1: Graph webhook receiver (file 02 §3.3). Graph calls it without a user token; the clientState secret
is the check. Off (404) until ``sync.webhooks_enabled`` and the webhook env values are set.

``POST /sync/webhook?validationToken=…`` echoes the token as text/plain (subscription validation).
A notification batch answers 202 at once; valid ones start one debounced ``dcl.sync.delta_root`` per root.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.postgres.models import SyncRoot
from backend.postgres.session import get_session
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
