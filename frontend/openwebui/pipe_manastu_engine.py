"""
title: Manastu Propulsion Engine
author: DCL (Manastu Space)
version: 0.1.0
required_open_webui_version: 0.12.3
requirements: httpx
description: The DCL Answer Engine as a chat model (file 08 §2.1); install as function id manastu_engine.
"""

import asyncio
import html
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from frontend.openwebui.api_endpoint import (  # inline
    EngineError,
    Identity,
    confirm,
    open_webui_groups,
    put_upload,
    request_upload,
    skill_playbook,
    stream_answer,
)
from frontend.openwebui.config import DclConfigError, build_config  # inline

Emitter = Callable[[dict], Awaitable[Any]] | None

PROVENANCE_LABEL = {
    "measured": "measured",
    "internal_report": "internal report",
    "standard": "standard",
    "vendor_claim": "vendor claim",
    "literature": "literature",
    "web": "web",
    "calculation": "calculation",  # physics calculator results (RocketCEA, nozzle sizing), file 07 §5
    "user_provided": "your attachment",  # a file attached to the chat message (never indexed)
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


# Skill mentions as Open WebUI v0.12.3 writes them into message text: <$skillId|label> or </skillId|label>
# (open_webui/utils/skills.py SKILL_ID_RE and SKILL_MENTION_RE).
SKILL_ID = r"(?:[a-z0-9_-]+|terminal:[^|>\s]+)"
SKILL_MENTION = re.compile(rf"<(?:\$({SKILL_ID})(?:\|([^>]*))?|/({SKILL_ID})\|([^>]*))>")


def without_skill_mentions(text: str) -> str:
    """The engine reads plain text: a mention tag becomes its label (or the skill id without one)."""
    return SKILL_MENTION.sub(lambda m: m.group(2) or m.group(4) or m.group(1) or m.group(3), text)


def mentioned_skills(messages: list[dict], metadata: dict) -> list[str]:
    """Skills $-mentioned in the last user message, in order, then any other ids Open WebUI listed."""
    last = next((_text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
    ids = [m.group(1) or m.group(3) for m in SKILL_MENTION.finditer(last)]
    listed = (metadata.get("chat_context") or {}).get("mentioned_skill_ids") or []
    return list(dict.fromkeys([*ids, *sorted(str(i) for i in listed)]))


def engine_messages(messages: list[dict]) -> list[dict]:
    """Open WebUI messages → engine ChatMessage list (text only; tool and image parts are dropped)."""
    out = []
    for message in messages:
        role = message.get("role")
        text = without_skill_mentions(_text_of(message.get("content")))
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
                "name": source_name(c, marks),
                "url": url,
            }
        )
    return list(grouped.values())


def source_name(citation: dict, marks: list[str]) -> str:
    """'[1] Test Report 37, p. 8 (internal report)'; a mark already in the engine's label is not repeated."""
    label = str(citation.get("label", ""))
    extra = [m for m in marks if m and f"({m})" not in label]
    return f"[{citation.get('citation_id')}] {label}" + (f" ({', '.join(extra)})" if extra else "")


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


def _history_question(messages: list[dict]) -> str:
    """The first user line of the ``<chat_history>`` block Open WebUI puts in its task templates."""
    text = next(
        (m.get("content") for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)),
        "",
    )
    history = (
        text.split("<chat_history>", 1)[1].split("</chat_history>", 1)[0] if "<chat_history>" in text else ""
    )
    for line in history.splitlines():
        if line.strip().upper().startswith("USER:"):
            return line.strip()[5:].strip()
    return ""


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
        MAX_ATTACHMENT_MB: int = Field(default=25, ge=0, le=25, description="larger chat files are not sent")

    class UserValves(BaseModel):
        strict_numbers: bool = Field(default=False, description="Never accept unverified values")
        show_debug_trace: bool = Field(default=False, description="Show tool runs under the answer")

    def __init__(self):
        self.valves = self.Valves()
        self.http_client: httpx.AsyncClient | None = None  # tests inject a mock transport here
        self._followups: dict[str, list[str]] = {}
        self._questions: dict[str, str] = {}  # each chat's first question, for its title

    def pipes(self) -> list[dict]:
        return [{"id": "main", "name": "Manastu Propulsion Engine"}]

    async def _groups_of(self, user_id: str) -> tuple[str, ...]:
        return await open_webui_groups(user_id)

    async def _read_attachment(self, item: dict, user_id: str) -> tuple[str, str, bytes] | None:
        """(name, mime type, bytes) of a file the user attached, read from Open WebUI's own storage."""
        file_id = item.get("id") or (item.get("file") or {}).get("id")
        if not file_id:
            return None
        try:
            from open_webui.models.files import Files
            from open_webui.storage.provider import Storage
        except ImportError:
            return None
        record = await Files.get_file_by_id(file_id)
        if record is None or record.user_id != user_id or not record.path:
            return None  # only the requesting user's own files
        local_path = await asyncio.to_thread(Storage.get_file, record.path)
        content = await asyncio.to_thread(Path(local_path).read_bytes)
        meta = record.meta or {}
        return record.filename, meta.get("content_type") or "application/octet-stream", content

    async def _upload_attachments(self, files: list[dict], config, identity: Identity, emit) -> list[dict]:
        """Chat files → presigned uploads the engine can fetch once (answer-time only, never indexed)."""
        attachments = []
        cap = self.valves.MAX_ATTACHMENT_MB * 1024 * 1024
        for item in files:
            try:
                found = await self._read_attachment(item, identity.user_id)
                if found is None:
                    continue
                name, mime, content = found
                if len(content) > cap:
                    await emit(
                        "notification",
                        {
                            "type": "warning",
                            "content": f"{name} is over {self.valves.MAX_ATTACHMENT_MB} MB and was not sent.",
                        },
                    )
                    continue
                slot = await request_upload(config, identity, name, mime, len(content), self.http_client)
                await put_upload(config, slot["upload_url"], content, mime, self.http_client)
                attachments.append({"name": name, "mime_type": mime, "url": slot["get_url"]})
            except (EngineError, OSError, KeyError) as exc:
                detail = exc.detail if isinstance(exc, EngineError) else type(exc).__name__
                await emit(
                    "notification",
                    {"type": "warning", "content": f"An attachment could not be sent ({detail})."},
                )
        return attachments

    async def _playbook_hint(self, skill_ids: list[str]) -> str | None:
        """The intent of the first mentioned skill that is a DCL playbook (tag dcl-playbook:<intent>)."""
        for skill_id in skill_ids:
            try:
                intent = await self._skill_playbook(skill_id)
            except Exception:  # an unreadable skill must not block the answer
                intent = None
            if intent:
                return intent
        return None

    async def _skill_playbook(self, skill_id: str) -> str | None:
        return await skill_playbook(skill_id)

    def _task_reply(self, task: str, messages: list[dict], chat_id: str) -> str:
        """Open WebUI's own background tasks never reach the engine."""
        if task == "title_generation":
            # The task's own message is Open WebUI's instruction template, never the user's question.
            question = self._questions.get(chat_id) or _history_question(messages)
            return json.dumps({"title": " ".join(question.split()[:8]) or "Propulsion question"})
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
        __files__: list[dict] | None = None,
    ) -> AsyncIterator[str | dict]:
        metadata = __metadata__ or {}
        chat_id = str(metadata.get("chat_id") or "")
        message_id = str(metadata.get("message_id") or "")
        if __task__:
            yield self._task_reply(str(__task__), body.get("messages", []), chat_id)
            return
        first = next(
            (m["content"] for m in engine_messages(body.get("messages", [])) if m["role"] == "user"), ""
        )
        if chat_id and first and isinstance(first, str):
            self._questions.setdefault(chat_id, first)

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
            "attachments": await self._upload_attachments(__files__ or [], config, identity, emit),
            "options": {
                "thinking_level": self.valves.DEFAULT_THINKING_LEVEL or None,
                "strict_numbers": bool(getattr(user_valves, "strict_numbers", False)),
                "show_debug_trace": bool(getattr(user_valves, "show_debug_trace", False)),
                "max_embeds": self.valves.MAX_EMBEDS_PER_MESSAGE,
            },
        }
        hint = await self._playbook_hint(mentioned_skills(body.get("messages", []), metadata))
        if hint:
            request["options"]["playbook_hint"] = hint

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
