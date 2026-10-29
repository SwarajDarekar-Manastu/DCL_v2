"""The common tail of Phase 2 up to the commit (file 04 diagram): `ProcessedDocument` → `IndexPlan`.

S1's pipeline calls `index_document` after a route finished and the validation gate passed; S1's commit
(`backend/indexing/commit.py`) writes the returned plan in one transaction, applying review overlays there.
This module writes nothing. Its steps:

1. refuse a document with an open HARD flag (it is HALTED, nothing reaches the index);
2. chunk (`chunker.chunk_document`);
3. one enrichment call per parent when cloud processing is allowed for the document's root (file 01 §7);
   a parent whose reply fails the schema is skipped with a warning, BudgetExhausted propagates (retry later);
4. entity normalization over the alias index and numeric facts with the sanity rule; extracted items land on
   the child that contains them, else on the parent; route mentions map onto the chunk nodes they came from;
5. question-proxy nodes (file 04 §5.4) for every enriched section, whatever the document kind;
6. contextual headers with English canonical names and `embed_text` (`chunker.build_embed_texts`);
7. vectors reused by `embed_text_hash` from the document's current rows, the rest embedded through the
   models role; image nodes embedded from their asset bytes;
8. document aggregation (file 04 §3.4): `documents.enrichment`, entity refs, and the file's card
   (`indexing/card.py`: `search_text`, `card_codes`, `card_embedding`).
"""

import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Session
from sqlalchemy.types import Text

from backend.common.parallel import map_parallel
from backend.dispatcher.contract import ProcessedDocument
from backend.indexing.anchors import content_hash
from backend.indexing.card import card_codes, card_text, contents_of
from backend.indexing.chunker import (
    ChunkingConfig,
    IndexNode,
    TokenCounter,
    build_embed_texts,
    chunk_document,
)
from backend.indexing.identifiers import content_codes
from backend.llm_engine.enrichment.entities import AliasIndex, EntityDecisions, EntityRef, normalize
from backend.llm_engine.enrichment.extract import (
    Drops,
    EnrichedParent,
    EntityExtract,
    document_context,
    enrich_parent,
)
from backend.llm_engine.enrichment.numeric_facts import (
    DroppedFact,
    FactDecision,
    NumberLocale,
    fact_source,
    validate_fact,
)
from backend.llm_engine.gemini_types import StructuredOutputError
from backend.llm_engine.local_models import EMBEDDING_MODEL_TAG
from backend.postgres.enums import EntityType, MentionSource, NodeType, Route, SourceOrigin

EMBED_BATCH = 256
IMAGE_BATCH = 32
IMAGE_NODE_TYPES = frozenset({NodeType.PHOTO, NodeType.FIGURE})
ENTITY_TYPE_VALUES = frozenset(str(t) for t in EntityType)
TOP_ENTITIES = 20
SUMMARY_PARENTS = 2
AGGREGATED_TYPES = {
    EntityType.SUBSYSTEM: "subsystems",
    EntityType.MATERIAL: "materials",
    EntityType.PROPELLANT: "propellants",
    EntityType.FAILURE_MODE: "failure_modes",
}


def first_sentence(text: str | None, limit: int = 300) -> str | None:
    """The summary's first sentence for the header's About line (a long first sentence is cut at a word)."""
    text = " ".join((text or "").split())
    if not text:
        return None
    end = text.find(". ")
    sentence = text if end < 0 else text[: end + 1]
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0] + " …"


class HaltedDocument(ValueError):
    """A document with an open HARD flag is never indexed (file 06)."""


@dataclass
class IndexPlan:
    """Everything S1's commit writes for one document, in order: entities, aliases, nodes, mentions, facts,
    the documents row update. Refs (`IndexNode.ref`, entity refs) become ids inside that transaction."""

    doc_id: uuid.UUID
    nodes: list[IndexNode]
    entities: EntityDecisions
    facts: list[FactDecision]
    document: dict[str, Any]
    embedding_model: str = EMBEDDING_MODEL_TAG
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, int | float] = field(default_factory=dict)


def existing_vectors(session: Session, doc_id: uuid.UUID, hashes: Iterable[str]) -> dict[str, list[float]]:
    """Vectors of the document's current rows by `embed_text_hash`, read before the commit deletes them."""
    wanted = list(dict.fromkeys(hashes))
    if not wanted:
        return {}
    statement = text(
        "SELECT DISTINCT ON (embed_text_hash) embed_text_hash, embedding::text FROM document_nodes "
        "WHERE doc_id = :doc_id AND embedding IS NOT NULL AND embed_text_hash = ANY(:hashes)"
    ).bindparams(bindparam("doc_id", type_=UUID(as_uuid=True)), bindparam("hashes", type_=ARRAY(Text)))
    rows = session.execute(statement, {"doc_id": doc_id, "hashes": wanted})
    return {h: [float(x) for x in v.strip("[]").split(",")] for h, v in rows}


