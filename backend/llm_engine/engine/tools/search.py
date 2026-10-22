"""T1 `search_documents` (file 07 §4): hybrid retrieval with alias expansion and the widening order.

The lexical leg is expanded with every alias surface of the entities query analysis resolved (all languages
the alias table knows: `HTP` → `hydrogen peroxide`, `H2O2`, `Wasserstoffperoxid`). Zero hits widen in the
manual's order — drop `doc_kinds`, then `test_plan_ids`, then switch to parent scope — and the result says
which filters were dropped. Each hit is quoted in `display` with its label, provenance and review marker.
"""

import uuid
from collections.abc import Callable

from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Session

from backend.indexing.retrieval import Hit, Scope, SearchFilters, search
from backend.llm_engine.engine.tools import Source, ToolResult, page_label, provenance_of
from backend.llm_engine.local_models import RerankResult

NAME = "search_documents"
DESCRIPTION = (
    "Hybrid search over every indexed document (reports, standards, datasheets, papers, code, slides, photo "
    "readings). Use filters for test plans, document kinds, origin and language; use scope tables_only for "
    "numbers in tables and figures_only for plots."
)
PARENT_CHARS = 7000


class SearchDocumentsArgs(BaseModel):
    query: str = Field(min_length=1)
    sub_queries: list[str] = []
    filters: SearchFilters = SearchFilters()
    entity_ids: list[uuid.UUID] = Field(
        default_factory=list, description="entities resolved by query analysis"
    )
    k: int = Field(default=8, ge=1, le=30)
    scope: Scope = Scope.CHILD
    user_language: str = "en"


def alias_surfaces(session: Session, entity_ids: list[uuid.UUID]) -> list[str]:
    if not entity_ids:
        return []
    statement = text(
        "SELECT canonical_name AS surface FROM entities WHERE entity_id = ANY(:ids) "
        "UNION SELECT alias FROM entity_aliases WHERE entity_id = ANY(:ids)"
    ).bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
    return sorted({row.surface for row in session.execute(statement, {"ids": entity_ids})})


def widening_steps(args: SearchDocumentsArgs) -> list[tuple[str, SearchFilters, Scope]]:
    steps = [("as asked", args.filters, args.scope)]
    filters = args.filters
    if filters.doc_kinds:
        filters = filters.model_copy(update={"doc_kinds": []})
        steps.append(("dropped doc_kinds", filters, args.scope))
    if filters.test_plan_ids:
        filters = filters.model_copy(update={"test_plan_ids": []})
        steps.append(("dropped test_plan_ids", filters, args.scope))
    if args.scope != Scope.PARENT:
        steps.append(("parent scope", filters, Scope.PARENT))
    return steps


def source_of(hit: Hit) -> Source:
    return Source(
        doc_id=hit.doc_id,
        anchor=hit.anchor,
        title=hit.title,
        label=page_label(hit.title, hit.page_no),
        provenance=provenance_of(hit.source_origin, hit.doc_kind),
        language=hit.language,
        needs_review=hit.needs_review,
        web_url=hit.web_url,
    )


def render(hits: list[Hit], sources: list[Source]) -> str:
    blocks = []
    for i, (hit, source) in enumerate(zip(hits, sources, strict=True), start=1):
        marks = [str(source.provenance)]
        if hit.language and hit.language != "en":
            marks.append(f"language {hit.language}")
        if hit.needs_review:
            marks.append("⚠ unverified extraction")
        if hit.also_in:
            marks.append(f"also in {len(hit.also_in)} near-duplicate(s)")
        text_ = hit.parent_text[:PARENT_CHARS]
        blocks.append(f"[{i}] {source.label} ({', '.join(marks)}) — {hit.breadcrumb}\n{text_}")
    return "\n\n".join(blocks)


def search_documents(
    session: Session,
    args: SearchDocumentsArgs,
    *,
    embed_query: Callable[[str], list[float]],
    rerank: Callable[[str, list[str]], RerankResult] | None,
) -> ToolResult:
    surfaces = alias_surfaces(session, args.entity_ids)
    query = " ".join([args.query, *args.sub_queries])
    warnings: list[str] = []
    tried: list[str] = []
    for label, filters, scope in widening_steps(args):
        tried.append(label)
        result = search(
            session,
            query,
            embed_query=embed_query,
            rerank=rerank,
            filters=filters,
            scope=scope,
            k=args.k,
            user_language=args.user_language,
            alias_surfaces=surfaces,
        )
        warnings += [w for w in result.warnings if w not in warnings]
        if result.hits:
            if label != "as asked":
                warnings.append(f"no hits with the requested filters; widened: {', '.join(tried[1:])}")
            sources = [source_of(h) for h in result.hits]
            return ToolResult(
                tool=NAME,
                result={
                    "hits": [h.model_dump(mode="json") for h in result.hits],
                    "widened": tried[1:],
                    "dense_path": result.dense_path,
                    "rerank_margin_1_5": result.rerank_margin_1_5,
                    "leg_counts": result.leg_counts,
                    "alias_surfaces": surfaces,
                },
                provenance=sources,
                warnings=warnings,
                display=render(result.hits, sources),
            )
    searched = (
        f"query {query!r}, filters {args.filters.model_dump(exclude_defaults=True)}, scopes tried: {tried}"
    )
    return ToolResult(
        tool=NAME,
        result={"hits": [], "widened": tried[1:]},
        warnings=warnings,
        display=f"No internal document matches ({searched}).",
    )
