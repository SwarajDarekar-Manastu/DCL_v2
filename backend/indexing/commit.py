"""The index commit (file 04, last stage; file 06 §2): one transaction per document version.

Input: a ``ProcessedDocument`` that passed the validation gate and S2's ``IndexPlan`` for it. Written, in
order: new entities and aliases (refs → ids), the document's assets, its ``document_nodes`` (old rows of
this document deleted first), entity mentions, numeric facts, the telemetry catalog of its runs, and the
``documents`` row (enrichment, entity ids, search text, status). The caller owns the transaction.

- Status: ``ACTIVE_WITH_SOFT_FLAGS`` while the document has an open SOFT flag, else ``ACTIVE``. Nodes on a
  page (or, for a run summary, a channel) that an open SOFT flag points at get ``needs_review = true``.
- A document with an open HARD flag is refused (``HaltedDocument``): HALTED documents have no rows.
- Run labels are unique: a label already used by another document's run gets a ``_2``, ``_3`` suffix and
  a SOFT ``CONFLICT`` (file 03 §C.1 step 9).
- A test-plan id the route read from the content that differs from the folder-derived id is not settled
  silently: both are kept in ``metadata_sources.test_plan_ids`` and a SOFT test-plan ``CONFLICT`` is raised
  (Lead 2026-10-22: TP7 sheets printed "Test Plan 6"); ``documents.test_plan_id`` keeps the folder value
  until a reviewer chooses.

Decisions (a person's or a rule's) are applied as overlays on every commit (``overlays.py``, file 06 §8);
active rules answer the commit's own flags and act on the document (origin override, supersession).
"""

import dataclasses
import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.dispatcher.contract import ConflictEvidence, ConflictSide, Flag, FlagAnchor, ProcessedDocument
from backend.indexing.index_document import HaltedDocument, IndexPlan
from backend.indexing.overlays import overlay_document, overlay_plan, supersede
from backend.llm_engine.enrichment.entities import EntityRef
from backend.postgres.enums import (
    DocumentStatus,
    EntityCreatedBy,
    FlagSeverity,
    FlagStatus,
    FlagType,
    NodeType,
)
from backend.postgres.models import (
    Asset,
    Document,
    DocumentNode,
    Entity,
    EntityAlias,
    EntityMention,
    LlmCall,
    NumericFact,
    ReviewFlag,
    TelemetryChannel,
    TelemetryRun,
)
from backend.review.flags import upsert_document_flag
from backend.review.rule_answers import answer_flags, document_rules

Indexer = Callable[[Session, ProcessedDocument, uuid.UUID, bool], IndexPlan]

OPEN_STATUSES = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)
PROCESSED_MARK = "processed_awaiting_commit"


@dataclass
class CommitResult:
    doc_id: uuid.UUID
    status: DocumentStatus
    nodes: int = 0
    mentions: int = 0
    facts: int = 0
    runs: int = 0
    channels: int = 0
    new_entities: int = 0
    renamed_runs: dict[str, str] = field(default_factory=dict)


def _open_flags(session: Session, doc_id: uuid.UUID) -> list[ReviewFlag]:
    return list(
        session.scalars(
            select(ReviewFlag).where(ReviewFlag.doc_id == doc_id, ReviewFlag.status.in_(OPEN_STATUSES))
        )
    )


def _entity_ids(session: Session, plan: IndexPlan) -> tuple[dict[EntityRef, uuid.UUID], int]:
    """New entities and aliases are inserted idempotently; every ref of the plan maps to an id."""
    ids: dict[EntityRef, uuid.UUID] = {}
    created = 0
    for entity in plan.entities.new_entities:
        inserted = session.execute(
            insert(Entity)
            .values(
                type=str(entity.type),
                canonical_name=entity.canonical_name,
                canonical_key=entity.canonical_key,
                created_by=EntityCreatedBy.SYSTEM,
                first_seen_doc_id=plan.doc_id,
            )
            .on_conflict_do_nothing(index_elements=["type", "canonical_key"])
            .returning(Entity.entity_id)
        ).scalar()
        created += inserted is not None
        ids[entity.ref] = inserted or session.scalar(
            select(Entity.entity_id).where(
                Entity.type == str(entity.type), Entity.canonical_key == entity.canonical_key
            )
        )

    def resolve(ref: EntityRef) -> uuid.UUID:
        if isinstance(ref, uuid.UUID):
            return ref
        if ref not in ids:
            found = session.scalar(
                select(Entity.entity_id).where(Entity.type == ref[0], Entity.canonical_key == ref[1])
            )
            if found is None:
                raise LookupError(f"entity ref {ref} is neither new in the plan nor in the table")
            ids[ref] = found
        return ids[ref]

    for alias in plan.entities.new_aliases:
        session.execute(
            insert(EntityAlias)
            .values(
                type=str(alias.type),
                alias_key=alias.alias_key,
                entity_id=resolve(alias.entity),
                alias=alias.alias,
                created_by=str(alias.created_by),
                fuzzy_score=alias.fuzzy_score,
            )
            .on_conflict_do_nothing(index_elements=["type", "alias_key"])
        )
    for mention in plan.entities.mentions:
        resolve(mention.entity)
    return ids, created


