"""T3 `inspect_visuals` (file 07 §4): photos, plot figures, video frames and diagram renders.

Hybrid search (the T1 core) restricted to the node types of the requested kinds, optionally fused by RRF with
an image-embedding kNN on `document_nodes.image_embedding` from a reference asset. Every result carries its
reading, the containing document, presigned web and thumb URLs (15 min) and its anchor, never a node id.

`relook` sends the top ≤ 4 images with a question to Gemini (`relook.v1`); the answer is an answer-time
observation, returned to synthesis and the trace and never written to the index.
"""

import uuid
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import ARRAY, bindparam, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from backend.config import ThinkingLevel
from backend.indexing.anchors import NodeView, make_anchor
from backend.indexing.retrieval import (
    NODE_COLUMNS,
    Scope,
    SearchFilters,
    _documents,
    build_where,
    rrf,
    search,
)
from backend.llm_engine.engine.tools import Source, ToolResult, page_label, provenance_of
from backend.llm_engine.gemini_types import CallContext, Image, Message, Text
from backend.llm_engine.model_ids import model_id
from backend.llm_engine.prompts import load_prompt
from backend.postgres.enums import AssetKind, NodeType

NAME = "inspect_visuals"
DESCRIPTION = (
    "Find photos, plots, video frames and diagram renders, optionally similar to an image, and look again."
)
RELOOK_PROMPT = "relook.v1"
MAX_RELOOK = 4
VisualKind = Literal["hardware_photo", "plot_figure", "video_frame", "diagram"]
KIND_TYPES: dict[str, tuple[NodeType, ...]] = {
    "hardware_photo": (NodeType.PHOTO, NodeType.FIGURE),
    "plot_figure": (NodeType.FIGURE,),
    "video_frame": (NodeType.VIDEO_EVENT,),
    "diagram": (NodeType.DIAGRAM_SUMMARY, NodeType.FIGURE),
}
THUMB_OF = {AssetKind.PHOTO_WEB: AssetKind.PHOTO_THUMB}


class InspectVisualsArgs(BaseModel):
    query: str = ""
    kinds: list[VisualKind] = []
    test_plan_ids: list[str] = []
    failure_modes: list[str] = []
    components: list[str] = []
    k: int = Field(default=6, ge=1, le=20)
    similar_to_asset_id: uuid.UUID | None = None
    similar_to_vector: list[float] | None = Field(
        default=None, description="image embedding of a photo the user attached (answer-time only)"
    )
    relook_question: str | None = None
    user_language: str = "en"


class Visual(BaseModel):
    doc_id: uuid.UUID
    title: str | None
    anchor: str
    node_type: str
    reading: str
    breadcrumb: str
    page_no: int | None = None
    asset_uri: str | None = None
    url_web: str | None = None
    url_thumb: str | None = None
    similarity: float | None = None
    source: Source


class Observation(BaseModel):
    image: int
    observation: str
    visible: Literal["yes", "no", "unclear"]


class RelookAnswer(BaseModel):
    answer: str
    images: list[Observation] = []


def node_types(kinds: list[str]) -> list[str]:
    chosen = kinds or list(KIND_TYPES)
    return list(dict.fromkeys(str(t) for kind in chosen for t in KIND_TYPES[kind]))


def similar_images(session: Session, asset_id: uuid.UUID, filters: SearchFilters, k: int) -> list[Any]:
    """kNN on image embeddings from the reference asset's node, excluding the reference itself."""
    where = build_where(filters, Scope.CHILD)
    statement = text(
        f"SELECT {NODE_COLUMNS}, 1 - (image_embedding <=> ref.v) AS similarity "  # noqa: S608
        "FROM document_nodes, (SELECT image_embedding AS v FROM document_nodes "
        "  WHERE asset_id = :ref AND image_embedding IS NOT NULL LIMIT 1) ref "
        f"WHERE {where.sql} AND image_embedding IS NOT NULL AND asset_id IS DISTINCT FROM :ref "
        "ORDER BY image_embedding <=> ref.v LIMIT :k"
    ).bindparams(*where.binds, bindparam("ref", type_=UUID(as_uuid=True)))
    return list(session.execute(statement, {**where.params, "ref": asset_id, "k": k}))