def _containing_node(
    nodes_by_parent: Mapping[str, list[IndexNode]], parent: IndexNode, fragment: str
) -> IndexNode:
    folded = fragment.casefold()
    for child in nodes_by_parent.get(parent.ref, []):
        if folded in child.content.casefold():
            return child
    return parent


def _question_proxy(parent: IndexNode, questions: list[str], ordinal_hint: int) -> IndexNode:
    content = "\n".join(questions)
    return IndexNode(
        ref=f"{parent.ref}#q",
        parent_ref=parent.ref,
        node_type=NodeType.QUESTION_PROXY,
        level=parent.level + 1,
        ordinal=ordinal_hint,
        breadcrumb=parent.breadcrumb,
        language="en",
        content=content,
        content_codes=content_codes(content),
        content_sha256=content_hash(content),
        token_count=0,
        page_no=parent.page_no,
        page_end=parent.page_end,
        line_start=parent.line_start,
        line_end=parent.line_end,
        t_start_ms=parent.t_start_ms,
        t_end_ms=parent.t_end_ms,
        sheet_name=parent.sheet_name,
        cell_range=parent.cell_range,
        source=parent.source,
        embed=True,
        origin_refs=list(parent.origin_refs),
    )


def _route_entity_pairs(
    doc: ProcessedDocument, nodes: list[IndexNode]
) -> tuple[list[tuple[str, EntityExtract]], int]:
    """Route mentions whose kind is an entity type, mapped from route refs to the smallest chunk node that
    holds the surface; other kinds (references, annotations, defined names) are not entity mentions."""
    by_origin: dict[str, list[IndexNode]] = {}
    for node in nodes:
        for origin in node.origin_refs:
            by_origin.setdefault(origin, []).append(node)
    pairs, skipped = [], 0
    for mention in doc.mentions:
        if mention.kind not in ENTITY_TYPE_VALUES:
            skipped += 1
            continue
        holders = [
            n
            for n in by_origin.get(mention.node_ref, [])
            if mention.surface.casefold() in n.content.casefold()
        ]
        if not holders:
            skipped += 1
            continue
        target = min(holders, key=lambda n: len(n.content))
        pairs.append((target.ref, EntityExtract(type=mention.kind, surface=mention.surface)))
    return pairs, skipped


def _aggregate(
    doc: ProcessedDocument,
    enriched: list[tuple[IndexNode, EnrichedParent]],
    decisions: EntityDecisions,
    index: AliasIndex,
) -> dict[str, Any]:
    """`documents` fields of file 04 §3.4, deterministic over the per-parent results."""
    counts: Counter[EntityRef] = Counter(m.entity for m in decisions.mentions)
    types = {m.entity: m.type for m in decisions.mentions}
    by_type: dict[str, list[str]] = {name: [] for name in AGGREGATED_TYPES.values()}
    for ref, _ in counts.most_common():
        name = AGGREGATED_TYPES.get(types[ref])
        if name and index.name(ref) not in by_type[name]:
            by_type[name].append(index.name(ref))
    summaries = [e.enrichment.summary for _, e in enriched[:SUMMARY_PARENTS] if e.enrichment.summary]
    publication = next(
        (e.enrichment.publication_type for _, e in enriched if e.enrichment.publication_type), None
    )
    kinds = Counter(e.enrichment.section_kind for _, e in enriched)

    def collect(attr: str) -> list[str]:
        return list(dict.fromkeys(str(x) for _, e in enriched for x in getattr(e.enrichment, attr)))

    entities_top = [index.name(ref) for ref, _ in counts.most_common(TOP_ENTITIES)]
    doc_summary = " ".join(summaries) or (doc.document.summary or "")
    enrichment = {
        "doc_kind_llm": kinds.most_common(1)[0][0] if kinds else None,
        "publication_type": publication,
        "doc_summary": doc_summary,
        "entities_top": entities_top,
        **by_type,
        "test_ids": collect("test_ids_mentioned"),
        "standards": collect("standards_mentioned"),
        "status_markers": collect("status_markers"),
        "languages_seen": sorted({n.language for n, _ in enriched if n.language}),
    }
    canonical_names = list(dict.fromkeys(index.name(ref) for ref in counts))
    return {"enrichment": enrichment, "entity_refs": list(counts), "entity_names": canonical_names}