def _asset_ids(session: Session, processed: ProcessedDocument) -> dict[str, uuid.UUID]:
    out: dict[str, uuid.UUID] = {}
    for asset in processed.assets:
        values = {
            "blob_sha256": processed.blob_sha256,
            "kind": str(asset.kind),
            "page_no": asset.page_no,
            "bbox": asset.bbox.model_dump() if asset.bbox else None,
            "t_ms": asset.t_ms,
            "width": asset.width,
            "height": asset.height,
            "bytes": asset.bytes,
            "phash": asset.phash,
            "exif": asset.exif,
        }
        out[asset.ref] = session.execute(
            insert(Asset)
            .values(minio_uri=asset.minio_uri, **values)
            .on_conflict_do_update(index_elements=["minio_uri"], set_=values)
            .returning(Asset.asset_id)
        ).scalar_one()
    return out


def _unique_label(session: Session, wanted: str, run_uuid: uuid.UUID) -> str:
    label, n = wanted, 1
    while True:
        holder = session.scalar(select(TelemetryRun.run_uuid).where(TelemetryRun.run_label == label))
        if holder is None or holder == run_uuid:
            return label
        n += 1
        label = f"{wanted}_{n}"


def _label_conflict(wanted: str, used: str) -> Flag:
    return Flag(
        flag_type=FlagType.CONFLICT,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(content_sha256=hashlib.sha256(f"run_label:{wanted}".encode()).hexdigest()[:16]),
        evidence=ConflictEvidence(
            subject=f"run label {wanted}",
            a=ConflictSide(label="this run", value=used, provenance="renamed at commit"),
            b=ConflictSide(label="existing run", value=wanted, provenance="telemetry_runs.run_label"),
        ),
    )


def _test_plan_conflict(folder_id: str, content_id: str) -> Flag:
    return Flag(
        flag_type=FlagType.CONFLICT,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(content_sha256=hashlib.sha256(b"test_plan_id").hexdigest()[:16]),
        evidence=ConflictEvidence(
            subject="test plan id",
            a=ConflictSide(label="folder", value=folder_id, provenance="folder path"),
            b=ConflictSide(
                label="content", value=content_id, provenance="read from the document by the route"
            ),
        ),
    )


def strip_nul(value: Any) -> Any:
    """``value`` with every NUL character removed from its strings, at any depth (pydantic models,
    dataclasses, lists, tuples, dicts). PostgreSQL text and jsonb refuse NUL (DECISIONS 2026-10-22)."""
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, BaseModel):
        return value.model_copy(
            update={name: strip_nul(getattr(value, name)) for name in type(value).model_fields}
        )
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        changes = {f.name: strip_nul(getattr(value, f.name)) for f in dataclasses.fields(value) if f.init}
        return dataclasses.replace(value, **changes)
    if isinstance(value, list):
        return [strip_nul(v) for v in value]
    if isinstance(value, tuple):
        return tuple(strip_nul(v) for v in value)
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    return value


