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

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter

from backend.api.auth import CurrentUser
from backend.config import ConfigError, Group, get_settings
from backend.indexing.retrieval import Scope, SearchFilters, SearchResult, search
from backend.llm_engine.engine.analysis import Intent
from backend.llm_engine.engine.tools import Provenance

MAX_CLOCK_SKEW_S = 300
SSE_MEDIA_TYPE = "text/event-stream"
ANSWER_TIMEOUT_S = 300
HISTORY_TURNS = 6
HISTORY_CHARS = 4000
log = logging.getLogger(__name__)

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
    playbook_hint: Intent | None = Field(
        default=None,
        description="the intent of a playbook Skill the user $-mentioned (front matter `dcl-playbook`); "
        "the planner adds it to the analysed intents",
    )


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


EVENTS = TypeAdapter(AnswerEvent)


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
    gemini: dict = Field(
        default_factory=dict,
        description="llm_calls of this answer: calls (purpose, model, latency_ms, tokens), total_ms, share",
    )


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


def _session_factory():
    from backend.postgres.session import engine_from_settings, session_factory

    return session_factory(engine_from_settings(get_settings()))


def db_session():
    with _session_factory()() as session:
        yield session


# ---------------------------------------------------------------- routes


def split_conversation(messages: list[ChatMessage]) -> tuple[str, str]:
    """The last user message is the question; the turns before it (bounded) are the history."""
    last = (
        max(i for i, m in enumerate(messages) if m.role == "user")
        if any(m.role == "user" for m in messages)
        else len(messages) - 1
    )
    earlier = [m for m in messages[:last] if m.role != "system"][-HISTORY_TURNS:]
    history = "\n".join(f"{m.role}: {m.content}" for m in earlier)[-HISTORY_CHARS:]
    return messages[last].content, history


# ---------------------------------------------------------------- the engine (one per API process)

_ENGINE: dict[str, Any] = {}
_ENGINE_LOCK = asyncio.Lock()


def _viewer_url(doc_id: uuid.UUID, anchor: str | None) -> str | None:
    base = get_settings().console_base_url
    if base is None:
        return None
    return f"{str(base).rstrip('/')}/docs/{doc_id}/viewer" + (f"?anchor={quote(anchor)}" if anchor else "")


def _log_trace(trace: dict) -> None:
    """Log line per answer (no answer text) and the `answer_traces` row (file 05 §4.7)."""
    log.info(
        "answer trace %s mode=%s tools=%s latency_ms=%s",
        trace["trace_id"],
        trace["mode"],
        [c["tool"] for c in trace["tool_calls"]],
        trace["latency_ms"],
    )
    try:
        with _session_factory()() as session:
            save_trace(session, trace)
            session.commit()
    except Exception:  # noqa: BLE001 — the answer was already streamed; a lost trace must not fail it
        log.exception("answer trace %s could not be saved", trace["trace_id"])


def save_trace(session, trace: dict) -> None:
    """Insert or replace the trace row (a DBOS replay of the last step writes the same row again)."""
    from backend.postgres.models import AnswerTrace

    session.merge(
        AnswerTrace(
            trace_id=uuid.UUID(str(trace["trace_id"])),
            chat_id=trace.get("chat_id"),
            message_id=trace.get("message_id"),
            user_id=trace.get("user_id"),
            question=trace.get("question") or "",
            conversation_summary=trace.get("conversation_summary"),
            user_language=trace.get("user_language"),
            query_analysis=trace.get("query_analysis"),
            tool_calls=trace.get("tool_calls"),
            retrieved=trace.get("retrieved"),
            external_queries=trace.get("external_queries"),
            claims=trace.get("claims"),
            citations=trace.get("citations"),
            verifier_result=trace.get("verifier_result"),
            model_config_={**(trace.get("model_config") or {}), "mode": trace.get("mode")},
            answer_markdown=trace.get("answer_markdown"),
            latency_ms=trace.get("latency_ms"),
        )
    )
    session.flush()


def _external_policy(session) -> Any:
    """File 07 §6 policy from `pipeline_config`: kill switch, allowed groups, proprietary terms."""
    from backend.llm_engine.engine.tools.external import ExternalPolicy
    from backend.postgres import pipeline_config

    return ExternalPolicy(
        enabled=bool(pipeline_config.get(session, "answer.external_search_enabled", True)),
        allowed_groups=tuple(pipeline_config.get(session, "answer.external_allowed_groups", [])),
        proprietary_terms=tuple(pipeline_config.get(session, "answer.proprietary_terms", [])),
    )