def similar_to_vector(session: Session, vector: list[float], filters: SearchFilters, k: int) -> list[Any]:
    """kNN on image embeddings from an attached photo's embedding (file 07 §9.7; the photo is not stored)."""
    where = build_where(filters, Scope.CHILD)
    literal = "[" + ",".join(f"{v:.7f}" for v in vector) + "]"
    statement = text(
        f"SELECT {NODE_COLUMNS}, 1 - (image_embedding <=> CAST(:v AS halfvec(768))) AS similarity "  # noqa: S608
        f"FROM document_nodes WHERE {where.sql} AND image_embedding IS NOT NULL "
        "ORDER BY image_embedding <=> CAST(:v AS halfvec(768)) LIMIT :k"
    ).bindparams(*where.binds)
    return list(session.execute(statement, {**where.params, "v": literal, "k": k}))


def _assets(session: Session, asset_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str | None]]:
    """asset_id → (web URI, thumb URI) where a thumb of the same blob exists."""
    if not asset_ids:
        return {}
    statement = text(
        "SELECT a.asset_id, a.minio_uri, a.kind, "
        "(SELECT t.minio_uri FROM assets t WHERE t.blob_sha256 = a.blob_sha256 AND t.kind = :thumb "
        " AND t.page_no IS NOT DISTINCT FROM a.page_no LIMIT 1) AS thumb "
        "FROM assets a WHERE a.asset_id = ANY(:ids)"
    ).bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
    rows = session.execute(statement, {"ids": asset_ids, "thumb": str(AssetKind.PHOTO_THUMB)})
    return {r.asset_id: (r.minio_uri, r.thumb if r.kind == AssetKind.PHOTO_WEB else None) for r in rows}


def inspect_visuals(
    session: Session,
    args: InspectVisualsArgs,
    *,
    embed_query: Callable[[str], list[float]],
    rerank: Callable | None,
    presign: Callable[[str], str] | None = None,
) -> ToolResult:
    filters = SearchFilters(node_types=node_types(args.kinds), test_plan_ids=args.test_plan_ids)
    query = " ".join([args.query, *args.failure_modes, *args.components]).strip()
    warnings: list[str] = []
    by_key: dict[tuple, dict] = {}
    rankings: list[list[tuple]] = []
    if query:
        found = search(
            session,
            query,
            embed_query=embed_query,
            rerank=rerank,
            filters=filters,
            k=args.k * 2,
            user_language=args.user_language,
        )
        warnings += found.warnings
        for hit in found.hits:
            key = (hit.doc_id, hit.anchor)
            by_key.setdefault(key, {"hit": hit})
        rankings.append([(h.doc_id, h.anchor) for h in found.hits])
    if args.similar_to_asset_id or args.similar_to_vector:
        rows = (
            similar_to_vector(session, args.similar_to_vector, filters, args.k * 2)
            if args.similar_to_vector
            else similar_images(session, args.similar_to_asset_id, filters, args.k * 2)
        )
        if not rows:
            warnings.append("the reference image has no image embedding; similarity search skipped")
        documents = _documents(session, list({r.doc_id for r in rows}))
        ranking = []
        for row in rows:
            anchor = make_anchor(row.doc_id, NodeView.from_row(row)).serialize()
            key = (row.doc_id, anchor)
            entry = by_key.setdefault(key, {})
            entry.update(row=row, document=documents.get(row.doc_id), similarity=float(row.similarity))
            ranking.append(key)
        rankings.append(ranking)
    scores = rrf(rankings)
    ordered = sorted(by_key, key=lambda key: -scores.get(key, 0.0))[: args.k]
    asset_ids = [
        a for a in ((by_key[k].get("hit") or by_key[k]["row"]).asset_id for k in ordered) if a is not None
    ]
    assets = _assets(session, asset_ids)
    visuals = [_visual(by_key[key], assets, presign) for key in ordered]
    if not visuals:
        return ToolResult(
            tool=NAME,
            result={"visuals": [], "hits": []},
            warnings=warnings,
            display=f"No photos, figures or frames found for {query or 'the reference image'!r}.",
        )
    display = "\n".join(
        f"[{i}] {v.source.label} ({v.node_type}) — {v.breadcrumb}: {v.reading[:600]}"
        for i, v in enumerate(visuals, 1)
    )
    return ToolResult(
        tool=NAME,
        result={
            "visuals": [v.model_dump(mode="json", exclude={"source"}) for v in visuals],
            "hits": [{"parent_text": f"{v.breadcrumb}: {v.reading}"} for v in visuals],
        },
        provenance=[v.source for v in visuals],
        warnings=warnings,
        display=display,
    )