def commit_document(
    session: Session,
    document: Document,
    processed: ProcessedDocument,
    plan: IndexPlan,
    pipeline_version: int,
    now: datetime | None = None,
    raw: Any = None,
) -> CommitResult:
    """``raw`` is the ``dcl-raw`` BucketStore; required when the document carries ``derived_blobs``."""
    processed, plan = strip_nul(processed), strip_nul(plan)
    if processed.derived_blobs and raw is None:
        raise ValueError("derived_blobs need the dcl-raw store")
    if processed.has_hard_flags or any(
        f.severity == FlagSeverity.HARD for f in _open_flags(session, document.doc_id)
    ):
        raise HaltedDocument(f"document {document.doc_id} has an open HARD flag; nothing is committed")
    if plan.doc_id != document.doc_id:
        raise ValueError("the index plan is for another document")
    doc_id = document.doc_id
    rules = document_rules(session, document)
    if rules.origin is not None:  # an origin_override rule wins over the folder's guess, nodes included
        override = {"source_origin": rules.origin.source_origin}
        if rules.origin.trust_tier is not None:
            override["trust_tier"] = rules.origin.trust_tier
        processed = processed.model_copy(update={"document": processed.document.model_copy(update=override)})
    overlay_plan(session, doc_id, plan)
    result = CommitResult(doc_id=doc_id, status=DocumentStatus.ACTIVE)

    entity_ids, result.new_entities = _entity_ids(session, plan)
    asset_ids = _asset_ids(session, processed)

    session.execute(delete(EntityMention).where(EntityMention.doc_id == doc_id))
    session.execute(delete(NumericFact).where(NumericFact.doc_id == doc_id))
    session.execute(delete(DocumentNode).where(DocumentNode.doc_id == doc_id))
    session.execute(delete(TelemetryRun).where(TelemetryRun.doc_id == doc_id))
    session.flush()

    # Run labels first: a rename shows in the flags, which decide the status.
    renamed: dict[uuid.UUID, str] = {}
    for run in processed.telemetry_runs:
        label = _unique_label(session, run.run_label, run.run_uuid)
        if label != run.run_label:
            renamed[run.run_uuid] = label
            result.renamed_runs[run.run_label] = label
            row = upsert_document_flag(
                session, doc_id, _label_conflict(run.run_label, label), str(processed.route)
            )
            answer_flags(session, document, [row])

    content_plan = processed.document.test_plan_id
    if content_plan and document.test_plan_id and content_plan.casefold() != document.test_plan_id.casefold():
        row = upsert_document_flag(
            session, doc_id, _test_plan_conflict(document.test_plan_id, content_plan), str(processed.route)
        )
        answer_flags(session, document, [row])  # the commit's own flags meet the rules too
        sources_ids = {"folder": document.test_plan_id, "content": content_plan}
    elif content_plan and not document.test_plan_id:
        document.test_plan_id = content_plan
        sources_ids = {"content": content_plan}
    else:
        sources_ids = None

    soft = [f for f in _open_flags(session, doc_id) if f.severity == FlagSeverity.SOFT]
    status = DocumentStatus.ACTIVE_WITH_SOFT_FLAGS if soft else DocumentStatus.ACTIVE
    result.status = status
    flagged_pages = {f.anchor.get("page") for f in soft if f.anchor.get("page") is not None}
    flagged_channels = any(f.anchor.get("channel") for f in soft)
    fields = processed.document

    node_ids = {node.ref: uuid.uuid4() for node in plan.nodes}
    for node in plan.nodes:
        needs_review = node.page_no in flagged_pages or (
            node.node_type == NodeType.RUN_SUMMARY and flagged_channels
        )
        session.add(
            DocumentNode(
                node_id=node_ids[node.ref],
                doc_id=doc_id,
                parent_node_id=node_ids.get(node.parent_ref) if node.parent_ref else None,
                node_type=str(node.node_type),
                level=node.level,
                ordinal=node.ordinal,
                breadcrumb=node.breadcrumb,
                language=node.language,
                content=node.content,
                content_codes=node.content_codes,
                content_sha256=node.content_sha256,
                embed_text=node.embed_text,
                embed_text_hash=node.embed_text_hash,
                embedding=node.embedding,
                image_embedding=node.image_embedding,
                embedding_model=plan.embedding_model if node.embedding is not None else None,
                token_count=node.token_count,
                page_no=node.page_no,
                page_end=node.page_end,
                bbox=[box.model_dump() for box in node.bboxes] or None,
                line_start=node.line_start,
                line_end=node.line_end,
                t_start_ms=node.t_start_ms,
                t_end_ms=node.t_end_ms,
                sheet_name=node.sheet_name,
                cell_range=node.cell_range,
                asset_id=asset_ids.get(node.asset_ref) if node.asset_ref else None,
                source=str(node.source),
                confidence=node.confidence,
                needs_review=needs_review,
                doc_kind=str(fields.doc_kind),
                test_plan_id=fields.test_plan_id,
                source_origin=str(fields.source_origin or document.source_origin),
                trust_tier=fields.trust_tier or document.trust_tier,
                doc_status=str(status),
                metadata_=node.metadata,
                pipeline_version=pipeline_version,
            )
        )
    session.flush()
    result.nodes = len(plan.nodes)

    for mention in plan.entities.mentions:
        session.add(
            EntityMention(
                node_id=node_ids[mention.node_ref],
                doc_id=doc_id,
                entity_id=mention.entity
                if isinstance(mention.entity, uuid.UUID)
                else entity_ids[mention.entity],
                surface=mention.surface,
                span_start=mention.span_start,
                span_end=mention.span_end,
                confidence=mention.confidence,
                source=str(mention.source),
            )
        )
    result.mentions = len(plan.entities.mentions)
    for fact in plan.facts:
        session.add(
            NumericFact(
                node_id=node_ids[fact.node_ref],
                doc_id=doc_id,
                quantity=str(fact.quantity),
                value_raw=fact.value_raw,
                unit_raw=fact.unit_raw,
                value_si=fact.value_si,
                unit_si=fact.unit_si,
                gauge_or_abs=str(fact.gauge_or_abs),
                context=fact.context,
                span_start=fact.span_start,
                span_end=fact.span_end,
                source=str(fact.source),
                confidence=fact.confidence,
                suspect=fact.suspect,
                needs_unit=fact.needs_unit,
            )
        )
    result.facts = len(plan.facts)

    for run in processed.telemetry_runs:
        session.add(
            TelemetryRun(
                run_uuid=run.run_uuid,
                run_label=renamed.get(run.run_uuid, run.run_label),
                doc_id=doc_id,
                blob_sha256=processed.blob_sha256,
                source_format=str(run.source_format),
                run_status=str(run.run_status),
                ambient_condition=str(run.ambient_condition),
                ambient_pressure_bar_abs=run.ambient_pressure_bar_abs,
                sampling_rate_hz_nominal=run.sampling_rate_hz_nominal,
                sampling_rate_hz_actual=run.sampling_rate_hz_actual,
                duration_s=run.duration_s,
                n_rows=run.n_rows,
                n_gaps=run.n_gaps,
                n_duplicate_ts=run.n_duplicate_ts,
                t0_ignition_ms=run.t0_ignition_ms,
                t0_method=run.t0_method,
                t0_confidence=run.t0_confidence,
                sub_runs=[s.model_dump(mode="json") for s in run.sub_runs],
                raw_parquet_uri=run.raw_parquet_uri,
                normalized_parquet_uri=run.normalized_parquet_uri,
                schema_uri=run.schema_uri,
                recorded_at=run.recorded_at,
                channel_map_rule_id=run.channel_map_rule_id,
                clock_offsets=run.clock_offsets,
            )
        )
        session.flush()
        for channel in run.channels:
            data = channel.model_dump(exclude={"sparkline_asset_ref"})
            data["quantity"] = str(channel.quantity) if channel.quantity else None
            data["gauge_or_abs"] = str(channel.gauge_or_abs)
            session.add(
                TelemetryChannel(
                    run_uuid=run.run_uuid,
                    sparkline_asset_id=asset_ids.get(channel.sparkline_asset_ref)
                    if channel.sparkline_asset_ref
                    else None,
                    **data,
                )
            )
            result.channels += 1
        result.runs += 1

    aggregated = plan.document
    document.title = fields.title or document.title
    document.doc_kind = str(fields.doc_kind)
    document.trust_tier = fields.trust_tier or document.trust_tier
    document.test_run_id = fields.test_run_id or document.test_run_id
    document.hardware_item = fields.hardware_item or document.hardware_item
    document.doc_date = fields.doc_date or document.doc_date
    document.date_source = fields.date_source or document.date_source
    document.unit_count = fields.unit_count
    document.page_count = fields.page_count
    document.language = fields.language
    document.source_origin = str(fields.source_origin) if fields.source_origin else document.source_origin
    document.publisher = fields.publisher or document.publisher
    document.external_ids = fields.external_ids.model_dump(exclude_none=True) or document.external_ids
    document.standard_id = fields.standard_id or document.standard_id
    document.standard_revision = fields.standard_revision or document.standard_revision
    document.classification_marking = fields.classification_marking or document.classification_marking
    document.languages_detected = fields.languages_detected or document.languages_detected
    document.number_locale = fields.number_locale or document.number_locale
    document.revision_marker = fields.revision_marker or document.revision_marker
    document.catalog = fields.catalog
    document.enrichment = aggregated.get("enrichment", {})
    document.entity_ids = list(
        dict.fromkeys(
            ref if isinstance(ref, uuid.UUID) else entity_ids[ref]
            for ref in aggregated.get("entity_refs", [])
            if isinstance(ref, uuid.UUID) or ref in entity_ids
        )
    )
    document.search_text = aggregated.get("search_text")
    document.card_codes = aggregated.get("card_codes")
    document.card_embedding = aggregated.get("card_embedding")
    document.status = str(status)
    document.staged_payload_uri = None
    document.pipeline_version = pipeline_version
    document.cir_uri = processed.cir_uri
    document.parser_version = processed.parser_version
    document.indexed_at = now or datetime.now(UTC)
    sources = dict(document.metadata_sources or {})
    sources.pop(PROCESSED_MARK, None)
    if sources_ids:
        sources["test_plan_ids"] = sources_ids
    if plan.warnings:
        sources["index_warnings"] = plan.warnings[:50]
    else:
        sources.pop("index_warnings", None)  # a clean re-run leaves no warning of an earlier one
    document.metadata_sources = sources
    overlay_document(session, document)
    for other_id in rules.superseded:
        supersede(session, document, other_id, "rule")
    document.cloud_processed = bool(
        session.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.doc_id == document.doc_id))
    )
    if document.revision_marker:
        from backend.indexing.revisions import apply_revisions

        apply_revisions(session, document)
        result.status = DocumentStatus(document.status)  # SUPERSEDED when a newer revision exists
    from backend.indexing.near_duplicates import apply_near_duplicates

    apply_near_duplicates(session, document)
    if processed.derived_blobs:
        from backend.storage.derived import register_derived_blobs

        register_derived_blobs(session, raw, processed.blob_sha256, processed.derived_blobs)
    session.flush()
    return result


