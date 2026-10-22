"""Route C for one document: load its primary file, rules and folder context, run the adapter, gate.

Called by ``dcl.process.route_c`` on ``telemetry_stream``. A clean result (every channel resolved, inside
its sanity range) is indexed by S2's ``index_document`` and committed (``backend/indexing/commit.py``):
``telemetry_runs``/``telemetry_channels`` rows, the run summary node, document status ACTIVE (or
ACTIVE_WITH_SOFT_FLAGS). Without an indexer the result is kept as ``{sha}/C/v1/processed.json`` and parked.
"""

import json
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.folder_context import FolderContext
from backend.dispatcher.routing import PROCESSED_MARK
from backend.dispatcher.type_resolution import HEAD_BYTES
from backend.indexing.commit import Indexer, commit_document
from backend.llm_engine.local_models import ModelServerUnavailable
from backend.postgres import pipeline_config
from backend.postgres.enums import DocumentSourceRole, DocumentStatus, DriveItemStatus, RuleOrigin, RuleType
from backend.postgres.models import Blob, Document, DocumentSource, DriveFolder, DriveItem, Rule, SyncRoot
from backend.review.rules import RuleRecord, RuleScope, RuleTarget
from backend.review.staged import GateResult, gate, load_staged
from backend.routes.c_telemetry.ljstream_cfg import parse_ljstream_cfg
from backend.routes.c_telemetry.normalize import NormalizeConfig, sanity_ranges_from
from backend.routes.c_telemetry.run import PARSER_VERSION, FolderConfig, RunInputs, process_labjack
from backend.storage.minio import CIR, TELEMETRY, BucketStore, parse_uri


@dataclass(frozen=True)
class RouteCOutcome:
    doc_id: uuid.UUID
    status: str
    rows: int | None
    channels: int
    hard_flags: int
    soft_flags: int


def _folder_ids(session: Session, parent_item_id: str | None) -> list[str]:
    """The parent folder first, then its ancestors (the rule resolver's specificity order)."""
    chain: list[str] = []
    current = parent_item_id
    while current and current not in chain:
        chain.append(current)
        current = session.scalar(select(DriveFolder.parent_item_id).where(DriveFolder.item_id == current))
    return chain


CFG_MAX_BYTES = 1024 * 1024
PIPELINE_VERSION = 1
TELEMETRY_PREFIX = "telemetry."  # t0_pressure_slope_bar_s, t0_temperature_slope_k_s, … (NormalizeConfig)


def folder_ljstream_config(session: Session, minio: Minio, parent_item_id: str | None) -> FolderConfig | None:
    """The LJStreamM ``.cfg`` next to the run (``LJStreamM*.cfg`` first, then any ``.cfg`` that parses)."""
    if parent_item_id is None:
        return None
    rows = session.execute(
        select(DriveItem.name, Blob)
        .join(Blob, Blob.sha256 == DriveItem.blob_sha256)
        .where(
            DriveItem.parent_item_id == parent_item_id,
            DriveItem.extension == ".cfg",
            DriveItem.status == DriveItemStatus.LANDED,
            Blob.restricted.is_(False),
            Blob.size_bytes <= CFG_MAX_BYTES,
        )
    ).all()
    rows.sort(key=lambda row: (not row[0].casefold().startswith("ljstreamm"), row[0]))
    for name, cfg_blob in rows:
        bucket, key = parse_uri(cfg_blob.minio_uri)
        response = minio.get_object(bucket, key)
        try:
            config = parse_ljstream_cfg(response.read().decode("utf-8", "replace"))
        finally:
            response.close()
            response.release_conn()
        if config is not None and not config.scaling_disabled:
            return FolderConfig(file_name=name, config=config)
    return None