def _asset_access(settings) -> tuple[Any, Any, Any]:
    """(presign, fetch, put_asset) over MinIO for T2 plots and T3; all None without MinIO configured."""
    from backend.storage.media_links import media_url
    from backend.storage.minio import (
        ASSETS,
        BucketStore,
        client_from_settings,
        parse_uri,
    )

    try:
        client = client_from_settings(settings)
    except ConfigError as exc:
        log.warning("T2 plots and T3 image links are off: %s", exc)
        return None, None, None

    def fetch(uri: str) -> bytes:
        bucket, key = parse_uri(uri)
        response = client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    assets = BucketStore(client, ASSETS)
    # embedded images, videos and plots stay with the chat message: they get lasting links that redirect to a
    # fresh presigned link each time they are opened (storage/media_links.py)
    return (
        (lambda uri: media_url(settings, uri)),
        fetch,
        (lambda key, data: assets.put(key, data, content_type="image/png")),
    )


def _telemetry_connect(settings) -> Any:
    """T2's DuckDB connections: httpfs with a MinIO secret, so `s3://dcl-telemetry/…` URIs read in place."""
    from urllib.parse import urlsplit

    try:
        settings.require(Group.MINIO)
    except ConfigError as exc:
        log.warning("T2 runs without the telemetry store: %s", exc)
        return None
    endpoint = urlsplit(str(settings.minio_endpoint))
    secure = bool(settings.minio_secure or endpoint.scheme == "https")
    secret = [
        settings.minio_access_key,
        settings.minio_secret_key.get_secret_value(),
        endpoint.netloc,
        secure,
    ]

    def connect():
        import duckdb

        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(
            "CREATE SECRET dcl_minio (TYPE s3, KEY_ID ?, SECRET ?, ENDPOINT ?, URL_STYLE 'path', USE_SSL ?, "
            "REGION 'us-east-1')",
            secret,
        )
        return con

    return connect


def engine_deps(settings) -> Any:
    """The workflow's process-level clients (Gemini, models, database, MinIO, DuckDB); shared with the
    benchmark runner so a benchmark answer takes the same code path as chat."""
    if settings.models_url is None:
        raise ConfigError("DCL_MODELS_URL is required by the Answer Engine")
    from backend.llm_engine.engine.workflow import EngineDeps
    from backend.llm_engine.enrichment.entities import index_from_db
    from backend.llm_engine.gemini_client import GeminiClient
    from backend.llm_engine.local_models import ModelsClient

    models = ModelsClient(base_url=str(settings.models_url))
    presign, fetch_asset, put_asset = _asset_access(settings)
    return EngineDeps(
        gemini=GeminiClient(settings),
        session_factory=_session_factory(),
        embed_query=lambda q: models.embed_queries([q])[0],
        embed_image=lambda data: models.embed_images([data])[0],
        rerank=models.rerank,
        alias_index=index_from_db,
        viewer_url=_viewer_url,
        save_trace=_log_trace,
        external_policy=_external_policy,
        presign=presign,
        fetch_asset=fetch_asset,
        put_asset=put_asset,
        telemetry_connect=_telemetry_connect(settings),
    )


async def start_engine() -> None:
    """Build the workflow with its process-level clients and launch DBOS (decision H8). Idempotent."""
    async with _ENGINE_LOCK:
        if "workflow" in _ENGINE:
            return
        settings = get_settings()
        from backend.llm_engine.engine.workflow import AnswerWorkflow, build_runtime

        deps = engine_deps(settings)
        database_url = settings.stack_database_url().get_secret_value().replace("+psycopg", "")
        runtime = build_runtime(database_url)
        workflow = AnswerWorkflow(deps, runtime=runtime, workflow_name="answer", timeout=ANSWER_TIMEOUT_S)
        await runtime.launch()
        _ENGINE.update(workflow=workflow, runtime=runtime, gemini=deps.gemini)