def default_indexer(models_url: str, minio) -> Indexer:
    """S2's ``index_document`` with the models role (vectors and token counts), the alias index and this
    session's vector reuse. The Gemini client is created only for a root with ``sync_roots.cloud_allowed``.
    An unreachable models role raises ``ModelServerUnavailable``; the Route C pipeline then parks the run."""
    from backend.indexing.card import folder_path
    from backend.indexing.index_document import existing_vectors, index_document
    from backend.llm_engine.enrichment.entities import index_from_db
    from backend.llm_engine.local_models import ModelsClient
    from backend.postgres import pipeline_config
    from backend.storage.minio import BucketStore, parse_uri

    models = ModelsClient(base_url=models_url)
    gemini_holder: list = []

    def gemini():
        if not gemini_holder:
            from backend.llm_engine.gemini_client import GeminiClient, result_cache_store

            gemini_holder.append(GeminiClient(result_cache=result_cache_store()))
        return gemini_holder[0]

    def asset_bytes(minio_uri: str) -> bytes | None:
        bucket, key = parse_uri(minio_uri)
        return BucketStore(minio, bucket).get(key)

    def index(session: Session, doc: ProcessedDocument, doc_id: uuid.UUID, cloud_allowed: bool) -> IndexPlan:
        ranges = pipeline_config.get(session, pipeline_config.SANITY_RANGES, default=None) or {}
        return index_document(
            doc,
            doc_id=doc_id,
            gemini=gemini() if cloud_allowed else None,
            embed_documents=models.embed_documents,
            embed_images=models.embed_images,
            asset_bytes=asset_bytes,
            alias_index=index_from_db(session),
            reuse_vectors=lambda hashes: existing_vectors(session, doc_id, hashes),
            sanity_ranges=ranges.get("ranges", []),
            cloud_allowed=cloud_allowed,
            count_tokens=models.count_tokens,  # POST /tokenize/count; workers never import transformers
            folder_path=folder_path(session.get(Document, doc_id).folder_context),
        )

    return index
