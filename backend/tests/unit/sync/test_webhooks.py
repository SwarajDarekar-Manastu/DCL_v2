"""Graph subscriptions, the webhook receiver and the 5-minute delta poll (file 02 §3.3)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api import sync as sync_api
from backend.postgres import pipeline_config
from backend.postgres.models import SyncRoot
from backend.postgres.session import get_session
from backend.sync import webhooks
from backend.sync.webhooks import (
    LIFETIME,
    SubscriptionClient,
    WebhookConfig,
    debounce,
    ensure_subscriptions,
    roots_to_sync,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
CONFIG = WebhookConfig("https://dcl.example/sync/webhook", "s3cret-state")


class FakeRedis:
    def __init__(self):
        self.keys = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


def test_only_valid_notifications_name_roots():
    notes = [
        {"subscriptionId": "s1", "clientState": "s3cret-state"},
        {"subscriptionId": "s1", "clientState": "s3cret-state"},
        {"subscriptionId": "s2", "clientState": "wrong"},
        {"subscriptionId": "unknown", "clientState": "s3cret-state"},
    ]
    assert roots_to_sync(notes, "s3cret-state", {"s1": "APU", "s2": "APU Heater"}) == ({"APU"}, 2)


def test_a_burst_starts_one_delta_per_root_per_window():
    redis, started = FakeRedis(), []
    assert debounce(redis, {"APU", "APU Heater"}, lambda r, c: started.append((r, c))) == [
        "APU",
        "APU Heater",
    ]
    assert debounce(redis, {"APU"}, lambda r, c: started.append((r, c))) == []
    assert started == [("APU", 30), ("APU Heater", 30)]


def test_the_subscription_client_reaches_nothing_but_subscriptions():
    client = SubscriptionClient(lambda: "t", transport=httpx.MockTransport(lambda r: httpx.Response(201)))
    with pytest.raises(ValueError, match="only reaches /subscriptions"):
        client._send("POST", "/drives/D/root/children", {})


def _graph(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "PATCH" and request.url.path.endswith("/gone"):
            return httpx.Response(404)
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(201, json={"id": f"sub-{len(calls)}"})

    return SubscriptionClient(lambda: "t", transport=httpx.MockTransport(handler))


def test_subscriptions_are_created_renewed_at_70_percent_and_recreated_when_gone(session):
    session.add_all(
        [
            SyncRoot(root_name="APU", remote_drive_id="D", remote_item_id="R1"),
            SyncRoot(
                root_name="APU Heater",
                remote_drive_id="D",
                remote_item_id="R2",
                subscription_id="old",
                subscription_expires_at=NOW + timedelta(hours=12),
            ),
            SyncRoot(
                root_name="APS - Library",
                remote_drive_id="D",
                remote_item_id="R3",
                subscription_id="gone",
                subscription_expires_at=NOW + timedelta(hours=1),
            ),
            SyncRoot(
                root_name="APU Fresh",
                remote_drive_id="D",
                remote_item_id="R4",
                subscription_id="fresh",
                subscription_expires_at=NOW + LIFETIME,
            ),
        ]
    )
    session.flush()
    calls = []
    outcome = ensure_subscriptions(session, _graph(calls), CONFIG, NOW)
    assert outcome == {
        "APS - Library": "created",
        "APU": "created",
        "APU Fresh": "ok",
        "APU Heater": "renewed",
        "APU Injector": "created",
    }
    assert ("PATCH", "/v1.0/subscriptions/old") in calls and ("PATCH", "/v1.0/subscriptions/gone") in calls
    heater = session.get(SyncRoot, "APU Heater")
    assert (heater.subscription_id, heater.subscription_expires_at) == ("old", NOW + LIFETIME)
    assert session.get(SyncRoot, "APS - Library").subscription_id.startswith("sub-")


@pytest.fixture
def receiver(session, monkeypatch):
    redis, started = FakeRedis(), []
    monkeypatch.setattr(sync_api, "_redis", lambda: redis)
    monkeypatch.setattr(sync_api, "_start_delta", lambda root, countdown: started.append(root))
    app = FastAPI()
    app.include_router(sync_api.router)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), started


def test_receiver_is_off_until_enabled(receiver):
    client, _ = receiver
    assert client.post("/sync/webhook", params={"validationToken": "abc"}).status_code == 404


def test_receiver_validates_and_debounces(receiver, session, monkeypatch):
    client, started = receiver
    monkeypatch.setattr(sync_api, "webhook_config", lambda s, settings: CONFIG)
    session.get(SyncRoot, "APU Injector").subscription_id = "sub-inj"
    session.commit()
    echo = client.post("/sync/webhook", params={"validationToken": "token value"})
    assert (echo.status_code, echo.text, echo.headers["content-type"].split(";")[0]) == (
        200,
        "token value",
        "text/plain",
    )
    batch = {"value": [{"subscriptionId": "sub-inj", "clientState": "s3cret-state"}] * 3}
    assert client.post("/sync/webhook", json=batch).status_code == 202
    assert (
        client.post(
            "/sync/webhook", json={"value": [{"subscriptionId": "sub-inj", "clientState": "x"}]}
        ).status_code
        == 202
    )
    assert started == ["APU Injector"]


def test_webhook_config_needs_the_flag_and_both_env_values(session):
    class S:
        graph_webhook_url = "https://dcl.example/sync/webhook"
        graph_webhook_client_state = None

    assert webhooks.webhook_config(session, S()) is None
    pipeline_config.set_value(session, webhooks.ENABLED_KEY, True, "test")
    assert webhooks.webhook_config(session, S()) is None
    S.graph_webhook_client_state = "s3cret-state"
    assert webhooks.webhook_config(session, S()) == CONFIG


def test_poll_starts_one_delta_per_active_root_with_a_link(session, monkeypatch):
    from backend.celery_redis import tasks_sync

    session.get(
        SyncRoot, "APU Injector"
    ).delta_link = "https://graph.microsoft.com/v1.0/drives/D/root/delta?token=x"
    session.add(
        SyncRoot(
            root_name="APU",
            remote_drive_id="D",
            remote_item_id="R1",
            delta_link="https://x",
            status="RESYNCING",
        )
    )
    session.add(SyncRoot(root_name="APU Heater", remote_drive_id="D", remote_item_id="R2"))
    session.add(
        SyncRoot(
            root_name="Mid chain",
            remote_drive_id="D",
            remote_item_id="R3",
            delta_link="https://x",
            next_link_checkpoint="https://graph.microsoft.com/v1.0/next",
        )
    )
    session.add(
        SyncRoot(root_name="Locked", remote_drive_id="D", remote_item_id="R5", delta_link="https://x")
    )
    session.commit()
    sent = []

    class Lock:
        def exists(self, key):
            return key == "sync:lock:Locked"

    monkeypatch.setattr(tasks_sync, "_redis", lambda: Lock())
    monkeypatch.setattr(tasks_sync, "_engine", lambda: session.get_bind())
    monkeypatch.setattr(tasks_sync.delta_root, "apply_async", lambda args, queue: sent.append((args, queue)))
    assert tasks_sync.poll_deltas() == ["APU Injector"]
    assert sent == [(["APU Injector"], "io_light")]
    assert session.scalars(select(SyncRoot.root_name)).all()
