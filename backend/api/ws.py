"""Console websocket channel: case updates, benchmark run progress, ops counters (file 08 §4.3, §7).

Protocol (JSON text frames):
  client → {"type": "auth", "token": "<Entra access token>"}        first frame, within AUTH_DEADLINE_S
  server → {"type": "ready", "user": {...}}
  client → {"type": "subscribe" | "unsubscribe", "topics": ["case", "run", "ops"]}
  server → {"type": "subscribed", "topics": [...]} | {"type": "error", "detail": "..."}
  server → {"type": "event", "topic": ..., "key": ..., "event": ..., "data": {...}, "at": ...}
Close codes: 4401 not authenticated or token expired (reconnect with a fresh token), 4400 bad frame.

Workers publish with `publish_event(redis_client, Event(...))` on EVENTS_CHANNEL; the API role runs
`redis_bridge(settings.redis_url)` in its lifespan and fans events out to subscribed sockets.
"""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError

from backend.api.auth import AuthConfig, AuthError, ConsoleUser, KeyResolver, Role, get_auth_config, get_key_resolver, verify_token

log = logging.getLogger(__name__)

EVENTS_CHANNEL = "dcl:console:events"
AUTH_DEADLINE_S = 5.0
CLOSE_UNAUTHENTICATED = 4401
CLOSE_BAD_FRAME = 4400


class Topic(StrEnum):
    CASE = "case"  # key = case_key; events: updated, resolved, reopened, siblings_resumed
    RUN = "run"  # key = benchmark run_id; events: progress, finished
    OPS = "ops"  # key = counter name; events: counters


TOPIC_ROLE = {Topic.CASE: Role.REVIEWER, Topic.RUN: Role.VIEWER, Topic.OPS: Role.VIEWER}


class Event(BaseModel):
    topic: Topic
    key: str
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def publish_event(redis_client: Any, event: Event) -> None:
    """For workers: publish one event to every API process (sync redis-py client)."""
    redis_client.publish(EVENTS_CHANNEL, event.model_dump_json())


class _Connection:
    def __init__(self, websocket: WebSocket, user: ConsoleUser, expires_at: int):
        self.websocket = websocket
        self.user = user
        self.expires_at = expires_at
        self.topics: set[Topic] = set()


class Hub:
    def __init__(self) -> None:
        self._connections: set[_Connection] = set()

    def add(self, connection: _Connection) -> None:
        self._connections.add(connection)

    def remove(self, connection: _Connection) -> None:
        self._connections.discard(connection)

    async def publish(self, event: Event) -> None:
        frame = {"type": "event", **event.model_dump(mode="json")}
        for connection in list(self._connections):
            if event.topic not in connection.topics:
                continue
            try:
                if time.time() >= connection.expires_at:
                    await connection.websocket.close(CLOSE_UNAUTHENTICATED, "token expired")
                    self.remove(connection)
                else:
                    await connection.websocket.send_json(frame)
            except Exception:  # a dead socket must not stop the fan-out
                self.remove(connection)


hub = Hub()
router = APIRouter(tags=["ws"])


async def _authenticate(websocket: WebSocket, config: AuthConfig, resolve_key: KeyResolver) -> tuple[ConsoleUser, int] | None:
    try:
        frame = await asyncio.wait_for(websocket.receive_json(), AUTH_DEADLINE_S)
    except (TimeoutError, json.JSONDecodeError):
        await websocket.close(CLOSE_UNAUTHENTICATED, "authenticate first")
        return None
    if not isinstance(frame, dict) or frame.get("type") != "auth" or not isinstance(frame.get("token"), str):
        await websocket.close(CLOSE_UNAUTHENTICATED, "authenticate first")
        return None
    try:
        return await run_in_threadpool(verify_token, frame["token"], config, resolve_key)
    except AuthError as exc:
        await websocket.close(CLOSE_UNAUTHENTICATED, exc.detail[:120])
        return None


def _parse_topics(frame: dict[str, Any]) -> list[Topic]:
    topics = frame.get("topics")
    if not isinstance(topics, list):
        raise ValueError("topics must be a list")
    return [Topic(t) for t in topics]


@router.websocket("/ws")
async def console_socket(
    websocket: WebSocket,
    config: AuthConfig = Depends(get_auth_config),
    resolve_key: KeyResolver = Depends(get_key_resolver),
) -> None:
    await websocket.accept()
    authenticated = await _authenticate(websocket, config, resolve_key)
    if authenticated is None:
        return
    user, expires_at = authenticated
    connection = _Connection(websocket, user, expires_at)
    hub.add(connection)
    await websocket.send_json({"type": "ready", "user": user.model_dump(mode="json")})
    try:
        while True:
            try:
                frame = await websocket.receive_json()
                kind = frame.get("type") if isinstance(frame, dict) else None
                if kind not in ("subscribe", "unsubscribe"):
                    raise ValueError(f"unknown frame type {kind!r}")
                topics = _parse_topics(frame)
            except (json.JSONDecodeError, ValueError) as exc:
                await websocket.close(CLOSE_BAD_FRAME, str(exc)[:120])
                return
            if kind == "unsubscribe":
                connection.topics.difference_update(topics)
            else:
                denied = [t for t in topics if not user.has(TOPIC_ROLE[t])]
                connection.topics.update(t for t in topics if t not in denied)
                if denied:
                    await websocket.send_json({"type": "error", "detail": f"not allowed: {', '.join(denied)}"})
            await websocket.send_json({"type": "subscribed", "topics": sorted(connection.topics)})
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(connection)


async def redis_bridge(redis_url: str) -> None:
    """Relay EVENTS_CHANNEL into the hub until cancelled. Started by main.py's lifespan (ROLE=api)."""
    from redis import asyncio as aioredis

    while True:
        client = aioredis.from_url(redis_url)
        try:
            async with client.pubsub() as pubsub:
                await pubsub.subscribe(EVENTS_CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        await hub.publish(Event.model_validate_json(message["data"]))
                    except ValidationError:
                        log.warning("dropping malformed console event")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("console event bridge lost redis; retrying in 5 s")
            await asyncio.sleep(5)
        finally:
            await client.aclose()