async def stop_engine() -> None:
    async with _ENGINE_LOCK:
        runtime = _ENGINE.pop("runtime", None)
        gemini = _ENGINE.pop("gemini", None)
        _ENGINE.pop("workflow", None)
        if runtime is not None:
            await runtime.destroy()
        if gemini is not None:
            await gemini.aclose()


async def answer_engine(identity: Identity) -> Any:
    """FastAPI dependency: the running workflow, started on first use if the lifespan did not start it.

    It depends on the identity so an unsigned request is refused before the engine is touched.
    """
    try:
        await start_engine()
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=f"the Answer Engine is not configured: {exc}") from exc
    except ImportError as exc:  # an API image built without the engine's dependency group
        raise HTTPException(status_code=503, detail=f"the Answer Engine is not installed: {exc}") from exc
    return _ENGINE["workflow"]


@router.post(
    "/answer",
    responses={200: {"content": {SSE_MEDIA_TYPE: {}}, "description": "stream of AnswerEvent frames"}},
)
async def answer(
    request: AnswerRequest, identity: Identity, engine: Annotated[Any, Depends(answer_engine)]
) -> StreamingResponse:
    """Run the Answer Engine workflow and stream its frames; a failure ends the stream with `error`."""
    from backend.llm_engine.engine.workflow import ordered
    from backend.llm_engine.gemini_types import GeminiError

    trace_id = uuid.uuid4()
    question, history = split_conversation(request.messages)

    async def frames():
        try:
            handler = engine.run(
                question=question,
                trace_id=str(trace_id),
                history=history,
                groups=identity.groups,
                user_id=identity.user_id,
                chat_id=request.chat_id,
                message_id=request.message_id,
                external_mode=request.options.benchmark.external_search
                if request.options.benchmark
                else None,
                playbook_hint=request.options.playbook_hint,
                attachments=[a.model_dump() for a in request.attachments],
            )
            async for payload in ordered(handler.stream_events()):
                yield to_sse(EVENTS.validate_python(payload))
            await handler
        except GeminiError as exc:
            log.warning("answer %s: Gemini unavailable: %s", trace_id, exc)
            yield to_sse(
                ErrorEvent(
                    trace_id=trace_id, code="gemini_unavailable", message=str(exc)[:300], retryable=True
                )
            )
        except Exception:
            log.exception("answer %s failed", trace_id)
            yield to_sse(
                ErrorEvent(trace_id=trace_id, code="internal", message="the answer failed", retryable=False)
            )

    return StreamingResponse(frames(), media_type=SSE_MEDIA_TYPE)


@router.post("/answer/{trace_id}/confirm", status_code=202)
async def confirm(trace_id: uuid.UUID, reply: ConfirmationReply, identity: Identity) -> None:
    raise HTTPException(status_code=501, detail="confirmations arrive with the workflow (M8)")


GEMINI_CALLS_SQL = (
    "SELECT purpose, model, latency_ms, input_tokens, output_tokens, cost_estimate, status FROM llm_calls "
    "WHERE trace_id = :trace ORDER BY at"
)


def gemini_split(session, trace_id: uuid.UUID, answer_ms: int | None) -> dict:
    """The answer's Gemini calls from `llm_calls` and their share of the answer time (drilldown)."""
    from sqlalchemy import text as sql

    calls = [dict(r._mapping) for r in session.execute(sql(GEMINI_CALLS_SQL), {"trace": str(trace_id)})]
    total = sum(c["latency_ms"] or 0 for c in calls)
    costs = [c["cost_estimate"] for c in calls if c["cost_estimate"] is not None]
    return {
        "calls": calls,
        "total_ms": total,
        "share": round(total / answer_ms, 3) if answer_ms else None,
        "tokens_in": sum(c["input_tokens"] or 0 for c in calls),
        "tokens_out": sum(c["output_tokens"] or 0 for c in calls),
        "cost_estimate": round(sum(costs), 6) if costs else None,
    }


def _trace_view(row, session=None) -> TraceView:
    return TraceView(
        trace_id=row.trace_id,
        chat_id=row.chat_id,
        message_id=row.message_id,
        question=row.question,
        query_analysis=row.query_analysis or {},
        tool_calls=row.tool_calls or [],
        retrieved=row.retrieved or [],
        external_queries=row.external_queries or [],
        claims=row.claims or [],
        citations=row.citations or [],
        verifier_result=row.verifier_result,
        answer_markdown=row.answer_markdown or "",
        latency_ms=row.latency_ms,
        created_at=row.created_at.isoformat(),
        gemini=gemini_split(session, row.trace_id, row.latency_ms) if session is not None else {},
    )