def channel_map_rules(session: Session) -> tuple[list[RuleRecord], dict[uuid.UUID, dict]]:
    rows = session.scalars(
        select(Rule).where(Rule.rule_type == RuleType.CHANNEL_MAP, Rule.active.is_(True))
    ).all()
    records = [
        RuleRecord(
            rule_id=row.rule_id,
            rule_type=RuleType(row.rule_type),
            origin=RuleOrigin(row.origin),
            scope=RuleScope(
                scope_root=row.scope_root,
                scope_folder_id=row.scope_folder_id,
                scope_filename_glob=row.scope_filename_glob,
                scope_extension=row.scope_extension,
            ),
            precedence=row.precedence,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return records, {row.rule_id: row.body for row in rows}


def process_document(
    session: Session,
    minio: Minio,
    doc_id: uuid.UUID,
    indexer: Indexer | None = None,
    raw_parquet: Path | None = None,
    header_text: str | None = None,
) -> RouteCOutcome:
    """Run Route C for a PROCESSING document. A clean result is indexed and committed through ``indexer``;
    without one (tests, or no models role) it is kept as ``processed.json`` and parked."""
    document = session.get(Document, doc_id)
    if document is None:
        raise LookupError(f"document {doc_id} does not exist")
    if document.status != DocumentStatus.PROCESSING:
        return RouteCOutcome(doc_id, document.status, None, 0, 0, 0)  # settled meanwhile: nothing to do
    blob = session.scalar(
        select(Blob)
        .join(DocumentSource, DocumentSource.blob_sha256 == Blob.sha256)
        .where(DocumentSource.doc_id == doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY)
    )
    item = session.scalar(
        select(DriveItem)
        .where(DriveItem.blob_sha256 == blob.sha256, DriveItem.status != DriveItemStatus.DELETED)
        .order_by(DriveItem.path_cached)
        .limit(1)
    )
    if item is None:
        raise LookupError(f"no live location holds the primary blob of {doc_id}")
    context = FolderContext.model_validate(document.folder_context)
    target = RuleTarget(
        root_name=item.root_name,
        folder_ids=_folder_ids(session, item.parent_item_id),
        file_name=item.name,
        extension=item.extension,
    )
    cloud_allowed = bool(
        session.scalar(select(SyncRoot.cloud_allowed).where(SyncRoot.root_name == item.root_name))
    )
    rules, bodies = channel_map_rules(session)
    bucket, key = parse_uri(blob.minio_uri)
    folder_config = folder_ljstream_config(session, minio, item.parent_item_id)

    def head() -> bytes:
        length = min(HEAD_BYTES, blob.size_bytes or HEAD_BYTES)
        response = minio.get_object(bucket, key, offset=0, length=length)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    cir = BucketStore(minio, CIR)
    processed = process_labjack(
        lambda: minio.get_object(bucket, key),
        RunInputs(
            blob_sha256=blob.sha256,
            name=item.name,
            context=context,
            target=target,
            folder_config=folder_config,
        ),
        rules,
        bodies,
        BucketStore(minio, TELEMETRY),
        cir,
        header_text.encode() if header_text is not None else head(),
        normalize_config=NormalizeConfig.from_mapping(
            {
                key.removeprefix(TELEMETRY_PREFIX): value
                for key, value in pipeline_config.get_prefix(session, TELEMETRY_PREFIX).items()
            }
        ),
        sanity=sanity_ranges_from(pipeline_config.get(session, pipeline_config.SANITY_RANGES, default=None)),
        raw_parquet=raw_parquet,
    )
    _apply_fields(document, processed)
    result: GateResult = gate(session, cir, document, processed, stale=_route_c_flag)
    plan = None
    if not result.halted and indexer is not None:
        try:
            plan = indexer(session, result.document, document.doc_id, cloud_allowed)
        except ModelServerUnavailable:
            plan = None  # models role unreachable: park the clean run (Lead 2026-10-22); a re-run commits it
    if plan is not None:
        committed = commit_document(session, document, result.document, plan, PIPELINE_VERSION)
        run = processed.telemetry_runs[0]
        return RouteCOutcome(doc_id, committed.status, run.n_rows, committed.channels, 0, result.soft)
    if not result.halted:
        uri_ = cir.put(
            f"{blob.sha256}/C/v{PARSER_VERSION}/processed.json",
            processed.model_dump_json().encode(),
            "application/json",
        )
        document.status = DocumentStatus.WAITING_FOR_ROUTE  # parked until an indexer is available
        document.staged_payload_uri = None
        document.metadata_sources = {
            **(document.metadata_sources or {}),
            PROCESSED_MARK: {"adapter": "labjack_dat", "parser_version": PARSER_VERSION, "uri": uri_},
        }
    session.flush()
    run = processed.telemetry_runs[0]
    return RouteCOutcome(doc_id, document.status, run.n_rows, len(run.channels), result.hard, result.soft)


def _route_c_flag(flag) -> bool:
    """Route C's own flags point at a channel (unit, bounds, t0); dispatcher and commit flags do not."""
    return bool((flag.anchor or {}).get("channel"))


def resume_document(
    session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer | None = None
) -> RouteCOutcome:
    """``resume_from_staged`` for Route C (file 06 §7): a HALTED run is rebuilt from its own
    ``raw.parquet`` with the rules as they are now; the ``.dat`` is not parsed again."""
    document = session.get(Document, doc_id)
    if document is None or document.status != DocumentStatus.HALTED or document.route != "C":
        raise ValueError(f"document {doc_id} is not a HALTED Route C document")
    staged = load_staged(BucketStore(minio, CIR), document)
    if not staged.telemetry_runs or staged.telemetry_runs[0].raw_parquet_uri is None:
        raise ValueError(f"the staged payload of {doc_id} has no raw Parquet; dispatch it again instead")
    run = staged.telemetry_runs[0]
    schema_bucket, schema_key = parse_uri(run.schema_uri)
    schema = json.loads(BucketStore(minio, schema_bucket).get(schema_key) or b"{}")
    if not schema.get("header_lines"):
        raise ValueError(f"the schema of {doc_id} has no header lines; dispatch it again instead")
    header_text = "\n".join(schema["header_lines"]) + "\n"
    bucket, key = parse_uri(run.raw_parquet_uri)
    with tempfile.TemporaryDirectory(prefix="dcl-resume-") as workdir:
        path = Path(workdir) / "raw.parquet"
        minio.fget_object(bucket, key, str(path))
        document.status = DocumentStatus.PROCESSING
        document.staged_payload_uri = None
        session.flush()
        return process_document(
            session, minio, doc_id, indexer=indexer, raw_parquet=path, header_text=header_text
        )


def halted_documents_for_rule(session: Session, rule_id: uuid.UUID) -> list[uuid.UUID]:
    """The HALTED Route C documents a channel_map rule applies to (file 06 §8 retroactive pass)."""
    from backend.review.rules import matches

    records, _ = channel_map_rules(session)
    rule = next((r for r in records if r.rule_id == rule_id), None)
    if rule is None:
        return []
    rows = session.execute(
        select(
            Document.doc_id,
            DriveItem.root_name,
            DriveItem.parent_item_id,
            DriveItem.name,
            DriveItem.extension,
        )
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .join(DriveItem, DriveItem.blob_sha256 == DocumentSource.blob_sha256)
        .where(
            Document.route == "C",
            Document.status == DocumentStatus.HALTED,
            DocumentSource.role == DocumentSourceRole.PRIMARY,
            DriveItem.status != DriveItemStatus.DELETED,
        )
    ).all()
    found: dict[uuid.UUID, None] = {}
    for doc_id, root, parent, name, extension in rows:
        target = RuleTarget(root, _folder_ids(session, parent), name, extension)
        if matches(rule, target):
            found[doc_id] = None
    return list(found)


def _apply_fields(document: Document, processed) -> None:
    fields = processed.document
    document.doc_kind = fields.doc_kind
    document.trust_tier = fields.trust_tier
    document.doc_date = fields.doc_date
    document.date_source = fields.date_source
    document.unit_count = fields.unit_count
