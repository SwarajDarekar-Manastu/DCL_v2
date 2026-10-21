"""
title: Manastu engine actions
author: DCL (Manastu Space)
version: 0.1.0
required_open_webui_version: 0.12.3
requirements: httpx
description: Show trace and Report issue under Manastu engine answers; install as id manastu_actions.
"""

import html
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from frontend.openwebui.api_endpoint import (  # inline
    EngineError,
    Identity,
    find_trace,
    open_webui_groups,
    send_feedback,
)
from frontend.openwebui.config import DclConfigError, build_config  # inline

Emitter = Callable[[dict], Awaitable[Any]] | None

FEEDBACK_KINDS = [
    ("wrong_number", "Wrong number"),
    ("wrong_citation", "Wrong citation"),
    ("missing_document", "Missing document"),
    ("wrong_unit", "Wrong unit or extraction"),
    ("wrong_translation", "Wrong translation"),
]
REPORT_PROMPT = "Start with the number of the reason, then describe the problem:\n" + "\n".join(
    f"{i}. {label}" for i, (_, label) in enumerate(FEEDBACK_KINDS, start=1)
)
TRACE_CSS = "".join(
    [
        "body{font:13px system-ui,sans-serif;margin:0;padding:8px;color:#1e293b}",
        "h2{font-size:14px;margin:0 0 4px}h3{font-size:12px;margin:10px 0 4px;color:#475569}",
        "table{border-collapse:collapse;width:100%}",
        "td,th{border:1px solid #d8dee6;padding:3px 6px;text-align:left;vertical-align:top}",
        "code{font-size:11px;word-break:break-all}.meta{color:#64748b}",
        "@media (prefers-color-scheme:dark){body{color:#e2e8f0}td,th{border-color:#334155}}",
    ]
)
HEIGHT_SCRIPT = (
    "<script>(function(){function h(){parent.postMessage({type:'iframe:height',"
    "height:document.documentElement.scrollHeight},'*')}window.addEventListener('load',h);h()})();</script>"
)


def parse_report(text: str) -> tuple[str, str | None] | None:
    """'4 the unit is psia' → ('wrong_unit', 'the unit is psia'); None if no reason number."""
    match = re.match(r"\s*([1-5])(?![0-9])[\s.:)\-]*(.*)", text or "", re.S)
    if not match:
        return None
    comment = match.group(2).strip()
    return FEEDBACK_KINDS[int(match.group(1)) - 1][0], comment[:4000] or None


def _e(value: Any) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return html.escape("" if value is None else str(value))


def _link(url: Any, label: Any) -> str:
    if isinstance(url, str) and url.startswith(("http://", "https://", "/")):
        return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{_e(label)}</a>'
    return _e(label)


def trace_html(trace: dict) -> str:
    """The Show-trace timeline (file 08 §2.2) as self-contained HTML; every value is escaped."""

    def row(*cells: str) -> str:
        return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"

    def code(value: Any) -> str:
        return f"<code>{_e(value)}</code>"

    rows_tools = "".join(
        row(
            _e(t.get("tool") or t.get("name")),
            _e(t.get("duration_ms")),
            _e(t.get("status", "")),
            code(t.get("arguments") or t.get("args")),
        )
        for t in trace.get("tool_calls") or []
    )
    rows_retrieved = "".join(
        row(
            _e(r.get("rank")),
            _e(r.get("score")),
            _link(r.get("url_viewer"), r.get("title") or r.get("doc_id")),
            code(r.get("anchor")),
        )
        for r in trace.get("retrieved") or []
    )
    rows_claims = "".join(
        row(_e(c.get("verdict", "")), _e(c.get("kind", "")), _e(c.get("text")))
        for c in trace.get("claims") or []
    )
    verifier = trace.get("verifier_result") or {}
    summary = ", ".join(f"{_e(k)} {_e(v)}" for k, v in verifier.items() if not isinstance(v, (dict, list)))
    latency = trace.get("latency_ms")

    def table(title: str, head: str, rows: str) -> str:
        if not rows:
            return ""
        return f"<h3>{title}</h3><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"

    return (
        "<!doctype html><meta charset='utf-8'><style>" + TRACE_CSS + "</style>"
        f"<h2>Trace {_e(trace.get('trace_id'))}</h2>"
        f"<p class='meta'>{_e(trace.get('question'))}"
        f"{' · ' + _e(latency) + ' ms' if latency is not None else ''}"
        f"{' · verifier: ' + summary if summary else ''}</p>"
        + table("Tool calls", "<th>Tool</th><th>ms</th><th>Status</th><th>Arguments</th>", rows_tools)
        + table("Retrieved", "<th>Rank</th><th>Score</th><th>Document</th><th>Anchor</th>", rows_retrieved)
        + table("Claims", "<th>Verdict</th><th>Kind</th><th>Claim</th>", rows_claims)
        + HEIGHT_SCRIPT
    )


class Action:
    actions = [
        {"id": "show_trace", "name": "Show trace"},
        {"id": "report_issue", "name": "Report issue"},
    ]

    class Valves(BaseModel):
        ENGINE_URL: str = Field(default="", description="DCL backend base URL, e.g. http://dcl-api:8200")
        ENGINE_SHARED_SECRET: str = Field(
            default="", description="DCL_PIPE_SHARED_SECRET (HMAC identity headers)"
        )

    def __init__(self):
        self.valves = self.Valves()
        self.http_client = None  # tests inject a mock transport here

    async def _groups_of(self, user_id: str) -> tuple[str, ...]:
        return await open_webui_groups(user_id)

    async def action(
        self,
        body: dict,
        __user__: dict | None = None,
        __event_emitter__: Emitter = None,
        __event_call__: Emitter = None,
        __id__: str | None = None,
    ):
        async def notify(kind: str, content: str) -> None:
            if __event_emitter__:
                await __event_emitter__({"type": "notification", "data": {"type": kind, "content": content}})

        try:
            config = build_config(self.valves.ENGINE_URL, self.valves.ENGINE_SHARED_SECRET)
        except DclConfigError as exc:
            await notify("error", str(exc))
            return None
        user = __user__ or {}
        identity = Identity(
            user_id=str(user.get("id", "")),
            email=str(user.get("email", "")),
            groups=await self._groups_of(str(user.get("id", ""))),
        )
        chat_id, message_id = str(body.get("chat_id") or ""), str(body.get("id") or "")

        try:
            trace = await find_trace(config, identity, chat_id, message_id, self.http_client)
        except EngineError as exc:
            reason = {404: "This answer has no engine trace.", 501: "Traces are not available yet."}
            await notify("warning", reason.get(exc.status, exc.detail))
            return None

        if __id__ == "report_issue":
            reply = None
            if __event_call__:
                reply = await __event_call__(
                    {
                        "type": "input",
                        "data": {
                            "title": "Report an issue with this answer",
                            "message": REPORT_PROMPT,
                            "placeholder": "4 the chamber pressure is psia, not psig",
                        },
                    }
                )
            if not isinstance(reply, str) or not reply.strip():
                return None  # cancelled, timed out or empty: nothing is sent
            parsed = parse_report(reply)
            if parsed is None:
                await notify("warning", "Start the report with the number of the reason (1 to 5).")
                return None
            kind, comment = parsed
            try:
                await send_feedback(
                    config, identity, trace["trace_id"], kind, comment, None, self.http_client
                )
            except EngineError as exc:
                await notify("error", f"The report could not be recorded: {exc.detail}")
                return None
            await notify("success", "Thank you, the report was recorded for review.")
            return None

        return HTMLResponse(content=trace_html(trace), headers={"Content-Disposition": "inline"})