def _own_trace(session, identity: PipeIdentity, trace_id: uuid.UUID | None = None, **where) -> Any:
    """The trace if it exists and belongs to the caller (or has no user); 404 otherwise, never 403, so
    trace ids of other users are not confirmed."""
    from sqlalchemy import select

    from backend.postgres.models import AnswerTrace

    query = select(AnswerTrace)
    if trace_id is not None:
        query = query.where(AnswerTrace.trace_id == trace_id)
    for column, value in where.items():
        query = query.where(getattr(AnswerTrace, column) == value)
    row = session.scalars(query.order_by(AnswerTrace.created_at.desc()).limit(1)).first()
    if row is None or (row.user_id and row.user_id != identity.user_id):
        raise HTTPException(status_code=404, detail="no trace for this message")
    return row


@router.get("/traces/{trace_id}")
def trace(trace_id: uuid.UUID, identity: Identity, session: Annotated[Any, Depends(db_session)]) -> TraceView:
    return _trace_view(_own_trace(session, identity, trace_id), session)


@router.get("/traces")
def trace_for_message(
    chat_id: Annotated[str, Query(min_length=1)],
    message_id: Annotated[str, Query(min_length=1)],
    identity: Identity,
    session: Annotated[Any, Depends(db_session)],
) -> TraceView:
    """The trace of one Open WebUI message; the Show-trace Action knows chat and message ids, not the
    trace id. 404 when the message has no trace."""
    return _trace_view(_own_trace(session, identity, chat_id=chat_id, message_id=message_id), session)


def _unit_conflict(trace_row, report: FeedbackRequest, identity: PipeIdentity) -> Any:
    """`wrong_unit` on a cited page: a SOFT CONFLICT flag anchored to the page and content hash (file 08
    §2.2), so the Review queue sees it. None when the report names no citation with a page anchor."""
    from backend.dispatcher.contract import ConflictEvidence, ConflictSide, Flag, FlagAnchor
    from backend.postgres.enums import FlagSeverity, FlagType

    citations = trace_row.citations or []
    try:
        cited = citations[int(report.citation_id) - 1] if report.citation_id else None
    except (ValueError, IndexError):
        cited = None
    if not cited or not cited.get("doc_id") or not (cited.get("anchor") or "").startswith("page:"):
        return None
    _, page, digest = cited["anchor"].split(":", 2)
    flag = Flag(
        flag_type=FlagType.CONFLICT,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(page=int(page) if page.isdigit() else None, content_sha256=digest or None),
        evidence=ConflictEvidence(
            subject="unit",
            a=ConflictSide(
                label="chat_feedback",
                value=(report.comment or "wrong unit or extraction")[:500],
                provenance=(
                    f"source chat_feedback; trace {trace_row.trace_id}; "
                    f"user {identity.email or identity.user_id}"
                ),
            ),
            b=ConflictSide(
                label="cited passage",
                value=cited.get("label") or cited.get("title") or "",
                provenance=cited["anchor"],
                doc_id=uuid.UUID(cited["doc_id"]),
            ),
        ),
    )
    return uuid.UUID(cited["doc_id"]), flag


@router.post("/traces/{trace_id}/feedback", status_code=202)
def feedback(
    trace_id: uuid.UUID,
    report: FeedbackRequest,
    identity: Identity,
    session: Annotated[Any, Depends(db_session)],
) -> None:
    """Appended to `answer_traces.feedback` in one statement; `wrong_unit` also opens a SOFT CONFLICT."""
    from datetime import UTC, datetime

    from sqlalchemy import text as sql

    from backend.review.flags import upsert_document_flag

    row = _own_trace(session, identity, trace_id)
    item = {
        **report.model_dump(mode="json"),
        "user_id": identity.user_id,
        "email": identity.email,
        "at": datetime.now(UTC).isoformat(),
    }
    session.execute(
        sql(
            "UPDATE answer_traces SET feedback = COALESCE(feedback, '[]'::jsonb) || jsonb_build_array("
            "CAST(:item AS jsonb)) WHERE trace_id = :id"
        ),
        {"item": json.dumps(item), "id": trace_id},
    )
    if report.kind == FeedbackKind.WRONG_UNIT and (conflict := _unit_conflict(row, report, identity)):
        doc_id, flag = conflict
        route = session.execute(sql("SELECT route FROM documents WHERE doc_id = :d"), {"d": doc_id}).scalar()
        if (
            route is not None
        ):  # a flag belongs to its document: the document's own route, origin in the evidence
            upsert_document_flag(session, doc_id, flag, route=route)
    session.commit()


