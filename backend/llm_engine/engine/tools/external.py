"""T6 `external_search` (file 07 §4) under the web policy of §6.

The only text that leaves the network is a sanitized generic need. `external_intent.v1` writes the needs
from the user's question alone (never from retrieved text); each passes `sanitize_query` with the
proprietary terms of `answer.proprietary_terms`; a refused need is never sent. Providers:

- Gemini with Google Search grounding in an isolated call: the request holds the fixed one-line
  instruction of `external_search.v1` and the sanitized query, nothing else (no history, no context).
  The queries Google received come back in `result.grounding.queries` and go to the trace.
- arXiv API for `literature` (also the fallback when grounding is unavailable).

Results are `web` / `literature` sources with URLs; grounding redirect links are resolved best-effort.
Every query is recorded for `answer_traces.external_queries`: sanitized text, SHA-256 of the original,
provider, result count, and Google's queries.
"""

import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET  # noqa: S405 (a fixed public endpoint; expat refuses external entities)
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from backend.config import ThinkingLevel
from backend.llm_engine.engine.sanitizer import SanitizerRefused, sanitize_query
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult
from backend.llm_engine.gemini_types import CallContext, CapabilityUnavailable, GeminiError, Message
from backend.llm_engine.model_ids import model_id
from backend.llm_engine.prompts import load_prompt

NAME = "external_search"
SEARCH_PROMPT = "external_search.v1"
INTENT_PROMPT = "external_intent.v1"
MAX_QUERIES = 3
ARXIV_URL = "https://export.arxiv.org/api/query"
ARXIV_RESULTS = 5
ATOM = "{http://www.w3.org/2005/Atom}"
REDIRECT_HOST = "vertexaisearch.cloud.google.com"

Purpose = Literal["cots_component", "literature", "standard_text", "general_physics"]
ExternalMode = Literal["allow", "mock", "off"]


class ExternalSearchArgs(BaseModel):
    purpose: Purpose
    query_intent: str = Field(description="the generic need, never internal text or identifiers")


class ExternalNeeds(BaseModel):
    needs: list[ExternalSearchArgs] = Field(default_factory=list)  # capped in code, not by the schema


@dataclass(frozen=True)
class ExternalPolicy:
    """`pipeline_config` keys `answer.external_search_enabled`, `answer.external_allowed_groups`,
    `answer.proprietary_terms`; the mode comes from the request (benchmark `mock`)."""

    enabled: bool = True
    allowed_groups: tuple[str, ...] = ()
    proprietary_terms: tuple[str, ...] = ()
    mode: ExternalMode = "allow"

    def allows(self, groups: Iterable[str]) -> bool:
        return self.enabled and self.mode != "off" and bool(set(groups) & set(self.allowed_groups))


@dataclass
class Found:
    title: str
    url: str | None
    snippet: str
    provenance: Provenance


@dataclass
class ExternalCall:
    """One query for the trace (`external_queries`)."""

    purpose: str
    original_sha256: str
    sanitized: str | None
    provider: str
    result_count: int = 0
    google_queries: list[str] = field(default_factory=list)
    refused: str | None = None
    error: str | None = None

    def record(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [])}


async def needs_for(client, question: str, *, trace_id: str | None) -> list[ExternalSearchArgs]:
    """The generic needs of a question (the model sees the question only)."""
    prompt = load_prompt("engine", INTENT_PROMPT)
    result = await client.generate(
        model=model_id(),
        messages=[
            Message.system(prompt.system.replace("$limit", str(MAX_QUERIES))),
            Message.user(prompt.render_user(question=question)),
        ],
        context=CallContext(
            purpose="engine.external_intent", prompt_version=INTENT_PROMPT, trace_id=trace_id
        ),
        schema=ExternalNeeds,
        thinking=ThinkingLevel.LOW,
    )
    return result.parsed.needs[:MAX_QUERIES]


async def resolve_redirect(url: str | None) -> str | None:
    """Grounding sources are Vertex AI Search redirect links; the original page is their Location."""
    if not url or REDIRECT_HOST not in url:
        return url
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.head(url, follow_redirects=False)
        return response.headers.get("location") or url
    except httpx.HTTPError:
        return url


async def _grounded(client, query: str, call: ExternalCall, resolve, trace_id) -> list[Found]:
    prompt = load_prompt("engine", SEARCH_PROMPT)
    result = await client.generate(
        model=model_id(),
        messages=[Message.system(prompt.system), Message.user(prompt.render_user(query=query))],
        context=CallContext(
            purpose="engine.external_search", prompt_version=SEARCH_PROMPT, trace_id=trace_id
        ),
        google_search=True,
        thinking=ThinkingLevel.LOW,
    )
    grounding = result.grounding
    call.google_queries = list(grounding.queries) if grounding else []
    sources = list(grounding.sources) if grounding else []
    urls = await asyncio.gather(*(resolve(s.uri) for s in sources))
    found = [Found(result.text.strip(), None, result.text.strip(), Provenance.WEB)] if not sources else []
    for i, (source, url) in enumerate(zip(sources, urls, strict=True)):
        snippet = (
            result.text.strip() if i == 0 else f"Source cited by the summary above: {source.title or url}"
        )
        found.append(Found(source.title or url or "web source", url, snippet, Provenance.WEB))
    return found


