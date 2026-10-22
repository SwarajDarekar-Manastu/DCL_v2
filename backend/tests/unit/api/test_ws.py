import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api import auth, ws
from backend.api.ws import Event, Topic

REVIEWERS = "group-reviewers"


@pytest.fixture
def client(monkeypatch, auth_config, key_resolver):
    monkeypatch.setattr(ws, "AUTH_DEADLINE_S", 0.2)
    monkeypatch.setattr(ws, "hub", ws.Hub())
    app = FastAPI()
    app.include_router(ws.router)
    app.dependency_overrides[auth.get_auth_config] = lambda: auth_config
    app.dependency_overrides[auth.get_key_resolver] = lambda: key_resolver
    return TestClient(app)


def publish(socket, event: Event) -> None:
    socket.portal.call(ws.hub.publish, event)


def test_no_auth_frame_closes_4401(client, token):
    with client.websocket_connect("/ws") as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == 4401


def test_wrong_first_frame_closes_4401(client, token):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "subscribe", "topics": ["ops"]})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == 4401


def test_invalid_token_closes_4401(client, token):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": token(aud="api://other")})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == 4401


def test_delivers_only_subscribed_topics(client, token):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": token(groups=[REVIEWERS])})
        ready = socket.receive_json()
        assert ready["type"] == "ready"
        assert ready["user"]["roles"] == ["viewer", "reviewer"]
        socket.send_json({"type": "subscribe", "topics": ["case"]})
        assert socket.receive_json() == {"type": "subscribed", "topics": ["case"]}

        publish(socket, Event(topic=Topic.OPS, key="queue_depth", event="counters", data={"io_light": 3}))
        resolved = Event(topic=Topic.CASE, key="doc-1:4", event="resolved", data={"siblings_resumed": 3})
        publish(socket, resolved)
        frame = socket.receive_json()
        assert frame["type"] == "event"
        assert frame["topic"] == "case"
        assert frame["key"] == "doc-1:4"
        assert frame["data"] == {"siblings_resumed": 3}


def test_viewer_cannot_subscribe_to_cases(client, token):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": token()})
        socket.receive_json()
        socket.send_json({"type": "subscribe", "topics": ["case", "ops"]})
        assert socket.receive_json() == {"type": "error", "detail": "not allowed: case"}
        assert socket.receive_json() == {"type": "subscribed", "topics": ["ops"]}


def test_unknown_topic_closes_4400(client, token):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": token()})
        socket.receive_json()
        socket.send_json({"type": "subscribe", "topics": ["nope"]})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == 4400


def test_expired_token_closes_on_next_event(client, token, monkeypatch):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": token(lifetime_s=30)})
        socket.receive_json()
        socket.send_json({"type": "subscribe", "topics": ["ops"]})
        socket.receive_json()
        monkeypatch.setattr(ws.time, "time", lambda: 10**12)
        publish(socket, Event(topic=Topic.OPS, key="k", event="counters"))
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == 4401


def test_publish_event_writes_the_channel():
    sent = []

    class FakeRedis:
        def publish(self, channel, payload):
            sent.append((channel, payload))

    ws.publish_event(FakeRedis(), Event(topic=Topic.RUN, key="run-1", event="progress", data={"done": 4}))
    channel, payload = sent[0]
    assert channel == "dcl:console:events"
    assert Event.model_validate_json(payload).data == {"done": 4}


def test_dev_token_opens_the_socket(client, monkeypatch):
    from backend.api.auth import ConsoleRole, DevAuth

    client.app.dependency_overrides[auth.get_dev_auth] = lambda: DevAuth(
        token="d" * 40, roles=[ConsoleRole.REVIEWER]
    )
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": "d" * 40})
        ready = socket.receive_json()
        assert ready["type"] == "ready" and ready["user"]["oid"] == "dev-sign-in"
        socket.send_json({"type": "subscribe", "topics": ["case"]})
        assert socket.receive_json() == {"type": "subscribed", "topics": ["case"]}