# ---------------------------------------------------------------- retrieval lab (Console, file 08 §5.5)


class RetrievalLabRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    filters: SearchFilters = SearchFilters()
    scope: Scope = Scope.CHILD
    k: int = Field(default=30, ge=1, le=50)
    user_language: str = "en"
    rerank: bool = True


@lru_cache(maxsize=1)
def models_client():
    from backend.llm_engine.local_models import ModelsClient

    url = get_settings().models_url
    if url is None:
        raise HTTPException(status_code=503, detail="DCL_MODELS_URL is not set")
    return ModelsClient(base_url=str(url))


@router.post("/retrieval/search")
def retrieval_lab(
    request: RetrievalLabRequest,
    user: CurrentUser,
    session: Annotated[Any, Depends(db_session)],
    models: Annotated[Any, Depends(models_client)],
) -> SearchResult:
    """The Retrieval lab: one search with its legs, path, scores and margin (Console users only)."""
    return search(
        session,
        request.query,
        embed_query=lambda q: models.embed_queries([q])[0],
        rerank=models.rerank if request.rerank else None,
        filters=request.filters,
        scope=request.scope,
        k=request.k,
        user_language=request.user_language,
    )


# ---------------------------------------------------------------- prompt registry (file 08 §3.3)


def _prompt_registry():
    from backend.llm_engine.prompts import registry

    return registry


@router.get("/prompts")
def prompts_list(user: CurrentUser) -> list[Any]:
    """Every prompt version with `latest`, `in_use` (pinned by the code today) and its template variables."""
    return _prompt_registry().list_prompts()


@router.get("/prompts/{area}/{version}")
def prompt_text(area: str, version: str, user: CurrentUser) -> Any:
    registry = _prompt_registry()
    try:
        return registry.get_prompt(area, version)
    except registry.PromptNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/prompts/{area}/diff/{a}/{b}")
def prompt_diff(area: str, a: str, b: str, user: CurrentUser) -> Any:
    registry = _prompt_registry()
    try:
        return registry.diff_prompts(area, a, b)
    except registry.PromptNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/prompts/{area}/{version}/run")
async def prompt_run(area: str, version: str, body: dict, user: CurrentUser) -> Any:
    """Run on sample: one Gemini call with the configured model; reviewers and admins (it costs tokens)."""
    from backend.api.auth import ConsoleRole
    from backend.llm_engine.gemini_client import GeminiClient
    from backend.llm_engine.gemini_types import GeminiError

    if not user.has(ConsoleRole.REVIEWER):
        raise HTTPException(status_code=403, detail="requires role reviewer")
    registry = _prompt_registry()
    request = registry.PromptRun.model_validate(body)
    client = _ENGINE.get("gemini") or GeminiClient(get_settings())
    try:
        return await registry.run_prompt(client, area, version, request, user=user.email)
    except registry.PromptNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=f"gateway: {str(exc)[:300]}") from exc


# ---------------------------------------------------------------- on-the-fly translation (file 04 §10)


class TranslateRequest(BaseModel):
    doc_id: uuid.UUID
    page_no: int | None = Field(default=None, ge=1, description="a page; or")
    anchor: str | None = Field(default=None, description="a passage: <kind>:<value>:<content_sha256>")
    target_language: str = Field(default="en", pattern=r"^[a-z]{2}$")


class TranslatedPassage(BaseModel):
    original: str
    translated: str
    cached: bool


class TranslateResponse(BaseModel):
    doc_id: uuid.UUID
    page_no: int | None
    source_language: str | None
    target_language: str
    passages: list[TranslatedPassage]
    translated_text: str
    note: str = "Translation of the original; citations point to the original text."


