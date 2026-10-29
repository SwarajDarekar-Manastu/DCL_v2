"""Hybrid retrieval over `document_nodes` (file 07 §4 T1, file 04 §6). The core of `search_documents`.

1. Lexical query: the user's words plus alias surfaces of resolved entities; identifier tokens from the same
   `extract_identifiers` the indexer used for `content_codes`.
2. Dense leg: the query embedded by the models role (`task: search result | query: …`). When the filters
   select fewer than `EXACT_PATH_MAX` embedded nodes (one test plan, one document) the HNSW index is skipped
   and exact distances are computed over the filtered rows; otherwise HNSW with `ef_search = 200` and
   `iterative_scan = relaxed_order`.
3. Lexical leg: BM25 (pg_search) over `content` with the user's language field and English, `breadcrumb`,
   `content_codes` (the piece's and its header's identifiers), `content_en` and `embed_text` (the header with
   the piece). Field names are the pinned DDL (`bm25_document_nodes`, migrations 0004 and 0020).
4. RRF (k = 60); children and question proxies collapse to their parent keeping the best child; top 30.
   Preferred document and passage kinds (guesses of the query analysis) add two more legs over the matching
   rows: they rank higher, nothing is excluded.
5. Rerank the parents' best children with bge-reranker over the stored header (`embed_text`: title, kind,
   date, test labels, piece type, path, About line, entities) and the passage; the rank-1 minus rank-5
   margin is recorded. When the
   models role is down the RRF order is kept and the result says so (file 07 §12).
6. Near-duplicate collapse via `document_relations` NEAR_DUPLICATE: the newer document stays, the other is
   listed in `also_in`.
7. Hits carry the parent text, a stable anchor of the best child, document fields and `web_url`; a table or
   figure hit also carries the text of the section it sits in. Node ids exist only inside the request.

All SQL is templates with bound values; field and table names are constants, never user input.
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Session
from sqlalchemy.types import Text

from backend.dispatcher.contract import AnchorError
from backend.indexing.anchors import NodeView, make_anchor
from backend.indexing.identifiers import extract_identifiers
from backend.llm_engine.local_models import ModelServerUnavailable, RerankResult
from backend.postgres.enums import DocumentStatus, NodeType

RRF_K = 60
LEG_LIMIT = 50
PARENT_LIMIT = 30
EXACT_PATH_MAX = 5000
HNSW_EF_SEARCH = 200
RERANK_PASSAGE_CHARS = 2400
VISIBLE_STATUSES = (DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS)
SUPERSEDED_STATUSES = (*VISIBLE_STATUSES, DocumentStatus.SUPERSEDED)
LANGUAGE_FIELDS = {
    "en": "content_stem_en",
    "de": "content_stem_de",
    "fr": "content_stem_fr",
    "es": "content_stem_es",
    "it": "content_stem_it",
    "ru": "content_stem_ru",
    "ja": "content_ja",
    "ko": "content_ko",
    "zh": "content_zh",
}
COLLAPSING_TYPES = frozenset({NodeType.CHILD, NodeType.QUESTION_PROXY})
# a hit on one of these keeps its own text and anchor and brings its section's text along (chunker attaches
# tables and figures to the section they sit in)
SECTION_MEMBERS = frozenset({NodeType.TABLE, NodeType.FIGURE})
SECTION_CHARS = 4000


class Scope(StrEnum):
    CHILD = "child"
    PARENT = "parent"
    TABLES_ONLY = "tables_only"
    FIGURES_ONLY = "figures_only"


SCOPE_TYPES: dict[Scope, tuple[NodeType, ...] | None] = {
    Scope.CHILD: tuple(t for t in NodeType if t is not NodeType.PARENT),
    Scope.PARENT: (NodeType.PARENT,),
    Scope.TABLES_ONLY: (NodeType.TABLE, NodeType.TABLE_ROW),
    Scope.FIGURES_ONLY: (NodeType.FIGURE, NodeType.PHOTO),
}


class SearchFilters(BaseModel):
    """L1 filters of T1 (file 07 §4), applied on the columns denormalized onto `document_nodes`."""

    doc_ids: list[uuid.UUID] = Field(default_factory=list)
    doc_kinds: list[str] = Field(default_factory=list)
    test_plan_ids: list[str] = Field(default_factory=list)
    source_origins: list[str] = Field(default_factory=list)
    trust_tier_max: int | None = Field(default=None, ge=1, le=6)
    node_types: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    include_superseded: bool = False
    include_needs_review: bool = True
    # Guesses (the query-analysis model's document and passage kinds) rank matching passages higher and
    # exclude nothing: a wrong guess must never hide the answer.
    prefer_doc_kinds: list[str] = Field(default_factory=list)
    prefer_node_types: list[str] = Field(default_factory=list)
    # The files the catalog step resolved the question to, when the question did not type the label that pins
    # them (PLAN_query_routing.md step 1): ranked higher, never the only files searched.
    prefer_doc_ids: list[uuid.UUID] = Field(default_factory=list)


@dataclass
class Where:
    sql: str
    params: dict[str, Any]
    binds: list


def build_where(filters: SearchFilters, scope: Scope) -> Where:
    clauses = ["doc_status = ANY(:statuses)"]
    statuses = SUPERSEDED_STATUSES if filters.include_superseded else VISIBLE_STATUSES
    params: dict[str, Any] = {"statuses": [str(s) for s in statuses]}
    binds = [bindparam("statuses", type_=ARRAY(Text))]

    def any_of(column: str, values: list, sql_type) -> None:
        if values:
            clauses.append(f"{column} = ANY(:{column}_values)")
            params[f"{column}_values"] = values
            binds.append(bindparam(f"{column}_values", type_=ARRAY(sql_type)))

    node_types = filters.node_types or [str(t) for t in SCOPE_TYPES[scope] or ()]
    any_of("doc_id", filters.doc_ids, UUID(as_uuid=True))
    any_of("doc_kind", filters.doc_kinds, Text)
    any_of("test_plan_id", filters.test_plan_ids, Text)
    any_of("source_origin", filters.source_origins, Text)
    any_of("node_type", node_types, Text)
    any_of("language", filters.languages, Text)
    if filters.trust_tier_max is not None:
        clauses.append("trust_tier <= :trust_tier_max")
        params["trust_tier_max"] = filters.trust_tier_max
    if not filters.include_needs_review:
        clauses.append("needs_review = false")
    return Where(" AND ".join(clauses), params, binds)


def _execute(session: Session, sql: str, where: Where, **extra):
    statement = text(sql).bindparams(*where.binds)
    return session.execute(statement, {**where.params, **extra}).all()


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


def dense_leg(
    session: Session, query_vector: list[float], where: Where, limit: int = LEG_LIMIT
) -> tuple[list[uuid.UUID], str]:
    """(node ids by cosine distance, path used: 'exact' or 'hnsw')."""
    selected = _execute(
        session,
        f"SELECT count(*) FROM (SELECT 1 FROM document_nodes WHERE embedding IS NOT NULL AND {where.sql} "  # noqa: S608 (constant fragments, bound values)
        f"LIMIT {EXACT_PATH_MAX}) AS s",
        where,
    )[0][0]
    q = _vector_literal(query_vector)
    if selected < EXACT_PATH_MAX:
        rows = _execute(
            session,
            "WITH candidates AS MATERIALIZED (SELECT node_id, embedding FROM document_nodes "  # noqa: S608 (constant fragments, bound values)
            f"WHERE embedding IS NOT NULL AND {where.sql}) "
            "SELECT node_id FROM candidates ORDER BY embedding <=> CAST(:q AS halfvec(768)) LIMIT :limit",
            where,
            q=q,
            limit=limit,
        )
        return [r[0] for r in rows], "exact"
    session.execute(text(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}"))
    session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    rows = _execute(
        session,
        "SELECT node_id, embedding <=> CAST(:q AS halfvec(768)) AS distance FROM document_nodes "  # noqa: S608 (constant fragments, bound values)
        f"WHERE embedding IS NOT NULL AND {where.sql} "
        "ORDER BY embedding <=> CAST(:q AS halfvec(768)) LIMIT :limit",
        where,
        q=q,
        limit=limit,
    )
    return [r[0] for r in sorted(rows, key=lambda r: r[1])], "hnsw"


def lexical_leg(
    session: Session,
    query_text: str,
    codes: list[str],
    languages: Iterable[str],
    where: Where,
    limit: int = LEG_LIMIT,
) -> list[uuid.UUID]:
    fields = ["content"] + [
        f"(content::pdb.alias('{LANGUAGE_FIELDS[lang]}'))"
        for lang in dict.fromkeys(languages)
        if lang in LANGUAGE_FIELDS
    ]
    matches = [f"{f} ||| :q" for f in fields] + [
        "breadcrumb ||| :q",
        "content_en ||| :q",
        "embed_text ||| :q",
    ]
    extra: dict[str, Any] = {"q": query_text, "limit": limit}
    if codes:
        matches.append("content_codes ||| :codes")
        extra["codes"] = " ".join(codes)
    rows = _execute(
        session,
        "SELECT node_id, pdb.score(node_id) AS score FROM document_nodes "  # noqa: S608 (constant fragments, bound values)
        f"WHERE ({' OR '.join(matches)}) AND {where.sql} ORDER BY score DESC LIMIT :limit",
        where,
        **extra,
    )
    return [r[0] for r in rows]


def rrf(rankings: Iterable[list[uuid.UUID]], k: int = RRF_K) -> dict[uuid.UUID, float]:
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, node_id in enumerate(ranking, start=1):
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank)
    return scores


NODE_COLUMNS = (
    "node_id, doc_id, parent_node_id, node_type, ordinal, content, content_sha256, breadcrumb, language, "
    "page_no, page_end, line_start, line_end, t_start_ms, t_end_ms, sheet_name, cell_range, bbox, "
    "needs_review, doc_kind, test_plan_id, source_origin, trust_tier, asset_id, embed_text, metadata"
)


def _load_nodes(session: Session, node_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Any]:
    ids = list(dict.fromkeys(node_ids))
    if not ids:
        return {}
    statement = text(f"SELECT {NODE_COLUMNS} FROM document_nodes WHERE node_id = ANY(:ids)").bindparams(  # noqa: S608 (constant fragments, bound values)
        bindparam("ids", type_=ARRAY(UUID(as_uuid=True)))
    )
    return {row.node_id: row for row in session.execute(statement, {"ids": ids})}


def _rerank_text(row) -> str:
    """What the reranker reads: the passage's stored header (title, kind, date, test labels, piece type, path,
    the file's About line, entities), then the passage. Bare text alone loses which file a passage is from."""
    return (row.embed_text or row.content)[:RERANK_PASSAGE_CHARS]