def _visual(entry: dict, assets: dict, presign) -> Visual:
    if hit := entry.get("hit"):
        doc_id, title, anchor, node_type, reading = (
            hit.doc_id,
            hit.title,
            hit.anchor,
            hit.node_type,
            hit.passage,
        )
        breadcrumb, page_no, asset_id = hit.breadcrumb, hit.page_no, hit.asset_id
        origin, kind, language, needs_review, web_url = (
            hit.source_origin,
            hit.doc_kind,
            hit.language,
            hit.needs_review,
            hit.web_url,
        )
    else:
        row, document = entry["row"], entry.get("document")
        doc_id, node_type, reading = row.doc_id, row.node_type, row.content
        title = document.title if document else None
        anchor = make_anchor(row.doc_id, NodeView.from_row(row)).serialize()
        breadcrumb, page_no, asset_id = row.breadcrumb or "", row.page_no, row.asset_id
        origin, kind, language, needs_review = row.source_origin, row.doc_kind, row.language, row.needs_review
        web_url = document.web_url if document else None
    web_uri, thumb_uri = assets.get(asset_id, (None, None)) if asset_id else (None, None)
    source = Source(
        doc_id=doc_id,
        anchor=anchor,
        title=title,
        label=page_label(title, page_no),
        provenance=provenance_of(origin, kind),
        language=language,
        needs_review=needs_review,
        web_url=web_url,
    )
    return Visual(
        doc_id=doc_id,
        title=title,
        anchor=anchor,
        node_type=node_type,
        reading=reading,
        breadcrumb=breadcrumb,
        page_no=page_no,
        asset_uri=web_uri,
        url_web=presign(web_uri) if presign and web_uri else None,
        url_thumb=presign(thumb_uri or web_uri) if presign and (thumb_uri or web_uri) else None,
        similarity=entry.get("similarity"),
        source=source,
    )


async def relook(
    client, result: ToolResult, question: str, *, fetch: Callable[[str], bytes], trace_id: str | None = None
) -> ToolResult:
    """Look again at the top ≤ 4 images with the question; an answer-time observation, never persisted."""
    visuals = [v for v in (result.result or {}).get("visuals", []) if v.get("asset_uri")][:MAX_RELOOK]
    if not visuals:
        return result.model_copy(update={"warnings": [*result.warnings, "no image to look at again"]})
    parts: list[Any] = []
    captions = []
    for i, visual in enumerate(visuals, start=1):
        parts += [Text(f"Image {i}"), Image(fetch(visual["asset_uri"]), _mime(visual["asset_uri"]))]
        captions.append(
            f"{i}. {visual['title'] or 'untitled'} — {visual['breadcrumb']}: {visual['reading'][:300]}"
        )
    prompt = load_prompt("vision", RELOOK_PROMPT)
    reply = await client.generate(
        model=model_id(),
        messages=[
            Message.system(prompt.system),
            Message.user(*parts, prompt.render_user(question=question, captions="\n".join(captions))),
        ],
        context=CallContext(purpose="engine.relook", prompt_version=RELOOK_PROMPT, trace_id=trace_id),
        schema=RelookAnswer,
        thinking=ThinkingLevel.LOW,
        media_resolution="high",
    )
    answer: RelookAnswer = reply.parsed
    lines = [f"Image {o.image}: {o.observation} (feature visible: {o.visible})" for o in answer.images]
    observation = (
        f"Answer-time observation by the vision model, not part of the indexed record. Question: {question}\n"
        f"{answer.answer}\n" + "\n".join(lines)
    )
    data = dict(result.result)
    data["relook"] = {
        "source": "relook",
        "question": question,
        **answer.model_dump(),
        "images_sent": len(visuals),
        "persisted": False,
    }
    data["hits"] = [*data.get("hits", []), {"parent_text": observation}]
    return result.model_copy(
        update={
            "result": data,
            "provenance": [*result.provenance, _looked_again(result.provenance[0])],
            "display": f"{result.display}\n\n{observation}",
        }
    )


def _looked_again(first: Source) -> Source:
    return first.model_copy(update={"label": f"{first.label} (looked at again)", "needs_review": True})


def _mime(uri: str) -> str:
    lower = uri.lower()
    return (
        "image/png" if lower.endswith(".png") else "image/webp" if lower.endswith(".webp") else "image/jpeg"
    )
