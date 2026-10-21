"""S2: the Answer Engine API (file 07, file 08 §2.1): `POST /v1/answer` (SSE) and `GET /v1/traces/{trace_id}`.

This module fixes the wire contract the Open WebUI Pipe (S3) codes against: the request body, the signed
identity headers, and the SSE events. Each event is `event: <type>` plus one `data:` line of JSON:

| event                | Pipe maps it to (file 08 §2.1)                                          |
|----------------------|-------------------------------------------------------------------------|
| `step`               | `status` (done=false while running)                                     |
| `token`              | streamed answer text                                                    |
| `citation`           | `source` (grouped per document, metadata url = Console viewer deep link) |
| `embed`              | `embeds` (HTML with the iframe height script) or a link                 |
| `needs_confirmation` | `__event_call__` confirmation; reply to `POST /v1/answer/{trace_id}/confirm`  |
| `done`               | end of stream; final markdown, mode, verifier summary, usage            |
| `error`              | the Pipe raises so Open WebUI shows an error state                      |

Identity (file 08 §2.3): the Pipe signs every request with `DCL_PIPE_SHARED_SECRET`; the engine never
trusts an unsigned identity. Signature = hex HMAC-SHA256 over
`"{timestamp}\\n{user_id}\\n{email}\\n{groups}\\n{sha256_hex(body)}"`, groups comma-separated as sent.
"""

import hashlib
import hmac
import json
import time
import uuid
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.config import Group, get_settings

MAX_CLOCK_SKEW_S = 300
SSE_MEDIA_TYPE = "text/event-stream"

router = APIRouter(prefix="/v1", tags=["engine"])


# ---------------------------------------------------------------- request


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class Attachment(BaseModel):
    """A file the user attached in chat, uploaded by the Pipe; answer-time only, never indexed."""

    name: str
    mime_type: str
    url: str = Field(description="presigned GET URL the engine can fetch once")


class BenchmarkMode(BaseModel):
    """Set by the Console benchmark runner (file 08 §5.6); same code path as chat."""

    case_id: str
    case_version: int
    external_search: Literal["mock", "allow"] = "mock"
    clarification_answer: str | None = None


class AnswerOptions(BaseModel):
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = None
    strict_numbers: bool = Field(default=False, description="UserValve: never accept unverified values")
    show_debug_trace: bool = False
    max_embeds: int = Field(default=6, ge=0, le=20)
    benchmark: BenchmarkMode | None = None


class AnswerRequest(BaseModel):
    messages: Annotated[list[ChatMessage], Field(min_length=1)]
    chat_id: str
    message_id: str
    attachments: list[Attachment] = []
    options: AnswerOptions = AnswerOptions()


class ConfirmationReply(BaseModel):
    confirmation_id: str
    accepted: bool


# ---------------------------------------------------------------- SSE events


class EventType(StrEnum):
    STEP = "step"
    TOKEN = "token"  # noqa: S105 (an SSE event name, not a credential)
    CITATION = "citation"
    EMBED = "embed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    DONE = "done"
    ERROR = "error"


class StepName(StrEnum):
    QUERY_ANALYSIS = "query_analysis"
    PLANNING = "planning"
    TOOL = "tool"
    SUFFICIENCY = "sufficiency"
    CLARIFICATION = "clarification"
    SYNTHESIS = "synthesis"
    VERIFICATION = "verification"
    RENDER = "render"


class Provenance(StrEnum):
    """Label every cited claim carries (file 07 §7)."""

    MEASURED = "measured"
    INTERNAL_REPORT = "internal_report"
    STANDARD = "standard"
    VENDOR_CLAIM = "vendor_claim"
    LITERATURE = "literature"
    WEB = "web"