def index_document(
    doc: ProcessedDocument,
    *,
    doc_id: uuid.UUID,
    gemini,
    embed_documents: Callable[[list[str], list[str | None]], list[list[float]]],
    embed_images: Callable[[list[bytes]], list[list[float]]] | None,
    asset_bytes: Callable[[str], bytes | None] | None,
    alias_index: AliasIndex,
    reuse_vectors: Callable[[list[str]], dict[str, list[float]]],
    sanity_ranges: Iterable[Mapping[str, Any]] = (),
    cloud_allowed: bool = True,
    config: ChunkingConfig | None = None,
    count_tokens: TokenCounter | None = None,
    folder_path: str | None = None,
) -> IndexPlan:
    """Build the IndexPlan. The callables are the models role (`ModelsClient.embed_documents`/`embed_images`),
    the asset store (`BucketStore(ASSETS).get` by key) and `existing_vectors` bound to a session."""
    if doc.has_hard_flags:
        raise HaltedDocument(
            f"document {doc_id} has an open HARD flag; it stays HALTED with its staged payload"
        )
    config = config or ChunkingConfig()
    nodes = chunk_document(doc, config, count_tokens)
    warnings: list[str] = []
    fields = doc.document
    parents = [n for n in nodes if n.node_type == NodeType.PARENT]
    children: dict[str, list[IndexNode]] = {}
    for node in nodes:
        if node.parent_ref:
            children.setdefault(node.parent_ref, []).append(node)

    enriched: list[tuple[IndexNode, EnrichedParent]] = []
    if not cloud_allowed:
        warnings.append("cloud processing not allowed for this root: no enrichment")
    elif doc.route != Route.B:  # manual 03 §6: Route B sends nothing to a model
        context = document_context(
            fields.title, str(fields.doc_kind), fields.source_origin, [fields.test_plan_id or ""]
        )

        def enrich(parent: IndexNode) -> EnrichedParent | None:
            try:
                return enrich_parent(
                    gemini,
                    parent.content,
                    context=context,
                    language=parent.language,
                    doc_id=str(doc_id),
                    anchor=None,
                )
            except StructuredOutputError:
                return None

        for parent, result in zip(parents, map_parallel(enrich, parents), strict=True):  # side by side
            if result is None:
                warnings.append(
                    f"enrichment reply for {parent.ref} failed the schema; parent left unenriched"
                )
            else:
                enriched.append((parent, result))

    pairs: list[tuple[str, EntityExtract]] = []
    for parent, result in enriched:
        for extract in result.enrichment.entities:
            pairs.append((_containing_node(children, parent, extract.surface).ref, extract))
    node_text = {n.ref: n.content for n in nodes}
    languages = {n.ref: n.language for n in nodes}
    decisions = normalize(pairs, node_text, alias_index, doc_id=doc_id, languages=languages)
    route_pairs, skipped_mentions = _route_entity_pairs(doc, nodes)
    normalize(
        route_pairs,
        node_text,
        alias_index,
        doc_id=doc_id,
        languages=languages,
        source=MentionSource.REGEX,
        decisions=decisions,
    )

    locale = NumberLocale.COMMA if fields.number_locale == "comma" else NumberLocale.DOT
    external = fields.source_origin == SourceOrigin.EXTERNAL_KEPT
    facts: list[FactDecision] = []
    dropped_facts = 0
    for parent, result in enriched:
        for extract in result.enrichment.numeric_facts:
            target = _containing_node(children, parent, extract.span)
            outcome = validate_fact(
                extract,
                node_ref=target.ref,
                node_text=target.content,
                locale=locale,
                source=fact_source(target.source, fields.source_origin, fields.doc_kind),
                ranges=sanity_ranges,
                external=external,
                confidence=target.confidence,
            )
            if isinstance(outcome, DroppedFact):
                dropped_facts += 1
            else:
                facts.append(outcome)

    for parent, result in enriched:  # every kind (user 2026-10-26): the questions come in the same reply
        if result.enrichment.questions_answered:
            nodes.append(_question_proxy(parent, result.enrichment.questions_answered, len(nodes)))
    for ordinal, node in enumerate(nodes):
        node.ordinal = ordinal

    entities_by_ref: dict[str, list[str]] = {}
    for mention in decisions.mentions:
        names = entities_by_ref.setdefault(mention.node_ref, [])
        name = alias_index.name(mention.entity)
        if name not in names:
            names.append(name)
    for parent in parents:
        merged = entities_by_ref.setdefault(parent.ref, [])
        for child in children.get(parent.ref, []):
            merged.extend(n for n in entities_by_ref.get(child.ref, []) if n not in merged)
    aggregated = _aggregate(doc, enriched, decisions, alias_index)
    about = first_sentence(aggregated["enrichment"]["doc_summary"])
    # each piece carries its own section's summary as the model wrote it (the prompt keeps it short)
    about_by_ref = {
        p.ref: " ".join(r.enrichment.summary.split()) for p, r in enriched if r.enrichment.summary
    }
    category = (fields.catalog or {}).get("recording_kind") or aggregated["enrichment"]["doc_kind_llm"]
    build_embed_texts(
        nodes,
        fields,
        entities_by_ref,
        config,
        count_tokens,
        about=about,
        about_by_ref=about_by_ref,
        category=category,
    )
    card = card_text(
        fields,
        category=category,
        folder_path=folder_path,
        summary=aggregated["enrichment"]["doc_summary"] or None,
        entities=aggregated.pop("entity_names"),
        contents=contents_of(nodes, fields.title),
    )
    aggregated |= {
        "search_text": card,
        "card_codes": card_codes(card),
        "card_embedding": embed_documents([card], [fields.title])[0],
    }

    to_embed = [n for n in nodes if n.embed and n.embed_text_hash]
    reused = reuse_vectors([n.embed_text_hash for n in to_embed])
    fresh = [n for n in to_embed if n.embed_text_hash not in reused]
    for node in to_embed:
        node.embedding = reused.get(node.embed_text_hash)
    for start in range(0, len(fresh), EMBED_BATCH):
        batch = fresh[start : start + EMBED_BATCH]
        vectors = embed_documents([n.embed_text for n in batch], [n.embed_title for n in batch])
        for node, vector in zip(batch, vectors, strict=True):
            node.embedding = vector

    image_nodes = [n for n in nodes if n.node_type in IMAGE_NODE_TYPES and n.asset_ref]
    images_embedded = 0
    if image_nodes and embed_images and asset_bytes:
        assets = {a.ref: a.minio_uri for a in doc.assets}
        loaded = [(n, asset_bytes(assets[n.asset_ref])) for n in image_nodes if n.asset_ref in assets]
        loaded = [(n, data) for n, data in loaded if data]
        for start in range(0, len(loaded), IMAGE_BATCH):
            batch = loaded[start : start + IMAGE_BATCH]
            for (node, _), vector in zip(batch, embed_images([data for _, data in batch]), strict=True):
                node.image_embedding = vector
                images_embedded += 1

    drops = [e.drops for _, e in enriched]
    for _, result in enriched:
        warnings.extend(result.warnings)
    return IndexPlan(
        doc_id=doc_id,
        nodes=nodes,
        entities=decisions,
        facts=facts,
        document=aggregated,
        warnings=warnings,
        metrics={
            "parents": len(parents),
            "enrichment_calls": len(enriched),
            "vectors_reused": len(to_embed) - len(fresh),
            "vectors_computed": len(fresh),
            "images_embedded": images_embedded,
            "facts": len(facts),
            "facts_dropped": dropped_facts,
            "route_mentions_skipped": skipped_mentions,
            "grounding_drop_rate": _overall_rate(drops),
        },
    )