def _anchor(row, fallback) -> str:
    """The serialized anchor of the passage; a node without a locator borrows its parent's."""
    for candidate in (row, fallback):
        try:
            return make_anchor(candidate.doc_id, NodeView.from_row(candidate)).serialize()
        except AnchorError:
            continue
    raise AnchorError(f"neither the passage nor its parent has a locator (doc {row.doc_id})")


@dataclass
class Candidate:
    """One parent-level result: the parent (or a stand-alone special node) and its best-scoring child."""

    key: uuid.UUID
    best: Any
    score: float
    parent: Any = None
    rerank_score: float | None = None
    also_in: list[uuid.UUID] = field(default_factory=list)


def collapse(
    scores: dict[uuid.UUID, float], rows: dict[uuid.UUID, Any], limit: int = PARENT_LIMIT
) -> list[Candidate]:
    groups: dict[uuid.UUID, Candidate] = {}
    for node_id, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        row = rows.get(node_id)
        if row is None:
            continue
        key = row.parent_node_id if row.node_type in COLLAPSING_TYPES and row.parent_node_id else node_id
        if key not in groups:
            groups[key] = Candidate(key=key, best=row, score=score)
        elif (
            groups[key].best.node_type == NodeType.QUESTION_PROXY and row.node_type != NodeType.QUESTION_PROXY
        ):
            groups[key].best = row
    return list(groups.values())[:limit]


