"""
title: Manastu Propulsion Engine
author: DCL (Manastu Space)
version: 0.1.0
required_open_webui_version: 0.12.3
requirements: httpx
description: The DCL Answer Engine as a chat model (file 08 §2.1); install as function id manastu_engine.
"""

import html
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from frontend.openwebui.api_endpoint import EngineError, Identity, confirm, stream_answer  # inline
from frontend.openwebui.config import DclConfigError, build_config  # inline

Emitter = Callable[[dict], Awaitable[Any]] | None

PROVENANCE_LABEL = {
    "measured": "measured",
    "internal_report": "internal report",
    "standard": "standard",
    "vendor_claim": "vendor claim",
    "literature": "literature",
    "web": "web",
}
# Open WebUI sizes an embed iframe from this message (file 08 §1, Rich UI embedding).
HEIGHT_SCRIPT = (
    "<script>(function(){function h(){parent.postMessage({type:'iframe:height',"
    "height:document.documentElement.scrollHeight},'*')}window.addEventListener('load',h);h()})();</script>"
)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def engine_messages(messages: list[dict]) -> list[dict]:
    """Open WebUI messages → engine ChatMessage list (text only; tool and image parts are dropped)."""
    out = []
    for message in messages:
        role = message.get("role")
        text = _text_of(message.get("content"))
        if role in ("user", "assistant", "system") and text.strip():
            out.append({"role": role, "content": text})
    return out


def viewer_url(citation: dict, console_url: str) -> str | None:
    if citation.get("url_viewer"):
        return citation["url_viewer"]
    if citation.get("doc_id") and console_url:
        anchor = citation.get("anchor")
        suffix = f"?anchor={quote(anchor, safe=':!')}" if anchor else ""
        return f"{console_url}/docs/{citation['doc_id']}/viewer{suffix}"
    return citation.get("url_onedrive") or citation.get("url_asset")


def group_sources(citations: list[dict], console_url: str) -> list[dict]:
    """One Open WebUI `source` per document, every cited passage of it in `document[]` (file 08 §2.1)."""
    grouped: dict[str, dict] = {}
    for c in citations:
        url = viewer_url(c, console_url)
        key = c.get("doc_id") or url or c.get("title", "")
        marks = [PROVENANCE_LABEL.get(c.get("provenance", ""), c.get("provenance", ""))]
        if c.get("translated"):
            marks.append(f"translated from {c.get('language') or 'another language'}")
        if c.get("needs_review"):
            marks.append("⚠ unverified extraction")
        source = grouped.setdefault(
            key,
            {"source": {"id": key, "name": c.get("title", ""), "url": url}, "document": [], "metadata": []},
        )
        source["document"].append(c.get("quote") or c.get("label") or c.get("title", ""))
        source["metadata"].append(
            {
                "source": c.get("title", ""),
                "name": f"[{c.get('citation_id')}] {c.get('label', '')} ({', '.join(m for m in marks if m)})",
                "url": url,
            }
        )
    return list(grouped.values())


def embed_html(event: dict) -> str | None:
    if event.get("html"):
        return event["html"] if "iframe:height" in event["html"] else event["html"] + HEIGHT_SCRIPT
    if event.get("url"):
        alt = html.escape(event.get("alt", ""))
        return (
            '<figure style="margin:0;font:13px system-ui">'
            f'<img src="{html.escape(event["url"], quote=True)}" alt="{alt}" style="max-width:100%">'
            f"<figcaption>{alt}</figcaption></figure>{HEIGHT_SCRIPT}"
        )
    return None


def tool_block(step: dict) -> str:
    name = html.escape(step.get("tool") or step.get("name", ""), quote=True)
    took = f" · {step['duration_ms']} ms" if step.get("duration_ms") is not None else ""
    summary = html.escape(f"{step.get('description', '')}{took}")
    return (
        f'\n<details type="tool_calls" done="true" name="{name}">\n<summary>{summary}</summary>\n</details>\n'
    )