def parse_arxiv(atom: str) -> list[Found]:
    root = ET.fromstring(atom)  # noqa: S314 (see the import)
    found = []
    for entry in root.findall(f"{ATOM}entry"):
        title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
        summary = " ".join((entry.findtext(f"{ATOM}summary") or "").split())
        published = (entry.findtext(f"{ATOM}published") or "")[:10]
        authors = [a.findtext(f"{ATOM}name") for a in entry.findall(f"{ATOM}author")]
        byline = ", ".join(a for a in authors[:3] if a) + (" et al." if len(authors) > 3 else "")
        url = entry.findtext(f"{ATOM}id")
        found.append(
            Found(title, url, f"{title} ({byline}, {published}). {summary[:1500]}", Provenance.LITERATURE)
        )
    return found


async def arxiv(query: str, *, http: httpx.AsyncClient | None = None) -> list[Found]:
    """All words first; arXiv's propulsion coverage is thin, so an empty result retries with any word,
    ranked by relevance (synthesis verification decides what is usable)."""
    words = re.findall(r"[\w-]+", query)[:8]
    attempts = [" AND ".join(f"all:{w}" for w in words), " OR ".join(f"all:{w}" for w in words)]
    own = http is None
    client = http or httpx.AsyncClient(timeout=15.0)
    try:
        for terms in attempts:
            params = {"search_query": terms, "max_results": str(ARXIV_RESULTS), "sortBy": "relevance"}
            response = await client.get(ARXIV_URL, params=params)
            response.raise_for_status()
            found = parse_arxiv(response.text)
            if found:
                return found
        return []
    finally:
        if own:
            await client.aclose()


def _mocked(query: str) -> list[Found]:
    return [
        Found(
            "mocked external source",
            "https://example.invalid/mock",
            f"(mock result for: {query})",
            Provenance.WEB,
        )
    ]


async def external_search(
    client,
    args: ExternalSearchArgs,
    *,
    policy: ExternalPolicy,
    trace_id: str | None = None,
    resolve: Callable[[str | None], Awaitable[str | None]] = resolve_redirect,
    search_arxiv: Callable[[str], Awaitable[list[Found]]] = arxiv,
) -> ToolResult:
    try:
        sanitized = sanitize_query(args.query_intent, proprietary_terms=policy.proprietary_terms)
    except SanitizerRefused as exc:
        original = ExternalCall(args.purpose, _sha(args.query_intent), None, "none", refused=str(exc))
        return ToolResult(
            tool=NAME,
            result={"external_queries": [original.record()]},
            warnings=[f"external query refused by the sanitizer: {exc}"],
            display="No external search: the need could not be written without internal details.",
        )
    query = sanitized.text
    calls: list[ExternalCall] = []
    found: list[Found] = []
    if policy.mode == "mock":
        call = ExternalCall(args.purpose, sanitized.original_sha256, query, "mock")
        found = _mocked(query)
        call.result_count = len(found)
        calls.append(call)
    else:
        grounded = ExternalCall(args.purpose, sanitized.original_sha256, query, "google_search")
        calls.append(grounded)
        try:
            web = await _grounded(client, query, grounded, resolve, trace_id)
            grounded.result_count = len(web)
            found += web
        except CapabilityUnavailable as exc:
            grounded.error = f"grounding unavailable: {exc}"
        except GeminiError as exc:
            grounded.error = f"grounded call failed: {type(exc).__name__}: {str(exc)[:200]}"
        if args.purpose == "literature":
            paper = ExternalCall(args.purpose, sanitized.original_sha256, query, "arxiv")
            calls.append(paper)
            try:
                papers = await search_arxiv(query)
                paper.result_count = len(papers)
                found += papers
            except (httpx.HTTPError, ET.ParseError) as exc:
                paper.error = f"arXiv failed: {type(exc).__name__}: {str(exc)[:200]}"
    sources = [
        Source(title=f.title, label=f"{f.title} (external)", provenance=f.provenance, url=f.url)
        for f in found
    ]
    display = "\n\n".join(f"[external] {f.snippet}" + (f" <{f.url}>" if f.url else "") for f in found)
    return ToolResult(
        tool=NAME,
        result={
            "hits": [{"parent_text": f.snippet} for f in found],
            "external_queries": [c.record() for c in calls],
            "query": query,
        },
        provenance=sources,
        warnings=[c.error for c in calls if c.error],
        display=display or f"No external results for: {query}",
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
