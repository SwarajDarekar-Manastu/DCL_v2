"""The Answer Engine workflow (file 07 §2): analysis → plan → tools → sufficiency → synthesis + verification.

A LlamaIndex Workflow with three steps and typed events (`QueryAnalyzed`, `ToolsDone`), streaming the wire
events of `backend/api/engine.py` (`step`, `token`, `citation`, `done`) through `Emit`.
Events carry JSON-ready
payloads so the DBOS runtime (decision H8, `build_runtime`) can journal every transition and resume a run by
id after a restart; dependencies (clients, the session factory) live on the workflow instance.

Behaviours of file 07 §10–§12: chit-chat is answered briefly with no tools; a clarification ends the run with
mode `clarification`; no evidence gives the insufficient-evidence template with what was searched; a Gemini
failure during synthesis degrades to extractive mode (top passages with citations, no synthesis); every run
produces a trace record (`answer_traces` columns) handed to `save_trace`.
"""

import asyncio
import dataclasses
import html
import itertools
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from workflows import Context, Workflow, step
from workflows.events import Event, StartEvent, StopEvent

from backend.config import ThinkingLevel
from backend.llm_engine.engine import catalog, playbooks, synthesis
from backend.llm_engine.engine.analysis import Analysis, Intent, QueryAnalysis, analyze
from backend.llm_engine.engine.playbooks import PlannedCall
from backend.llm_engine.engine.tools import Source, ToolResult
from backend.llm_engine.engine.tools import attachments as attachment_tools
from backend.llm_engine.engine.tools import external as external_tools
from backend.llm_engine.engine.tools import telemetry as telemetry_tools
from backend.llm_engine.engine.tools import visuals as visual_tools
from backend.llm_engine.engine.tools.code_diagrams import inspect_code_and_diagrams
from backend.llm_engine.engine.tools.documents import GetDocumentArgs, get_document
from backend.llm_engine.engine.tools.external import ExternalPolicy
from backend.llm_engine.engine.tools.physics import PhysicsArgs, physics_calculator
from backend.llm_engine.engine.tools.search import SearchDocumentsArgs, search_documents
from backend.llm_engine.gemini_types import CallContext, GeminiError, Message
from backend.llm_engine.model_ids import Tier, model_id
from backend.llm_engine.prompts import load_prompt

TOKEN_CHUNK = 160
EXTRACTIVE_PASSAGES = 5


log = logging.getLogger(__name__)


@dataclass
class EngineDeps:
    gemini: Any
    session_factory: Callable[[], Any]
    embed_query: Callable[[str], list[float]]
    rerank: Callable | None
    alias_index: Callable[[Any], Any]
    external_policy: Callable[[Any], ExternalPolicy] = lambda session: ExternalPolicy(enabled=False)
    fetch_attachment: Callable[[str], bytes] = attachment_tools.fetch  # presigned upload URL → bytes (capped)
    embed_image: Callable[[bytes], list[float]] | None = (
        None  # models role; T3 similarity for attached photos
    )
    viewer_url: Callable[[uuid.UUID, str | None], str | None] = lambda doc_id, anchor: None
    save_trace: Callable[[dict], None] = lambda trace: None
    telemetry_connect: Callable[[], Any] | None = None  # DuckDB connection that reads the stored Parquet URIs
    presign: Callable[[str], str] | None = None  # MinIO URI → presigned GET (15 min)
    fetch_asset: Callable[[str], bytes] | None = None
    put_asset: Callable[[str, bytes], str] | None = (
        None  # dcl-assets key, PNG → s3:// URI (T2 plots)  # MinIO URI → bytes (T3 relook)
    )


class Emit(Event):
    """One wire event (`backend/api/engine.py` models, dumped); the API turns it into an SSE frame.

    `seq` numbers the frames of one run from 0: under DBOS every stream write is its own task, so frames can
    arrive out of order and `ordered` puts them back.
    """

    seq: int
    payload: dict


class QueryAnalyzed(Event):
    analysis: dict
    started: float


class ToolsDone(Event):
    analysis: dict
    results: list[dict]
    caveats: list[str]
    started: float


def dump_analysis(analysis: Analysis) -> dict:
    data = dataclasses.asdict(analysis)
    data["raw"] = analysis.raw.model_dump(mode="json")
    data["entity_ids"] = [str(e) for e in analysis.entity_ids]
    return data