class Pipe:
    class Valves(BaseModel):
        ENGINE_URL: str = Field(default="", description="DCL backend base URL, e.g. http://dcl-api:8200")
        ENGINE_SHARED_SECRET: str = Field(
            default="", description="DCL_PIPE_SHARED_SECRET (HMAC identity headers)"
        )
        CONSOLE_URL: str = Field(default="", description="DCL Console base URL for citation links")
        DEFAULT_THINKING_LEVEL: Literal["", "minimal", "low", "medium", "high"] = ""
        SHOW_STATUS_EVENTS: bool = True
        MAX_EMBEDS_PER_MESSAGE: int = Field(default=6, ge=0, le=20)

    class UserValves(BaseModel):
        strict_numbers: bool = Field(default=False, description="Never accept unverified values")
        show_debug_trace: bool = Field(default=False, description="Show tool runs under the answer")

    def __init__(self):
        self.valves = self.Valves()
        self.http_client: httpx.AsyncClient | None = None  # tests inject a mock transport here
        self._followups: dict[str, list[str]] = {}

    def pipes(self) -> list[dict]:
        return [{"id": "main", "name": "Manastu Propulsion Engine"}]

    async def _groups_of(self, user_id: str) -> tuple[str, ...]:
        try:
            from open_webui.models.groups import Groups
        except ImportError:
            return ()
        return tuple(sorted(group.name for group in await Groups.get_groups_by_member_id(user_id)))

    def _task_reply(self, task: str, messages: list[dict], chat_id: str) -> str:
        """Open WebUI's own background tasks never reach the engine."""
        if task == "title_generation":
            last = next(
                (m["content"] for m in reversed(engine_messages(messages)) if m["role"] == "user"), ""
            )
            return json.dumps({"title": " ".join(last.split()[:8]) or "Propulsion question"})
        if task == "tags_generation":
            return json.dumps({"tags": []})
        if task == "follow_up_generation":
            return json.dumps({"follow_ups": self._followups.get(chat_id, [])})
        return ""

    async def pipe(
        self,
        body: dict,
        __user__: dict | None = None,
        __event_emitter__: Emitter = None,
        __event_call__: Emitter = None,
        __metadata__: dict | None = None,
        __task__: str | None = None,
    ) -> AsyncIterator[str | dict]:
        metadata = __metadata__ or {}
        chat_id = str(metadata.get("chat_id") or "")
        message_id = str(metadata.get("message_id") or "")
        if __task__:
            yield self._task_reply(str(__task__), body.get("messages", []), chat_id)
            return

        async def emit(kind: str, data: dict) -> None:
            if __event_emitter__:
                await __event_emitter__({"type": kind, "data": data})

        try:
            config = build_config(
                self.valves.ENGINE_URL, self.valves.ENGINE_SHARED_SECRET, self.valves.CONSOLE_URL
            )
        except DclConfigError as exc:
            yield {"error": {"detail": str(exc)}}
            return

        user = __user__ or {}
        user_valves = user.get("valves") or self.UserValves()
        identity = Identity(
            user_id=str(user.get("id", "")),
            email=str(user.get("email", "")),
            groups=await self._groups_of(str(user.get("id", ""))),
        )
        request = {
            "messages": engine_messages(body.get("messages", [])),
            "chat_id": chat_id,
            "message_id": message_id,
            "attachments": [],  # chat attachments need an upload endpoint (open question to the Lead)
            "options": {
                "thinking_level": self.valves.DEFAULT_THINKING_LEVEL or None,
                "strict_numbers": bool(getattr(user_valves, "strict_numbers", False)),
                "show_debug_trace": bool(getattr(user_valves, "show_debug_trace", False)),
                "max_embeds": self.valves.MAX_EMBEDS_PER_MESSAGE,
            },
        }

        streamed: list[str] = []
        citations: list[dict] = []
        embeds = 0
        sources_sent = False

        async def flush_sources() -> None:
            nonlocal sources_sent
            if not sources_sent:
                sources_sent = True
                for source in group_sources(citations, config.console_url):
                    await emit("source", source)

        try:
            async for kind, data in stream_answer(config, identity, request, self.http_client):
                if kind == "step":
                    if self.valves.SHOW_STATUS_EVENTS:
                        await emit("status", {"description": data.get("description", ""), "done": False})
                    if request["options"]["show_debug_trace"] and data.get("done") and data.get("tool"):
                        yield tool_block(data)
                elif kind == "token":
                    streamed.append(data.get("text", ""))
                    yield data.get("text", "")
                elif kind == "citation":
                    citations.append(data)
                elif kind == "embed":
                    content = embed_html(data)
                    if content and embeds < self.valves.MAX_EMBEDS_PER_MESSAGE:
                        embeds += 1
                        await emit("embeds", {"embeds": [content]})
                elif kind == "needs_confirmation":
                    reply = None
                    if __event_call__:
                        reply = await __event_call__(
                            {
                                "type": "confirmation",
                                "data": {"title": data.get("title", ""), "message": data.get("message", "")},
                            }
                        )
                    accepted = reply is True
                    if data.get("trace_id"):
                        await confirm(
                            config,
                            identity,
                            data["trace_id"],
                            data["confirmation_id"],
                            accepted,
                            self.http_client,
                        )
                    else:
                        await emit(
                            "notification",
                            {
                                "type": "warning",
                                "content": "The engine asked to confirm without a trace id; declined.",
                            },
                        )
                elif kind == "done":
                    text = "".join(streamed)
                    if not text.strip():
                        yield data.get("answer_markdown", "")
                        text = data.get("answer_markdown", "")
                    caveats = [c for c in data.get("caveats", []) if c and c not in text]
                    if caveats:
                        yield "\n\n" + "\n".join(f"> ⚠ {c}" for c in caveats)
                    await flush_sources()
                    followups = [f for f in data.get("followups", []) if isinstance(f, str)]
                    if chat_id:
                        self._followups[chat_id] = followups
                    if followups:
                        await emit("chat:message:follow_ups", {"follow_ups": followups})
                    if self.valves.SHOW_STATUS_EVENTS:
                        await emit(
                            "status",
                            {
                                "description": "Answer verified" if data.get("verifier") else "Done",
                                "done": True,
                            },
                        )
                elif kind == "error":
                    await flush_sources()
                    yield {"error": {"detail": data.get("message") or "the engine reported an error"}}
                    return
            await flush_sources()
        except EngineError as exc:
            await flush_sources()
            detail = "The answer engine is not available yet." if exc.status == 501 else exc.detail
            yield {"error": {"detail": detail}}
