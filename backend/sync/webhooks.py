"""Graph change notifications (file 02 §3.3), off until a public endpoint exists.

On when ``pipeline_config`` ``sync.webhooks_enabled`` is true and the environment names the public
notification URL and the clientState secret (``DCL_GRAPH_WEBHOOK_URL``, ``DCL_GRAPH_WEBHOOK_CLIENT_STATE``;
S4's env contract). One subscription per root on its drive, change type ``updated``, lifetime about
3 days, renewed by ``dcl.sync.renew_subscriptions`` once 70% of it has passed. The receiver validates
``clientState``, answers 202 at once and pushes one debounced delta run per root (30 s window); webhooks
are a trigger only, the 5-minute delta poll and the daily delta stay the safety net.

``SubscriptionClient`` reaches ``/subscriptions`` and nothing else: the drive client stays read-only.
"""

import hmac
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.postgres import pipeline_config
from backend.postgres.models import SyncRoot
from backend.sync.graph_client import GRAPH_BASE_URL

log = logging.getLogger(__name__)

ENABLED_KEY = "sync.webhooks_enabled"
LIFETIME = timedelta(days=3)
RENEW_AT = 0.7  # of the lifetime
DEBOUNCE_S = 30


@dataclass(frozen=True)
class WebhookConfig:
    notification_url: str
    client_state: str


def webhook_config(session: Session, settings: Any) -> WebhookConfig | None:
    """The config when webhooks are switched on and both environment values exist, else None."""
    if pipeline_config.get(session, ENABLED_KEY, default=False) is not True:
        return None
    url = getattr(settings, "graph_webhook_url", None)
    secret = getattr(settings, "graph_webhook_client_state", None)
    secret = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
    if not url or not secret:
        log.warning("%s is on but DCL_GRAPH_WEBHOOK_URL / _CLIENT_STATE are not set", ENABLED_KEY)
        return None
    return WebhookConfig(str(url), secret)


class SubscriptionClient:
    """POST, PATCH and DELETE on ``/subscriptions`` only."""

    def __init__(self, access_token: Callable[[], str], transport: httpx.BaseTransport | None = None) -> None:
        self._token = access_token
        self._http = httpx.Client(base_url=GRAPH_BASE_URL, transport=transport, timeout=30.0)

    def _send(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> httpx.Response:
        if not (path == "/subscriptions" or path.startswith("/subscriptions/")):
            raise ValueError("the subscription client only reaches /subscriptions")
        headers = {"Authorization": f"Bearer {self._token()}"}
        return self._http.request(method, path, json=body, headers=headers)

    def create(self, body: Mapping[str, Any]) -> httpx.Response:
        return self._send("POST", "/subscriptions", body)

    def renew(self, subscription_id: str, expires: datetime) -> httpx.Response:
        return self._send("PATCH", f"/subscriptions/{subscription_id}", {"expirationDateTime": _iso(expires)})

    def close(self) -> None:
        self._http.close()


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def due(root: SyncRoot, now: datetime) -> bool:
    """No subscription yet, or 70% of its lifetime has passed."""
    if root.subscription_id is None or root.subscription_expires_at is None:
        return True
    return now >= root.subscription_expires_at - LIFETIME * (1 - RENEW_AT)


def ensure_subscriptions(
    session: Session, client: SubscriptionClient, config: WebhookConfig, now: datetime | None = None
) -> dict[str, str]:
    """Create or renew each root's subscription when due; returns ``{root: created|renewed|failed|ok}``."""
    now = now or datetime.now(UTC)
    expires = now + LIFETIME
    outcome: dict[str, str] = {}
    for root in session.scalars(select(SyncRoot).order_by(SyncRoot.root_name)):
        if not due(root, now):
            outcome[root.root_name] = "ok"
            continue
        if root.subscription_id:
            response = client.renew(root.subscription_id, expires)
            if response.status_code == 200:
                root.subscription_expires_at = expires
                outcome[root.root_name] = "renewed"
                continue
            log.warning(
                "renewal of %s for %s answered %s; creating a new one",
                root.subscription_id,
                root.root_name,
                response.status_code,
            )
        response = client.create(
            {
                "changeType": "updated",
                "notificationUrl": config.notification_url,
                "resource": f"/drives/{root.remote_drive_id}/root",
                "expirationDateTime": _iso(expires),
                "clientState": config.client_state,
            }
        )
        if response.status_code == 201:
            body = response.json()
            root.subscription_id = body["id"]
            root.subscription_expires_at = expires
            outcome[root.root_name] = "created"
        else:
            log.error(
                "subscription for %s failed: %s %s", root.root_name, response.status_code, response.text[:300]
            )
            outcome[root.root_name] = "failed"
    session.flush()
    return outcome


def roots_to_sync(
    notifications: Iterable[Mapping[str, Any]], client_state: str, root_by_subscription: Mapping[str, str]
) -> tuple[set[str], int]:
    """Roots named by valid notifications, and the number refused (wrong clientState or unknown id)."""
    roots: set[str] = set()
    refused = 0
    for item in notifications:
        state = str(item.get("clientState") or "")
        root = root_by_subscription.get(str(item.get("subscriptionId") or ""))
        if not hmac.compare_digest(state.encode(), client_state.encode()) or root is None:
            refused += 1
            continue
        roots.add(root)
    return roots, refused


def debounce(redis_client: Any, roots: Iterable[str], start: Callable[[str, int], None]) -> list[str]:
    """One delta run per root per window: the first notification starts it ``DEBOUNCE_S`` later."""
    started = []
    for root in sorted(roots):
        if redis_client.set(f"sync:webhook:{root}", "1", nx=True, ex=DEBOUNCE_S):
            start(root, DEBOUNCE_S)
            started.append(root)
    return started