class AnswerMode(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CLARIFICATION = "clarification"
    EXTRACTIVE = "extractive"
    CHITCHAT = "chitchat"


class StepEvent(BaseModel):
    type: Literal[EventType.STEP] = EventType.STEP
    step_id: str
    name: StepName
    description: str = Field(description='shown above the message, e.g. "Running DuckDB on TP07_T01…"')
    done: bool
    tool: str | None = None
    duration_ms: int | None = None


class TokenEvent(BaseModel):
    type: Literal[EventType.TOKEN] = EventType.TOKEN
    text: str


class CitationEvent(BaseModel):
    """One cited passage, referenced by doc id plus the serialized stable anchor, never by node id."""

    type: Literal[EventType.CITATION] = EventType.CITATION
    citation_id: str = Field(description="label used in the answer text, e.g. '1'")
    doc_id: uuid.UUID | None = Field(description="null for web sources")
    title: str
    label: str = Field(description='"Test Report 37, p. 8" or "run TP07_T04"')
    anchor: str | None = Field(description="<kind>:<value>:<content_sha256>, file 04 §4.4")
    page_no: int | None = None
    provenance: Provenance
    language: str | None = None
    translated: bool = False
    needs_review: bool = Field(description='render "⚠ unverified extraction"')
    quote: str | None = None
    url_viewer: str | None = Field(description="Console deep link /docs/{doc_id}/viewer?anchor=…")
    url_onedrive: str | None = None
    url_asset: str | None = None


class EmbedEvent(BaseModel):
    type: Literal[EventType.EMBED] = EventType.EMBED
    embed_id: str
    kind: Literal["photo_strip", "plot", "timeline", "diagram", "html"]
    html: str | None = Field(default=None, description="self-contained HTML for an Open WebUI embed")
    url: str | None = Field(default=None, description="signed URL when the embed needs no HTML")
    alt: str
    height: int | None = None


class ConfirmationEvent(BaseModel):
    """The stream pauses; the Pipe replies to `POST /v1/answer/{trace_id}/confirm` before `done` exists."""

    type: Literal[EventType.NEEDS_CONFIRMATION] = EventType.NEEDS_CONFIRMATION
    trace_id: uuid.UUID
    confirmation_id: str
    title: str
    message: str


class VerifierSummary(BaseModel):
    claims: int
    entailed: int
    contradicted: int
    not_supported: int


class Usage(BaseModel):
    tokens_in: int
    tokens_out: int
    cost_estimate: float | None = None


class DoneEvent(BaseModel):
    type: Literal[EventType.DONE] = EventType.DONE
    trace_id: uuid.UUID
    mode: AnswerMode
    answer_markdown: str
    caveats: list[str] = []
    followups: list[str] = []
    verifier: VerifierSummary | None = None
    usage: Usage
    latency_ms: int


class ErrorEvent(BaseModel):
    type: Literal[EventType.ERROR] = EventType.ERROR
    trace_id: uuid.UUID | None = None
    code: Literal["unauthorized", "bad_request", "gemini_unavailable", "budget_exhausted", "internal"]
    message: str
    retryable: bool


AnswerEvent = Annotated[
    StepEvent | TokenEvent | CitationEvent | EmbedEvent | ConfirmationEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]


def to_sse(event: BaseModel) -> str:
    """One SSE frame: `event: <type>` and one JSON `data:` line (JSON never contains a raw newline)."""
    payload = event.model_dump(mode="json", exclude={"type"})
    return f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------- traces


class TraceView(BaseModel):
    """`GET /v1/traces/{trace_id}`: what the Show-trace action renders (file 08 §2.2, file 05 §4.7)."""

    trace_id: uuid.UUID
    chat_id: str | None
    message_id: str | None
    question: str
    query_analysis: dict
    tool_calls: list[dict]
    retrieved: list[dict] = Field(description="stable anchors with ranks and scores")
    external_queries: list[dict]
    claims: list[dict]
    citations: list[dict]
    verifier_result: dict | None
    answer_markdown: str
    latency_ms: int | None
    created_at: str


class FeedbackKind(StrEnum):
    """Reasons of the Report-issue Action (file 08 §2.2)."""

    WRONG_NUMBER = "wrong_number"
    WRONG_CITATION = "wrong_citation"
    MISSING_DOCUMENT = "missing_document"
    WRONG_UNIT = "wrong_unit"
    WRONG_TRANSLATION = "wrong_translation"


class FeedbackRequest(BaseModel):
    """Appended to `answer_traces.feedback`; `wrong_unit` also opens a SOFT CONFLICT flag on the page."""

    kind: FeedbackKind
    comment: str | None = Field(default=None, max_length=4000)
    citation_id: str | None = Field(default=None, description="the citation the report is about, if any")


# ---------------------------------------------------------------- identity


class PipeIdentity(BaseModel):
    user_id: str
    email: str
    groups: list[str]


def sign_identity(secret: str, timestamp: str, user_id: str, email: str, groups: str, body: bytes) -> str:
    message = f"{timestamp}\n{user_id}\n{email}\n{groups}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


async def pipe_identity(
    request: Request,
    x_dcl_user_id: Annotated[str, Header()],
    x_dcl_user_email: Annotated[str, Header()],
    x_dcl_user_groups: Annotated[str, Header()],
    x_dcl_timestamp: Annotated[str, Header()],
    x_dcl_signature: Annotated[str, Header()],
) -> PipeIdentity:
    secret = get_settings().require(Group.PIPE).pipe_shared_secret.get_secret_value()
    if not x_dcl_timestamp.isdigit() or abs(time.time() - int(x_dcl_timestamp)) > MAX_CLOCK_SKEW_S:
        raise HTTPException(status_code=401, detail="identity timestamp missing or outside the allowed skew")
    expected = sign_identity(
        secret, x_dcl_timestamp, x_dcl_user_id, x_dcl_user_email, x_dcl_user_groups, await request.body()
    )
    if not hmac.compare_digest(expected, x_dcl_signature):
        raise HTTPException(status_code=401, detail="identity signature does not verify")
    groups = [g.strip() for g in x_dcl_user_groups.split(",") if g.strip()]
    return PipeIdentity(user_id=x_dcl_user_id, email=x_dcl_user_email, groups=groups)


Identity = Annotated[PipeIdentity, Depends(pipe_identity)]


# ---------------------------------------------------------------- routes


@router.post(
    "/answer",
    responses={200: {"content": {SSE_MEDIA_TYPE: {}}, "description": "stream of AnswerEvent frames"}},
)
async def answer(request: AnswerRequest, identity: Identity):
    raise HTTPException(
        status_code=501, detail="the answer workflow is not built yet (file 07, milestone M8)"
    )


@router.post("/answer/{trace_id}/confirm", status_code=202)
async def confirm(trace_id: uuid.UUID, reply: ConfirmationReply, identity: Identity) -> None:
    raise HTTPException(status_code=501, detail="confirmations arrive with the workflow (M8)")


@router.get("/traces/{trace_id}")
async def trace(trace_id: uuid.UUID, identity: Identity) -> TraceView:
    raise HTTPException(status_code=501, detail="answer_traces arrives with the workflow (M8)")


@router.get("/traces")
async def trace_for_message(
    chat_id: Annotated[str, Query(min_length=1)],
    message_id: Annotated[str, Query(min_length=1)],
    identity: Identity,
) -> TraceView:
    """The trace of one Open WebUI message; the Show-trace Action knows chat and message ids, not the
    trace id. 404 when the message has no trace."""
    raise HTTPException(status_code=501, detail="answer_traces arrives with the workflow (M8)")


@router.post("/traces/{trace_id}/feedback", status_code=202)
async def feedback(trace_id: uuid.UUID, report: FeedbackRequest, identity: Identity) -> None:
    raise HTTPException(status_code=501, detail="answer_traces arrives with the workflow (M8)")