def _overall_rate(drops: list[Drops]) -> float:
    dropped = sum(d.entities + d.numeric_facts + d.claims + d.identifiers for d in drops)
    total = dropped + sum(d.kept for d in drops)
    return dropped / total if total else 0.0


@dataclass(frozen=True)
class ReembedImpact:
    """What a change of `models.embedding` costs (file 08 §3.3: "requires re-embedding N nodes")."""

    text_nodes: int
    image_nodes: int
    documents: int

    @property
    def nodes(self) -> int:
        return self.text_nodes + self.image_nodes


REEMBED_SQL = (
    "SELECT count(*) FILTER (WHERE embedding IS NOT NULL) AS text_nodes, "
    "count(*) FILTER (WHERE image_embedding IS NOT NULL) AS image_nodes, "
    "count(DISTINCT doc_id) AS documents FROM document_nodes "
    "WHERE (embedding IS NOT NULL OR image_embedding IS NOT NULL) "
    "AND embedding_model IS DISTINCT FROM :model"
)


def reembed_impact(session: Session, new_model: str) -> ReembedImpact:
    """Nodes whose vectors were made by another model than `new_model` (text and image vectors share the
    model; spaces of different models are incompatible, file 01 §5). A reranker change re-embeds nothing."""
    row = session.execute(text(REEMBED_SQL), {"model": new_model}).one()
    return ReembedImpact(int(row.text_nodes), int(row.image_nodes), int(row.documents))