def load_analysis(data: dict) -> Analysis:
    return Analysis(
        **{
            **data,
            "raw": QueryAnalysis.model_validate(data["raw"]),
            "entity_ids": [uuid.UUID(e) for e in data["entity_ids"]],
        }
    )


_SEQUENCES: dict[str, itertools.count] = {}


def _emit(ctx: Context, trace_id: str, payload: dict) -> None:
    seq = next(_SEQUENCES.setdefault(trace_id, itertools.count()))
    ctx.write_event_to_stream(Emit(seq=seq, payload=payload))


def _step(
    ctx: Context, trace_id: str, step_id: str, name: str, description: str, done: bool, **extra
) -> None:
    payload = {"type": "step", "step_id": step_id, "name": name, "description": description, "done": done}
    _emit(ctx, trace_id, {**payload, **extra})


def _tokens(ctx: Context, trace_id: str, markdown: str) -> None:
    for start in range(0, len(markdown), TOKEN_CHUNK):
        _emit(ctx, trace_id, {"type": "token", "text": markdown[start : start + TOKEN_CHUNK]})


async def ordered(events: AsyncIterator[Any]) -> AsyncIterator[dict]:
    """The run's wire payloads in `seq` order (frames that never arrive leave the rest flushed at the end)."""
    pending: dict[int, dict] = {}
    expected = 0
    async for event in events:
        if not isinstance(event, Emit):
            continue
        pending[event.seq] = event.payload
        while expected in pending:
            yield pending.pop(expected)
            expected += 1
    for seq in sorted(pending):
        yield pending[seq]


CHITCHAT_PROMPT = "chitchat.v2"
HALTED = re.compile(r"halted for review", re.IGNORECASE)  # T2/U2 warning: the answer must name the case


class ChitchatReply(BaseModel):
    kind: Literal["small_talk", "out_of_scope"]
    reply: str