class Hit(BaseModel):
    doc_id: uuid.UUID
    title: str | None
    anchor: str = Field(description="<kind>:<value>:<content_sha256> of the best passage")
    parent_text: str
    passage: str
    node_type: str
    breadcrumb: str
    page_no: int | None
    doc_kind: str | None
    source_origin: str | None
    trust_tier: int | None
    language: str | None
    needs_review: bool
    doc_date: date | None
    test_plan_id: str | None
    test_run_id: str | None
    hardware_item: str | None
    web_url: str | None
    asset_id: uuid.UUID | None
    rrf_score: float
    rerank_score: float | None
    also_in: list[uuid.UUID] = []
    section_text: str | None = Field(
        default=None, description="the text of the section a table or figure sits in (its parent)"
    )
    sheet_name: str | None = None
    table_summary: str | None = Field(default=None, description="caption, rows and columns of a table hit")


class SearchResult(BaseModel):
    hits: list[Hit]
    warnings: list[str] = []
    dense_path: str | None = None
    rerank_margin_1_5: float | None = None
    leg_counts: dict[str, int] = {}


def _documents(session: Session, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not doc_ids:
        return {}
    statement = text(
        "SELECT d.doc_id, d.title, d.doc_date, d.created_at, d.test_run_id, d.hardware_item, "
        "(SELECT di.web_url FROM document_sources ds JOIN drive_items di ON di.blob_sha256 = ds.blob_sha256 "
        " WHERE ds.doc_id = d.doc_id AND ds.role = 'primary' AND di.deleted_at IS NULL "
        " ORDER BY di.last_modified_at DESC NULLS LAST LIMIT 1) AS web_url "
        "FROM documents d WHERE d.doc_id = ANY(:ids)"
    ).bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
    return {row.doc_id: row for row in session.execute(statement, {"ids": doc_ids})}


def _near_duplicates(session: Session, doc_ids: list[uuid.UUID]) -> list[tuple[uuid.UUID, uuid.UUID]]:
    if len(doc_ids) < 2:
        return []
    statement = text(
        "SELECT doc_id_a, doc_id_b FROM document_relations WHERE relation = 'NEAR_DUPLICATE' "
        "AND doc_id_a = ANY(:ids) AND doc_id_b = ANY(:ids)"
    ).bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
    return [(r[0], r[1]) for r in session.execute(statement, {"ids": doc_ids})]


def _drop_near_duplicates(ordered: list[Candidate], pairs, documents) -> list[Candidate]:
    def newer(a: uuid.UUID, b: uuid.UUID) -> uuid.UUID:
        da, db = documents.get(a), documents.get(b)
        key = lambda d: (d.doc_date or date.min, d.created_at) if d else (date.min, None)  # noqa: E731
        return a if key(da) >= key(db) else b

    present = {c.best.doc_id for c in ordered}
    loser_to_winner = {}
    for a, b in pairs:
        if a in present and b in present:
            winner = newer(a, b)
            loser_to_winner[b if winner == a else a] = winner
    kept = [c for c in ordered if c.best.doc_id not in loser_to_winner]
    for loser, winner in loser_to_winner.items():
        for candidate in kept:
            if candidate.best.doc_id == winner and loser not in candidate.also_in:
                candidate.also_in.append(loser)
    return kept


def search(
    session: Session,
    query: str,
    *,
    embed_query: Callable[[str], list[float]],
    rerank: Callable[[str, list[str]], RerankResult] | None,
    filters: SearchFilters | None = None,
    scope: Scope = Scope.CHILD,
    k: int = 8,
    user_language: str = "en",
    alias_surfaces: Iterable[str] = (),
) -> SearchResult:
    """T1 core. `embed_query`/`rerank` are the models role (ModelsClient.embed_queries / .rerank)."""
    filters = filters or SearchFilters()
    where = build_where(filters, scope)
    surfaces = list(dict.fromkeys(alias_surfaces))
    lexical_text = " ".join([query, *surfaces])
    codes = extract_identifiers(lexical_text)
    warnings: list[str] = []

    query_vector = embed_query(query)
    dense, path = dense_leg(session, query_vector, where)
    lexical = lexical_leg(session, lexical_text, codes, [user_language, "en"], where)
    rankings = [dense, lexical]
    if filters.prefer_doc_kinds or filters.prefer_node_types:
        preferred = build_where(
            filters.model_copy(
                update={
                    "doc_kinds": [*filters.doc_kinds, *filters.prefer_doc_kinds],
                    "node_types": [*filters.node_types, *filters.prefer_node_types],
                }
            ),
            scope,
        )
        rankings += [
            dense_leg(session, query_vector, preferred)[0],
            lexical_leg(session, lexical_text, codes, [user_language, "en"], preferred),
        ]
    if filters.prefer_doc_ids and not filters.doc_ids:
        files = build_where(filters.model_copy(update={"doc_ids": filters.prefer_doc_ids}), scope)
        rankings += [
            dense_leg(session, query_vector, files)[0],
            lexical_leg(session, lexical_text, codes, [user_language, "en"], files),
        ]
    scores = rrf(rankings)
    rows = _load_nodes(session, scores)
    candidates = collapse(scores, rows)
    parents = _load_nodes(session, [c.key for c in candidates if c.key not in rows])
    for c in candidates:
        c.parent = parents.get(c.key) or rows.get(c.key) or c.best
        if c.best.node_type == NodeType.QUESTION_PROXY:
            c.best = c.parent

    margin = None
    ordered = candidates
    if rerank is not None and candidates:
        try:
            result = rerank(query, [_rerank_text(c.best) for c in candidates])
            for i, score in enumerate(result.scores):
                candidates[i].rerank_score = score
            ordered = [candidates[i] for i in result.order]
            margin = result.margin_1_5
        except ModelServerUnavailable:
            warnings.append("reranker unavailable; results are in RRF order")

    doc_ids = list(dict.fromkeys(c.best.doc_id for c in ordered))
    documents = _documents(session, doc_ids)
    ordered = _drop_near_duplicates(ordered, _near_duplicates(session, doc_ids), documents)

    sections = _load_nodes(
        session,
        [
            c.best.parent_node_id
            for c in ordered[: k * 2]
            if c.best.node_type in SECTION_MEMBERS and c.best.parent_node_id
        ],
    )
    hits = []
    unanchored: set[uuid.UUID] = set()
    for c in ordered:
        if len(hits) == k:
            break
        try:
            anchor = _anchor(c.best, c.parent)
        except AnchorError:
            unanchored.add(c.best.doc_id)  # a route wrote a node without a locator: not citable, skipped
            continue
        doc = documents.get(c.best.doc_id)
        hits.append(
            Hit(
                doc_id=c.best.doc_id,
                title=doc.title if doc else None,
                anchor=anchor,
                parent_text=c.parent.content,
                passage=c.best.content,
                node_type=c.best.node_type,
                breadcrumb=c.best.breadcrumb or "",
                page_no=c.best.page_no,
                doc_kind=c.best.doc_kind,
                source_origin=c.best.source_origin,
                trust_tier=c.best.trust_tier,
                language=c.best.language,
                needs_review=c.best.needs_review,
                doc_date=doc.doc_date if doc else None,
                test_plan_id=c.best.test_plan_id,
                test_run_id=doc.test_run_id if doc else None,
                hardware_item=doc.hardware_item if doc else None,
                web_url=doc.web_url if doc else None,
                asset_id=c.best.asset_id,
                rrf_score=c.score,
                rerank_score=c.rerank_score,
                also_in=c.also_in,
                sheet_name=c.best.sheet_name,
                table_summary=(c.best.metadata or {}).get("summary"),
                section_text=(
                    sections[c.best.parent_node_id].content[:SECTION_CHARS]
                    if c.best.node_type in SECTION_MEMBERS and c.best.parent_node_id in sections
                    else None
                ),
            )
        )
    if unanchored:
        warnings.append(
            f"{len(unanchored)} document(s) skipped: their passages have no page, line, time or cell locator "
            f"({', '.join(sorted(str(d) for d in unanchored)[:3])})"
        )
    return SearchResult(
        hits=hits,
        warnings=warnings,
        dense_path=path,
        rerank_margin_1_5=margin,
        leg_counts={"dense": len(dense), "lexical": len(lexical), "parents": len(candidates)},
    )