def translation_cache() -> Any:
    from backend.storage.minio import CIR, BucketStore, client_from_settings

    try:
        return BucketStore(client_from_settings(get_settings()), CIR)
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=f"translation cache unavailable: {exc}") from exc


def translation_client() -> Any:
    from backend.llm_engine.gemini_client import GeminiClient

    return _ENGINE.get("gemini") or GeminiClient(get_settings())


TRANSLATABLE = ("child", "parent", "table", "table_row", "slide", "figure", "transcript_window")


def _passages(session, request: TranslateRequest) -> tuple[int | None, list[tuple[str, str | None]]]:
    """(page, [(content, language)]) of the page, or of the passage the anchor resolves to."""
    from sqlalchemy import ARRAY, bindparam
    from sqlalchemy import text as sql
    from sqlalchemy.dialects.postgresql import UUID as PGUUID

    from backend.dispatcher.contract import Anchor
    from backend.indexing.anchors import resolve_anchor

    page_no = request.page_no
    if request.anchor:
        resolution = resolve_anchor(session, Anchor.parse(request.doc_id, request.anchor))
        if resolution.status == "exact" and resolution.matches:
            rows = session.execute(
                sql(
                    "SELECT content, language FROM document_nodes WHERE node_id = ANY(:ids) ORDER BY ordinal"
                ).bindparams(bindparam("ids", type_=ARRAY(PGUUID(as_uuid=True)))),
                {"ids": [m.node_id for m in resolution.matches]},
            ).all()
            return resolution.page_no, [(r.content, r.language) for r in rows]
        page_no = resolution.page_no
    if page_no is None:
        raise HTTPException(status_code=422, detail="give a page_no or an anchor")
    rows = session.execute(
        sql(
            "SELECT n.content, n.language FROM document_nodes n WHERE n.doc_id = :doc AND n.page_no = :page "
            "AND n.node_type = ANY(:types) "
            "AND NOT EXISTS (SELECT 1 FROM document_nodes c WHERE c.parent_node_id = n.node_id) "
            "ORDER BY n.ordinal"
        ),
        {"doc": request.doc_id, "page": page_no, "types": list(TRANSLATABLE)},
    ).all()
    return page_no, [(r.content, r.language) for r in rows]


def _cloud_allowed(session, doc_id: uuid.UUID) -> bool:
    from sqlalchemy import text as sql

    return bool(
        session.execute(
            sql(
                "SELECT bool_or(r.cloud_allowed) FROM document_sources ds "
                "JOIN drive_items di ON di.blob_sha256 = ds.blob_sha256 AND di.deleted_at IS NULL "
                "JOIN sync_roots r ON r.root_name = di.root_name "
                "WHERE ds.doc_id = :doc AND ds.role = 'primary'"
            ),
            {"doc": doc_id},
        ).scalar()
    )


@router.post("/translate")
def translate(
    request: TranslateRequest,
    user: CurrentUser,
    session: Annotated[Any, Depends(db_session)],
    cache: Annotated[Any, Depends(translation_cache)],
    client: Annotated[Any, Depends(translation_client)],
) -> TranslateResponse:
    """The viewer's Translate toggle without `content_en`: per page or passage, cached by content hash."""
    from sqlalchemy import text as sql

    from backend.llm_engine.enrichment.translate import TranslationRefused, translate_passages
    from backend.llm_engine.gemini_types import GeminiError

    language = session.execute(
        sql("SELECT language FROM documents WHERE doc_id = :doc"), {"doc": request.doc_id}
    ).scalar()
    page_no, found = _passages(session, request)
    if not found:
        raise HTTPException(status_code=404, detail="nothing to translate at that location")
    source = next((lang for _, lang in found if lang), None) or language
    try:
        done = translate_passages(
            client,
            cache,
            [content for content, _ in found],
            source_language=source,
            target_language=request.target_language,
            cloud_allowed=_cloud_allowed(session, request.doc_id),
            doc_id=str(request.doc_id),
        )
    except TranslationRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (GeminiError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"translation failed: {str(exc)[:300]}") from exc
    passages = [TranslatedPassage(original=t.source, translated=t.text, cached=t.cached) for t in done]
    return TranslateResponse(
        doc_id=request.doc_id,
        page_no=page_no,
        source_language=source,
        target_language=request.target_language,
        passages=passages,
        translated_text="\n\n".join(p.translated for p in passages),
    )