class AnswerWorkflow(Workflow):
    def __init__(self, deps: EngineDeps, **kwargs):
        super().__init__(**kwargs)
        self.deps = deps

    # ------------------------------------------------------------------ step 1: analysis

    @step
    async def analyze_question(self, ctx: Context, ev: StartEvent) -> QueryAnalyzed | StopEvent:
        started = time.monotonic()
        _step(ctx, ev.trace_id, "analysis", "query_analysis", "Understanding the question", False)
        with self.deps.session_factory() as session:
            index = self.deps.alias_index(session)
            policy = self.deps.external_policy(session)
            previous = catalog.previous_record(session, ev.get("chat_id"), ev.get("user_id"))
        policy = dataclasses.replace(policy, mode=ev.get("external_mode") or policy.mode)
        # an answer to the last ask-back ("TP12", "the second one") resumes the question that was asked then
        picked = catalog.chosen_option(previous, ev.question)
        asked = previous["ask"]["question"] if picked else ev.question
        _step(ctx, ev.trace_id, "catalog", "query_analysis", "Finding what the question refers to", False)
        vector = await asyncio.to_thread(self.deps.embed_query, asked)
        with self.deps.session_factory() as session:
            found = catalog.search_catalog(session, asked, vector, previous)
        _step(ctx, ev.trace_id, "catalog", "query_analysis", "Finding what the question refers to", True)
        groups = ev.get("groups", [])
        request = {
            "question": ev.question,
            "trace_id": ev.trace_id,
            "language": ev.get("language", "en"),
            "external": dataclasses.asdict(policy),
            "chat_id": ev.get("chat_id"),
            "message_id": ev.get("message_id"),
            "user_id": ev.get("user_id"),
            "history": ev.get("history", ""),
            "attachments": list(ev.get("attachments") or [])[: attachment_tools.MAX_ATTACHMENTS],
        }
        await ctx.store.set("request", request)
        analysis = await analyze(
            self.deps.gemini,
            asked,
            history=ev.get("history", ""),
            state=ev.get("state", {}),
            index=index,
            user_groups=groups,
            external_allowed_groups=list(policy.allowed_groups) if policy.allows(groups) else [],
            trace_id=ev.trace_id,
            catalog=found.prompt_text(),
        )
        _step(ctx, ev.trace_id, "analysis", "query_analysis", "Understanding the question", True)
        analysis = playbooks.apply_hint(analysis, ev.get("playbook_hint"))
        if analysis.chitchat and not picked:
            return await self._chitchat(ctx, ev, analysis, started, request)
        decision = self._decide(analysis, found, previous, picked, ev)
        analysis.catalog = {**decision.record(found, asked), "caveats": decision.caveats}
        if decision.kind == "ask":
            return self._finish(
                ctx, ev.trace_id, "clarification", decision.text, analysis, [], None, started, request=request
            )
        if decision.kind == "halted":
            return self._finish(
                ctx,
                ev.trace_id,
                "insufficient_evidence",
                decision.text,
                analysis,
                [],
                None,
                started,
                request=request,
            )
        if decision.subject is not None:  # the catalog settled it: the model's own clarification is moot
            analysis.raw.clarification.needed = False
        if analysis.raw.clarification.needed and analysis.raw.clarification.question:
            text = analysis.raw.clarification.question
            if analysis.raw.clarification.options:
                text += "\n" + "\n".join(f"- {o}" for o in analysis.raw.clarification.options)
            return self._finish(
                ctx, ev.trace_id, "clarification", text, analysis, [], None, started, request=request
            )
        return QueryAnalyzed(analysis=dump_analysis(analysis), started=started)

    def _decide(self, analysis: Analysis, found, previous: dict | None, picked: dict | None, ev):
        """The catalog decision after the model reframed the question (engine/catalog.py)."""
        raw = analysis.raw
        allowed = "\n".join(
            [found.question, ev.get("history", ""), str(ev.get("state", {})), found.prompt_text()]
            + [str((previous or {}).get("chosen") or ""), str(picked or "")]
            + [o.label for o in found.options]
        )
        if raw.reframed_question and not catalog.reframing_ok(raw.reframed_question, allowed):
            analysis.warnings.append(f"reframed question dropped (unknown id): {raw.reframed_question}")
            raw.reframed_question = None
            if len(found.subjects) >= 2 and not picked:
                raw.resolution = "ambiguous"
        forced = picked
        if forced is None and "S0" in raw.subject_ids and previous and previous.get("chosen"):
            forced = previous["chosen"]
        with self.deps.session_factory() as session:
            return catalog.decide(
                session,
                found,
                resolution=raw.resolution,
                subject_ids=raw.subject_ids,
                intents=[str(i) for i in raw.intents],
                forced=forced,
            )

    async def _chitchat(self, ctx, ev, analysis: Analysis, started: float, request: dict) -> StopEvent:
        """Small talk gets a friendly reply (mode `chitchat`); a question outside the team's material gets a
        clear refusal on the insufficient-evidence path (mode `insufficient_evidence`, Lead 2026-10-23)."""
        prompt = load_prompt("engine", CHITCHAT_PROMPT)
        result = await self.deps.gemini.generate(
            model=model_id(),
            messages=[
                Message.system(prompt.system),
                Message.user(prompt.render_user(question=ev.question, language=analysis.raw.language)),
            ],
            context=CallContext(
                purpose="engine.chitchat", prompt_version=CHITCHAT_PROMPT, trace_id=ev.trace_id
            ),
            schema=ChitchatReply,
            thinking=ThinkingLevel.LOW,
        )
        reply: ChitchatReply = result.parsed
        mode = "insufficient_evidence" if reply.kind == "out_of_scope" else "chitchat"
        return self._finish(
            ctx, ev.trace_id, mode, reply.reply.strip(), analysis, [], None, started, request=request
        )

    # ------------------------------------------------------------------ steps 2–4: plan and tools

    @step
    async def run_tools(self, ctx: Context, ev: QueryAnalyzed) -> ToolsDone:
        request = await ctx.store.get("request")
        analysis = load_analysis(ev.analysis)
        question = analysis.question or request["question"]
        request = {**request, "asked": question}
        await ctx.store.set("request", request)
        plan = playbooks.build_plan(question, analysis)
        calls = list(plan.calls)
        if plan.needs_physics_args:
            physics = await self._extract(request, "physics_args", PhysicsArgs)
            if physics is not None:
                calls.append(PlannedCall("physics_calculator", physics, "the calculation asked for"))
        if plan.needs_telemetry_args:
            with self.deps.session_factory() as session:
                channels = telemetry_tools.channel_list(session, analysis.catalog.get("run_labels", []))
            asked = await self._extract(
                request,
                "telemetry_args",
                telemetry_tools.TelemetryRequest,
                version="telemetry_args.v2",
                channels=channels or "not known (use the roles)",
            )
            args = asked and telemetry_tools.args_for(
                asked,
                analysis.test_plan_ids,
                analysis.test_run_ids,
                run_labels=analysis.catalog.get("run_labels", []),
            )
            if args is not None:
                calls.insert(0, PlannedCall(telemetry_tools.NAME, args, "the measured run data"))
        trace_id = request["trace_id"]
        attached = await self._attachments(ctx, request)
        visual = Intent.VISUAL_LOOKUP in analysis.raw.intents or analysis.raw.needs_visuals
        for item in attached:
            if item.is_image and visual and self.deps.embed_image is not None:
                vector = await asyncio.to_thread(self.deps.embed_image, item.data)
                args = playbooks.similar_photos(analysis, question, vector)
                calls.append(PlannedCall(visual_tools.NAME, args, f"photos similar to {item.name}"))
        results = await asyncio.gather(*(self._call(ctx, trace_id, i, c) for i, c in enumerate(calls)))
        uncovered = [
            f"not covered by the files: {c.reason.removeprefix('sub-question: ')}"
            for c, r in zip(calls, results, strict=True)
            if c.reason.startswith("sub-question:") and not r.provenance
        ]
        results = [*await self._read_attachments(ctx, request, attached), *results]
        settled = analysis.catalog.get("doc_ids") if analysis.catalog.get("chosen") else []
        if settled:
            with self.deps.session_factory() as session:
                cards = catalog.catalog_evidence(session, settled)
            results += [cards] if cards else []
        if plan.read_top_document and settled:
            read = PlannedCall(
                "get_document", GetDocumentArgs(doc_id=settled[0]), "read the file asked about"
            )
            results.append(await self._call(ctx, trace_id, len(calls), read))
        elif plan.read_top_document:
            top = next((r for r in results if r.tool == "search_documents" and r.provenance), None)
            if top is not None and top.provenance[0].doc_id:
                results.append(
                    await self._call(
                        ctx, trace_id, len(calls), playbooks.read_document_call(top.provenance[0].doc_id)
                    )
                )
        if plan.external == "yes" or (
            plan.external == "if_gap" and not any(r.provenance and r.result for r in results)
        ):
            results.extend(await self._external(ctx, request))
        halted = [w for r in results for w in r.warnings if HALTED.search(w)]
        return ToolsDone(
            analysis=ev.analysis,
            results=[r.model_dump(mode="json") for r in results],
            caveats=list(
                dict.fromkeys([*plan.caveats, *analysis.catalog.get("caveats", []), *uncovered, *halted])
            ),
            started=ev.started,
        )

    async def _external(self, ctx: Context, request: dict) -> list[ToolResult]:
        """T6 under file 07 §6: generic needs from the question alone, each sanitized, at most three."""
        trace_id = request["trace_id"]
        policy = ExternalPolicy(**request["external"])
        _step(ctx, trace_id, "external", "planning", "Choosing what to look up outside", False)
        try:
            needs = await external_tools.needs_for(self.deps.gemini, request["question"], trace_id=trace_id)
        except GeminiError as exc:
            needs, note = [], f"external search unavailable: {str(exc)[:200]}"
        else:
            note = "the question has no need public sources could answer"
        _step(ctx, trace_id, "external", "planning", "Choosing what to look up outside", True)
        if not needs:
            return [
                ToolResult(
                    tool=external_tools.NAME,
                    result=None,
                    warnings=[note],
                    display=f"No external search: {note}.",
                )
            ]
        results = []
        for i, need in enumerate(needs[: external_tools.MAX_QUERIES]):
            step_id, description = f"external{i}", f"Searching outside sources ({need.purpose})"
            _step(ctx, trace_id, step_id, "tool", description, False, tool=external_tools.NAME)
            result = await external_tools.external_search(
                self.deps.gemini,
                need,
                policy=policy,
                trace_id=trace_id,
                resolve=external_tools.resolve_redirect,
                search_arxiv=external_tools.arxiv,
            )
            _step(ctx, trace_id, step_id, "tool", description, True, tool=external_tools.NAME)
            results.append(result)
        return results

    async def _attachments(self, ctx: Context, request: dict) -> list[attachment_tools.Attached]:
        """The files the user attached (answer-time only): fetched once, size-capped; a failure is skipped."""
        out = []
        for i, item in enumerate(request.get("attachments") or []):
            try:
                data = await asyncio.to_thread(self.deps.fetch_attachment, item["url"])
            except Exception as exc:  # noqa: BLE001 — an unreadable upload must not fail the answer
                log.warning("attachment %s of %s not fetched: %s", i, request["trace_id"], exc)
                continue
            out.append(attachment_tools.Attached(item["name"], item.get("mime_type") or "", data))
        return out

    async def _read_attachments(self, ctx, request: dict, attached) -> list[ToolResult]:
        results = []
        for i, item in enumerate(attached):
            step_id, description = f"attachment{i}", f"Reading your attachment {item.name}"
            _step(ctx, request["trace_id"], step_id, "tool", description, False, tool=attachment_tools.NAME)
            results.append(
                await attachment_tools.read_attachment(
                    self.deps.gemini, item, request["question"], trace_id=request["trace_id"]
                )
            )
            _step(ctx, request["trace_id"], step_id, "tool", description, True, tool=attachment_tools.NAME)
        return results

    async def _extract(
        self, request: dict, name: str, schema: type[BaseModel], version: str | None = None, **variables: str
    ) -> Any:
        """Tool arguments from the question (`<name>.v1` unless pinned); None when Gemini fails."""
        version = version or f"{name}.v1"
        prompt = load_prompt("engine", version)
        try:
            result = await self.deps.gemini.generate(
                model=model_id(),
                messages=[
                    Message.system(prompt.system),
                    Message.user(
                        prompt.render_user(question=request.get("asked") or request["question"], **variables)
                    ),
                ],
                context=CallContext(
                    purpose=f"engine.{name}",
                    prompt_version=version,
                    trace_id=request["trace_id"],
                ),
                schema=schema,
                thinking=ThinkingLevel.LOW,
            )
        except GeminiError:
            return None
        return result.parsed

    async def _call(self, ctx: Context, trace_id: str, index: int, call: PlannedCall) -> ToolResult:
        step_id = f"tool{index}"
        _step(ctx, trace_id, step_id, "tool", call.reason, False, tool=call.tool)
        started = time.monotonic()
        result = await asyncio.to_thread(self._run_tool, call)
        if call.tool == visual_tools.NAME and call.args.relook_question and self.deps.fetch_asset:
            try:
                result = await visual_tools.relook(
                    self.deps.gemini,
                    result,
                    call.args.relook_question,
                    fetch=self.deps.fetch_asset,
                    trace_id=trace_id,
                )
            except GeminiError as exc:
                result = result.model_copy(
                    update={"warnings": [*result.warnings, f"relook failed: {exc}"[:240]]}
                )
        _step(
            ctx,
            trace_id,
            step_id,
            "tool",
            call.reason,
            True,
            tool=call.tool,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    def _run_tool(self, call: PlannedCall) -> ToolResult:
        if call.tool == "physics_calculator":
            return physics_calculator(call.args)
        with self.deps.session_factory() as session:
            if call.tool == "search_documents":
                return search_documents(
                    session, call.args, embed_query=self.deps.embed_query, rerank=self.deps.rerank
                )
            if call.tool == "get_document":
                return get_document(session, call.args)
            if call.tool == telemetry_tools.NAME:
                return telemetry_tools.query_telemetry(
                    session,
                    call.args,
                    connect=self.deps.telemetry_connect,
                    put_asset=self.deps.put_asset,
                    presign=self.deps.presign,
                )
            if call.tool == visual_tools.NAME:
                return visual_tools.inspect_visuals(
                    session,
                    call.args,
                    embed_query=self.deps.embed_query,
                    rerank=self.deps.rerank,
                    presign=self.deps.presign,
                )
            if call.tool == "inspect_code_and_diagrams":

                def code_search(query, node_types):
                    args = SearchDocumentsArgs(query=query, filters={"node_types": node_types})
                    return search_documents(
                        session, args, embed_query=self.deps.embed_query, rerank=self.deps.rerank
                    )

                return inspect_code_and_diagrams(session, call.args, search=code_search)
        raise ValueError(f"unknown tool {call.tool}")

    # ------------------------------------------------------------------ steps 5–7: answer

    @step
    async def answer(self, ctx: Context, ev: ToolsDone) -> StopEvent:
        request = await ctx.store.get("request")
        analysis = load_analysis(ev.analysis)
        results = [ToolResult.model_validate(r) for r in ev.results]
        evidence = [r for r in results if r.provenance and r.result]
        if not evidence:
            searched = "\n".join(f"- {r.tool}: {r.display}" for r in results) or "- nothing could be searched"
            text = (
                "I found no internal evidence for this question.\n\nWhat was searched:\n"
                + searched
                + ("\n\n" + "\n".join(ev.caveats) if ev.caveats else "")
            )
            return self._finish(
                ctx,
                request["trace_id"],
                "insufficient_evidence",
                text,
                analysis,
                results,
                None,
                ev.started,
                caveats=ev.caveats,
                request=request,
            )
        _step(ctx, request["trace_id"], "synthesis", "synthesis", "Writing the answer", False)
        try:
            asked = request.get("asked") or request["question"]
            draft = await synthesis.answer(
                self.deps.gemini,
                asked
                if asked == request["question"]
                else f"{asked}\n(The user asked: {request['question']})",
                ev.analysis,
                results,
                language=analysis.raw.language,
                trace_id=request["trace_id"],
            )
        except GeminiError as exc:
            return self._extractive(ctx, request, analysis, results, ev, str(exc))
        _step(ctx, request["trace_id"], "synthesis", "synthesis", "Writing the answer", True)
        _step(
            ctx,
            request["trace_id"],
            "verification",
            "verification",
            f"Verified {len(draft.claims)} claims",
            True,
        )
        halted = [c for c in ev.caveats if HALTED.search(c)]
        markdown = draft.markdown + ("\n\n" + "\n".join(f"> Note: {c}" for c in halted) if halted else "")
        # sufficiency (file 07 §4): an answer none of whose claims the evidence entails did not find it
        supported = any(v.verdict == "entailed" for v in draft.verdicts)
        return self._finish(
            ctx,
            request["trace_id"],
            "answered" if supported else "insufficient_evidence",
            markdown,
            analysis,
            results,
            draft,
            ev.started,
            caveats=[*ev.caveats, *draft.caveats],
            citations=draft.citations,
            request=request,
        )

    def _extractive(self, ctx, request, analysis, results, ev, error: str) -> StopEvent:
        items = synthesis.evidence_items(results)[:EXTRACTIVE_PASSAGES]
        blocks = [
            f"**{i.source.label if i.source else i.tool}** [{i.id}]\n\n> {i.text[:1200]}" for i in items
        ]
        text, cited = synthesis.number_citations(
            "The answer model is unavailable, so here are the most relevant passages as found:\n\n"
            + "\n\n".join(blocks),
            [],
            items,
        )
        return self._finish(
            ctx,
            request["trace_id"],
            "extractive",
            text,
            analysis,
            results,
            None,
            ev.started,
            caveats=[*ev.caveats, f"synthesis unavailable: {error[:200]}"],
            citations=cited,
            request=request,
        )

    # ------------------------------------------------------------------ render and trace

    def _finish(
        self,
        ctx,
        trace_id,
        mode,
        markdown,
        analysis: Analysis,
        results: list[ToolResult],
        draft,
        started: float,
        *,
        caveats: list[str] | None = None,
        citations: list[Source] | None = None,
        request: dict | None = None,
    ) -> StopEvent:
        for embed in [*plot_embeds(results), *photo_strips(results)]:
            _emit(ctx, trace_id, embed)
        _tokens(ctx, trace_id, markdown)
        for n, source in enumerate(citations or [], start=1):
            _emit(
                ctx,
                trace_id,
                {
                    "type": "citation",
                    "citation_id": str(n),
                    "doc_id": str(source.doc_id) if source.doc_id else None,
                    "title": source.title or source.label,
                    "label": source.label,
                    "anchor": source.anchor,
                    "page_no": int(source.anchor.split(":")[1])
                    if source.anchor
                    and source.anchor.startswith("page:")
                    and source.anchor.split(":")[1].isdigit()
                    else None,
                    "provenance": str(source.provenance),
                    "language": source.language,
                    "translated": bool(source.language and source.language != analysis.raw.language),
                    "needs_review": source.needs_review,
                    "quote": None,
                    "url_viewer": self.deps.viewer_url(source.doc_id, source.anchor)
                    if source.doc_id
                    else None,
                    "url_onedrive": source.web_url,
                    "url_asset": None,
                },
            )
        verifier = draft.summary() if draft is not None else None
        latency = int((time.monotonic() - started) * 1000)
        done = {
            "type": "done",
            "trace_id": trace_id,
            "mode": mode,
            "answer_markdown": markdown,
            "caveats": caveats or [],
            "followups": draft.followups if draft else [],
            "verifier": verifier,
            "usage": {"tokens_in": 0, "tokens_out": 0, "cost_estimate": None},
            "latency_ms": latency,
        }
        _emit(ctx, trace_id, done)
        _SEQUENCES.pop(trace_id, None)
        request = request or {}
        trace = {
            "trace_id": trace_id,
            "question": request.get("question", ""),
            "chat_id": request.get("chat_id"),
            "message_id": request.get("message_id"),
            "user_id": request.get("user_id"),
            "conversation_summary": (request.get("history") or "")[-4000:] or None,
            "user_language": analysis.raw.language,
            "model_config": {
                "mode": mode,
                "gemini_model": model_id(),
                "gemini_lite_model": model_id(Tier.LITE),
                "external_mode": (request.get("external") or {}).get("mode"),
            },
            "query_analysis": dump_analysis(analysis),
            "tool_calls": [
                {
                    "tool": r.tool,
                    "call_id": r.call_id,
                    "warnings": r.warnings,
                    "display": r.display[:TRACE_DISPLAY],
                }
                for r in results
            ],
            "retrieved": [s.model_dump(mode="json") for r in results for s in r.provenance],
            "claims": [c.model_dump() for c in draft.claims] if draft else [],
            "citations": [s.model_dump(mode="json") for s in citations or []],
            "verifier_result": {
                "summary": verifier,
                "verdicts": [v.model_dump() for v in draft.verdicts],
                "numeric_mismatches": draft.numeric_mismatches,
            }
            if draft
            else None,
            "external_queries": [
                q
                for r in results
                if r.tool == external_tools.NAME and isinstance(r.result, dict)
                for q in r.result.get("external_queries", [])
            ],
            "answer_markdown": markdown,
            "mode": mode,
            "latency_ms": latency,
        }
        self.deps.save_trace(trace)
        return StopEvent(result=done)


TRACE_DISPLAY = 4000  # characters of each tool's display kept in the trace (benchmark drilldown)
IMG_STYLE = "width:160px;height:120px;object-fit:cover"


def _photo_cell(visual: dict) -> str:
    full = html.escape(visual.get("url_web") or visual["url_thumb"])
    thumb = html.escape(visual.get("url_thumb") or visual["url_web"])
    alt = html.escape(visual["breadcrumb"][:120])
    caption = html.escape((visual["title"] or "")[:60])
    return (
        f'<figure style="margin:0;width:160px"><a href="{full}" target="_blank">'
        f'<img src="{thumb}" alt="{alt}" style="{IMG_STYLE}"></a>'
        f'<figcaption style="font:12px sans-serif">{caption}</figcaption></figure>'
    )


def plot_embeds(results: list[ToolResult]) -> list[dict]:
    """One `plot` embed (presigned PNG link) per T2 plot."""
    return [
        {
            "type": "embed",
            "embed_id": f"plot-{result.call_id}-{i}",
            "kind": "plot",
            "url": plot["url"],
            "alt": plot["alt"],
            "height": 360,
        }
        for result in results
        if result.tool == telemetry_tools.NAME and isinstance(result.result, dict)
        for i, plot in enumerate(result.result.get("plots", []))
    ]


def photo_strips(results: list[ToolResult]) -> list[dict]:
    """One `photo_strip` embed per T3 result that has image links (self-contained HTML, escaped)."""
    embeds = []
    for result in results:
        if result.tool != visual_tools.NAME or not isinstance(result.result, dict):
            continue
        shown = [v for v in result.result.get("visuals", []) if v.get("url_thumb") or v.get("url_web")][:6]
        if not shown:
            continue
        cells = "".join(_photo_cell(v) for v in shown)
        embeds.append(
            {
                "type": "embed",
                "embed_id": f"photos-{result.call_id}",
                "kind": "photo_strip",
                "html": f'<div style="display:flex;gap:8px;flex-wrap:wrap">{cells}</div>',
                "alt": f"{len(shown)} images: " + "; ".join(v["breadcrumb"][:60] for v in shown),
                "height": 170,
            }
        )
    return embeds


def build_runtime(database_url: str, *, app_name: str = "dcl-answer-engine"):
    """DBOS durability (decision H8): one runtime per process, launched at API start-up."""
    from dbos import DBOS
    from llama_agents.dbos import DBOSRuntime

    DBOS(config={"name": app_name, "system_database_url": database_url})
    return DBOSRuntime()
