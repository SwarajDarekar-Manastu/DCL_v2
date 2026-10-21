"""Every call from the Open WebUI functions to the DCL backend; the Python mirror of api_endpoint.ts.

Identity: each request carries X-DCL-User-* headers signed with the shared secret, exactly as
`backend.api.engine.sign_identity` computes them (file 08 §2.3); the engine never trusts an unsigned identity.
"""

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from frontend.openwebui.config import DclConfig  # inline


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str
    groups: tuple[str, ...]


class EngineError(Exception):
    def __init__(self, status: int | None, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


async def open_webui_groups(user_id: str) -> tuple[str, ...]:
    """The user's Open WebUI group names (mirrored from Entra ID); empty outside Open WebUI."""
    try:
        from open_webui.models.groups import Groups
    except ImportError:
        return ()
    return tuple(sorted(group.name for group in await Groups.get_groups_by_member_id(user_id)))


def sign_identity(secret: str, timestamp: str, user_id: str, email: str, groups: str, body: bytes) -> str:
    message = f"{timestamp}\n{user_id}\n{email}\n{groups}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def identity_headers(
    config: DclConfig, identity: Identity, body: bytes, now: float | None = None
) -> dict[str, str]:
    timestamp = str(int(now if now is not None else time.time()))
    groups = ",".join(identity.groups)
    return {
        "X-DCL-User-Id": identity.user_id,
        "X-DCL-User-Email": identity.email,
        "X-DCL-User-Groups": groups,
        "X-DCL-Timestamp": timestamp,
        "X-DCL-Signature": sign_identity(
            config.shared_secret, timestamp, identity.user_id, identity.email, groups, body
        ),
    }


@asynccontextmanager
async def _client(config: DclConfig, client: httpx.AsyncClient | None):
    if client is not None:
        yield client
        return
    timeout = httpx.Timeout(config.read_timeout_s, connect=config.connect_timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as owned:
        yield owned


def _detail(status: int, raw: bytes) -> str:
    try:
        detail = json.loads(raw).get("detail")
        if isinstance(detail, str):
            return detail
    except (ValueError, AttributeError):
        pass
    return f"engine answered HTTP {status}"


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict]]:
    """Server-sent events → (event name, JSON data). Multi-line data is joined; comments are skipped."""
    event, data = "message", []
    async for line in lines:
        if line == "":
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
    if data:
        yield event, json.loads("\n".join(data))


async def stream_answer(
    config: DclConfig, identity: Identity, request: dict, client: httpx.AsyncClient | None = None
) -> AsyncIterator[tuple[str, dict]]:
    """POST /v1/answer and yield its SSE events (backend/api/engine.py)."""
    body = json.dumps(request).encode()
    headers = identity_headers(config, identity, body) | {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    try:
        async with _client(config, client) as http:
            url = f"{config.engine_url}/v1/answer"
            async with http.stream("POST", url, content=body, headers=headers) as response:
                if response.status_code != 200:
                    raw = await response.aread()
                    raise EngineError(response.status_code, _detail(response.status_code, raw))
                async for item in parse_sse(response.aiter_lines()):
                    yield item
    except httpx.TransportError as exc:
        raise EngineError(None, f"engine unreachable: {type(exc).__name__}") from exc


async def confirm(
    config: DclConfig,
    identity: Identity,
    trace_id: str,
    confirmation_id: str,
    accepted: bool,
    client: httpx.AsyncClient | None = None,
) -> None:
    """POST /v1/answer/{trace_id}/confirm."""
    body = json.dumps({"confirmation_id": confirmation_id, "accepted": accepted}).encode()
    headers = identity_headers(config, identity, body) | {"Content-Type": "application/json"}
    async with _client(config, client) as http:
        url = f"{config.engine_url}/v1/answer/{trace_id}/confirm"
        response = await http.post(url, content=body, headers=headers)
    if response.status_code >= 300:
        raise EngineError(response.status_code, _detail(response.status_code, response.content))


async def find_trace(
    config: DclConfig,
    identity: Identity,
    chat_id: str,
    message_id: str,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """GET /v1/traces?chat_id=&message_id= (the Show trace action knows the message, not the trace id)."""
    headers = identity_headers(config, identity, b"")
    params = {"chat_id": chat_id, "message_id": message_id}
    async with _client(config, client) as http:
        response = await http.get(f"{config.engine_url}/v1/traces", params=params, headers=headers)
    if response.status_code != 200:
        raise EngineError(response.status_code, _detail(response.status_code, response.content))
    return response.json()


async def send_feedback(
    config: DclConfig,
    identity: Identity,
    trace_id: str,
    kind: str,
    comment: str | None,
    citation_id: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    """POST /v1/traces/{trace_id}/feedback (the Report issue action)."""
    body = json.dumps({"kind": kind, "comment": comment, "citation_id": citation_id}).encode()
    headers = identity_headers(config, identity, body) | {"Content-Type": "application/json"}
    async with _client(config, client) as http:
        response = await http.post(
            f"{config.engine_url}/v1/traces/{trace_id}/feedback", content=body, headers=headers
        )
    if response.status_code >= 300:
        raise EngineError(response.status_code, _detail(response.status_code, response.content))


async def create_benchmark_draft(
    config: DclConfig, identity: Identity, draft: dict, client: httpx.AsyncClient | None = None
) -> dict:
    """POST /benchmark/drafts (backend/api/benchmark.py): a draft case a reviewer approves in the Console."""
    body = json.dumps(draft).encode()
    headers = identity_headers(config, identity, body) | {"Content-Type": "application/json"}
    async with _client(config, client) as http:
        response = await http.post(f"{config.engine_url}/benchmark/drafts", content=body, headers=headers)
    if response.status_code != 201:
        raise EngineError(response.status_code, _detail(response.status_code, response.content))
    return response.json()


async def get_trace(
    config: DclConfig, identity: Identity, trace_id: str, client: httpx.AsyncClient | None = None
) -> dict:
    """GET /v1/traces/{trace_id} (the Show trace action)."""
    headers = identity_headers(config, identity, b"")
    async with _client(config, client) as http:
        response = await http.get(f"{config.engine_url}/v1/traces/{trace_id}", headers=headers)
    if response.status_code != 200:
        raise EngineError(response.status_code, _detail(response.status_code, response.content))
    return response.json()


async def request_upload(
    config: DclConfig,
    identity: Identity,
    file_name: str,
    mime_type: str,
    size_bytes: int,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """POST /assets/upload → {object_uri, upload_url, get_url, expires_in_s} (backend/api/assets.py)."""
    body = json.dumps({"file_name": file_name, "mime_type": mime_type, "size_bytes": size_bytes}).encode()
    headers = identity_headers(config, identity, body) | {"Content-Type": "application/json"}
    async with _client(config, client) as http:
        response = await http.post(f"{config.engine_url}/assets/upload", content=body, headers=headers)
    if response.status_code != 201:
        raise EngineError(response.status_code, _detail(response.status_code, response.content))
    return response.json()


async def put_upload(
    config: DclConfig,
    upload_url: str,
    content: bytes,
    mime_type: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    """PUT the file bytes to the presigned URL the backend handed out."""
    async with _client(config, client) as http:
        response = await http.put(upload_url, content=content, headers={"Content-Type": mime_type})
    if response.status_code >= 300:
        raise EngineError(response.status_code, f"upload refused by storage (HTTP {response.status_code})")
