"""Route C for one document: load its primary file, rules and folder context, run the adapter, gate.

Called by ``dcl.process.route_c`` on ``telemetry_stream``. A clean result (every channel resolved, inside
its sanity range) is indexed by S2's ``index_document`` and committed (``backend/indexing/commit.py``):
``telemetry_runs``/``telemetry_channels`` rows, the run summary node, document status ACTIVE (or
ACTIVE_WITH_SOFT_FLAGS). Without an indexer the result is kept as ``{sha}/C/v1/processed.json`` and parked.
"""

import json
import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from minio import Minio
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.common.unit_reader import name_of
from backend.dispatcher.adapters import adapter_for
from backend.dispatcher.contract import (
    ConflictEvidence,
    ConflictSide,
    Flag,
    FlagAnchor,
    ProcessedDocument,
    SiblingUnit,
)
from backend.dispatcher.folder_context import FolderContext, with_folder_labels
from backend.dispatcher.location import primary_location
from backend.dispatcher.routing import PROCESSED_MARK
from backend.dispatcher.type_resolution import HEAD_BYTES
from backend.indexing.card import models_embedder, write_halted_card
from backend.indexing.commit import Indexer, commit_document
from backend.llm_engine.local_models import ModelServerUnavailable
from backend.postgres import pipeline_config
from backend.postgres.enums import (
    DocKind,
    DocumentSourceRole,
    DocumentStatus,
    DriveItemStatus,
    FlagSeverity,
    FlagType,
    NodeType,
    Route,
    RuleOrigin,
    RuleType,
)
from backend.postgres.models import Blob, Document, DocumentSource, DriveFolder, DriveItem, Rule, SyncRoot
from backend.review.proposals import refresh as refresh_proposals
from backend.review.rules import RuleRecord, RuleScope, RuleTarget
from backend.review.staged import GateResult, gate, load_staged
from backend.routes.c_telemetry.config_file import process_config
from backend.routes.c_telemetry.delimited import as_table, delimited_source, read_delimited, series_plan
from backend.routes.c_telemetry.ljstream_cfg import parse_ljstream_cfg
from backend.routes.c_telemetry.normalize import NormalizeConfig, sanity_ranges_from
from backend.routes.c_telemetry.run import PARSER_VERSION, FolderConfig, RunInputs, labjack_source
from backend.routes.c_telemetry.series import SeriesSource, process_series, slug, source_from_schema
from backend.routes.c_telemetry.suggest import with_suggestion
from backend.routes.c_telemetry.tables import header_unit, table_document, unit_flags
from backend.routes.c_telemetry.tdms import tdms_source
from backend.routes.c_telemetry.workbook import island_source, read_workbook
from backend.storage.minio import CIR, RAW, TELEMETRY, BucketStore, parse_uri

log = logging.getLogger(__name__)


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
    resume_from: tuple[SeriesSource, Path] | None = None,
) -> RouteCOutcome:
    """Run Route C for a PROCESSING document: the adapter that accepts its primary file builds the
    ``ProcessedDocument`` (a series run, a table document, a workbook with tables and runs, or a config
    document); the gate halts on HARD; a clean result is indexed and committed through ``indexer``, or,
    without one (tests, models role unreachable), kept as ``processed.json`` and parked.
    ``resume_from`` rebuilds a halted series run from its schema and ``raw.parquet``."""
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
    item = primary_location(session, blob.sha256)
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
    store = _BlobReader(minio, blob)
    cir = BucketStore(minio, CIR)
    series_args = _SeriesArgs(
        rules=channel_map_rules(session),
        telemetry=BucketStore(minio, TELEMETRY),
        cir=cir,
        config=NormalizeConfig.from_mapping(
            {
                key.removeprefix(TELEMETRY_PREFIX): value
                for key, value in pipeline_config.get_prefix(session, TELEMETRY_PREFIX).items()
            }
        ),
        sanity=sanity_ranges_from(pipeline_config.get(session, pipeline_config.SANITY_RANGES, default=None)),
    )
    inputs = RunInputs(
        blob_sha256=blob.sha256,
        name=item.name,
        context=context,
        target=target,
        folder_config=folder_ljstream_config(session, minio, item.parent_item_id),
    )
    if resume_from is not None:
        adapter_name = "resume"
        source, raw_path = resume_from
        processed = series_args.run(source, inputs, raw_path)
    else:
        adapter = adapter_for(Route.C, store.head(), item.name)
        if adapter is None:
            raise ValueError(f"no Route C adapter accepts {item.name}")
        adapter_name = adapter.name
        processed = _build(adapter_name, session, minio, store, item, inputs, series_args)
    propose = _unit_proposer(item, document) if cloud_allowed else None
    processed = processed.model_copy(update={"flags": [with_suggestion(f, propose) for f in processed.flags]})
    processed = with_folder_labels(processed, context)
    _apply_fields(document, processed)
    result: GateResult = gate(session, cir, document, processed, stale=_route_c_flag)
    if result.halted:
        write_halted_card(document, processed.document, embed=models_embedder())
    refresh_proposals(session, [document.doc_id])  # a rule's units are shown, never applied
    plan = None
    if not result.halted and indexer is not None:
        try:
            plan = indexer(session, result.document, document.doc_id, cloud_allowed)
        except ModelServerUnavailable as exc:
            log.warning("models role unreachable for %s; the clean result is parked: %s", doc_id, exc)
            plan = None  # models role unreachable: park the clean run (Lead 2026-10-22); a re-run commits it
    runs = processed.telemetry_runs
    rows = sum(r.n_rows or 0 for r in runs) if runs else None
    if plan is not None:
        committed = commit_document(
            session, document, result.document, plan, PIPELINE_VERSION, raw=BucketStore(minio, RAW)
        )
        return RouteCOutcome(doc_id, committed.status, rows, committed.channels, 0, result.soft)
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
            PROCESSED_MARK: {"adapter": adapter_name, "parser_version": PARSER_VERSION, "uri": uri_},
        }
    session.flush()
    channels = sum(len(r.channels) for r in runs)
    return RouteCOutcome(doc_id, document.status, rows, channels, result.hard, result.soft)


class _BlobReader:
    def __init__(self, minio: Minio, blob: Blob) -> None:
        self.minio, self.blob = minio, blob
        self.bucket, self.key = parse_uri(blob.minio_uri)

    def head(self) -> bytes:
        length = min(HEAD_BYTES, self.blob.size_bytes or HEAD_BYTES)
        response = self.minio.get_object(self.bucket, self.key, offset=0, length=length)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def stream(self):
        return self.minio.get_object(self.bucket, self.key)

    def read(self) -> bytes:
        response = self.stream()
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def download(self, path: Path) -> Path:
        self.minio.fget_object(self.bucket, self.key, str(path))
        return path


@dataclass
class _SeriesArgs:
    rules: tuple[list[RuleRecord], dict[uuid.UUID, dict]]
    telemetry: BucketStore
    cir: BucketStore
    config: NormalizeConfig
    sanity: list

    def run(
        self, source: SeriesSource, inputs: RunInputs, raw_parquet: Path | None = None
    ) -> ProcessedDocument:
        records, bodies = self.rules
        return process_series(
            source, inputs, records, bodies, self.telemetry, self.cir, self.config, self.sanity, raw_parquet
        )


def _build(
    adapter: str,
    session: Session,
    minio: Minio,
    store: _BlobReader,
    item: DriveItem,
    inputs: RunInputs,
    series: _SeriesArgs,
) -> ProcessedDocument:
    def cir_put(key: str, data: bytes) -> str:
        return series.cir.put(key, data, "application/json")

    if adapter == "labjack_dat":
        return series.run(labjack_source(store.stream, store.head(), item.name), inputs)
    if adapter == "config_file":
        return process_config(store.read(), inputs.blob_sha256, item.name, inputs.context, cir_put)
    if adapter == "tdms":
        with tempfile.TemporaryDirectory(prefix="dcl-tdms-") as workdir:
            path = store.download(Path(workdir) / "run.tdms")
            siblings = sibling_units(session, minio, item)
            return series.run(tdms_source(path, item.name, siblings), inputs)
    if adapter == "delimited":
        table = read_delimited(store.read())
        plan = series_plan(table)
        if plan is not None:
            return series.run(delimited_source(table, plan, item.name), inputs)
        as_tab = as_table(table, item.name)
        return table_document(
            inputs.blob_sha256,
            item.name,
            inputs.context,
            [as_tab],
            unit_flags(as_tab, table_units_elsewhere(session)),
            DocKind.ENGINEERING_TABLE,
            cir_put,
            PARSER_VERSION,
            catalog={"preamble": table.preamble, "footer": table.footer}
            if table.preamble or table.footer
            else None,
        )
    if adapter == "workbook":
        return _workbook_document(store.read(), item, inputs, series, cir_put, table_units_elsewhere(session))
    raise ValueError(f"unknown Route C adapter {adapter}")


def _doc_kind_for_workbook(name: str, sheets: list[str]) -> DocKind:
    text = " ".join([name, *sheets]).casefold()
    if any(word in text for word in ("fmea", "risk")):
        return DocKind.RISK_ASSESSMENT
    if any(word in text for word in ("setup", "test plan", "input param", "checklist")):
        return DocKind.TEST_PLAN
    if "calibrat" in text:
        return DocKind.CALIBRATION
    return DocKind.ENGINEERING_TABLE


def _workbook_document(
    data: bytes,
    item: DriveItem,
    inputs: RunInputs,
    series: _SeriesArgs,
    cir_put,
    same_name: dict[str, list[str]] | None = None,
) -> ProcessedDocument:
    from backend.common.office import convert

    if item.name.casefold().endswith(".xls"):
        data = convert(data, "xls", "xlsx")
    book = read_workbook(data, recalc=lambda raw: convert(raw, "xlsx", "xlsx", recalc=True))
    flags: list[Flag] = []
    for table in book.tables:
        flags += unit_flags(table, same_name)
    for sheet, cells in book.error_sheets.items():
        flags.append(_formula_conflict(sheet, cells, book.recalc_note))
    doc = table_document(
        inputs.blob_sha256,
        item.name,
        inputs.context,
        book.tables,
        flags,
        _doc_kind_for_workbook(item.name, book.sheets)
        if book.tables or not book.series
        else DocKind.TELEMETRY_RUN,
        cir_put,
        PARSER_VERSION,
        catalog={"sheets": book.sheets, "recalculated": book.recalculated}
        | ({"recalc_note": book.recalc_note} if book.recalc_note else {}),
    )
    for island in book.series:
        key = f"{island.sheet}!{island.cell_range}"
        run_doc = series.run(
            island_source(island, item.name),
            RunInputs(
                blob_sha256=inputs.blob_sha256,
                name=item.name,
                context=inputs.context,
                target=inputs.target,
                run_key=key,
                label_suffix=f"_{slug(island.sheet)}",
            ),
        )
        prefix = slug(key)
        doc = doc.model_copy(
            update={
                "nodes": [
                    *doc.nodes,
                    *[
                        n.model_copy(
                            update={
                                "ref": f"{prefix}.{n.ref}",
                                "parent_ref": f"{prefix}.{n.parent_ref}" if n.parent_ref else None,
                                "ordinal": len(doc.nodes) + n.ordinal,
                                "sheet_name": island.sheet,
                            }
                        )
                        for n in run_doc.nodes
                    ],
                ],
                "telemetry_runs": [*doc.telemetry_runs, *run_doc.telemetry_runs],
                "flags": [
                    *doc.flags,
                    *[
                        f.model_copy(update={"anchor": f.anchor.model_copy(update={"sheet": island.sheet})})
                        for f in run_doc.flags
                    ],
                ],
            }
        )
    return ProcessedDocument.model_validate(doc.model_dump())


def _formula_conflict(sheet: str, cells: list[str], note: str | None) -> Flag:
    return Flag(
        flag_type=FlagType.CONFLICT,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(sheet=sheet),
        evidence=ConflictEvidence(
            subject=f"formula errors in sheet {sheet}",
            relation="check_failed",
            a=ConflictSide(
                label="cells", value=", ".join(cells[:50]), provenance="cached values after recalculation"
            ),
            b=ConflictSide(
                label="expected", value="computed values", provenance=note or "LibreOffice recalculation"
            ),
        ),
    )


SIBLING_MAX_BYTES = 5 * 1024 * 1024


TABLE_UNITS_SQL = """
select u.key, coalesce(u.value, '')
from document_nodes n
join documents d on d.doc_id = n.doc_id,
lateral (
    select * from jsonb_each_text(
        case when jsonb_typeof(n.metadata -> 'units') = 'object' then n.metadata -> 'units' else '{}' end)
    union all
    select * from jsonb_each_text(
        case when jsonb_typeof(n.metadata -> 'column_units') = 'object' then n.metadata -> 'column_units'
        else '{}' end)
) u
where n.node_type = 'table' and d.status in ('ACTIVE', 'ACTIVE_WITH_SOFT_FLAGS')
"""


def table_units_elsewhere(session: Session) -> dict[str, list[str]]:
    """``{column name: units}`` for the shared reader's same-name check (plan step B): the units indexed
    tables state, and the ones people decided (``column_units``, written by a ``set_fact_unit`` decision; ""
    for "no unit needed"). A column named like those takes the unit when they all agree."""
    found: dict[str, list[str]] = {}
    for header, unit in session.execute(text(TABLE_UNITS_SQL)).all():
        found.setdefault(name_of(header), []).append(unit)
    return found


def sibling_units(session: Session, minio: Minio, item: DriveItem) -> list[SiblingUnit]:
    """Units stated by sibling exports of the same run (C.2 evidence): ``.csv`` files in the same folder
    or in a sub-folder named like the file (``Temperature.tdms`` ↔ ``Temperature/Analog … .csv``)."""
    stem = PurePosixPath(item.name).stem.casefold()
    folder_ids = [item.parent_item_id]
    for folder in session.scalars(
        select(DriveFolder).where(DriveFolder.parent_item_id == item.parent_item_id)
    ):
        if folder.name.casefold() == stem:
            folder_ids.append(folder.item_id)
    rows = session.execute(
        select(DriveItem.name, Blob)
        .join(Blob, Blob.sha256 == DriveItem.blob_sha256)
        .where(
            DriveItem.parent_item_id.in_(folder_ids),
            DriveItem.extension.in_([".csv", ".tsv"]),
            DriveItem.status == DriveItemStatus.LANDED,
            Blob.restricted.is_(False),
            Blob.size_bytes <= SIBLING_MAX_BYTES,
        )
        .order_by(DriveItem.name)
        .limit(5)
    ).all()
    found: list[SiblingUnit] = []
    for name, sibling in rows:
        bucket, key = parse_uri(sibling.minio_uri)
        response = minio.get_object(bucket, key)
        try:
            table = read_delimited(response.read())
        finally:
            response.close()
            response.release_conn()
        for cell in table.header:
            unit = header_unit(cell)
            if unit:
                found.append(SiblingUnit(file_name=name, channel=cell, unit=unit, source="header"))
    return found


def _route_c_flag(flag) -> bool:
    """Route C's own flags point at a channel (unit, bounds, t0); dispatcher and commit flags do not."""
    return bool((flag.anchor or {}).get("channel"))


def _unit_proposer(item: DriveItem, document: Document):
    """One model proposal per unit flag the file's own hints leave open (file 06 §5)."""
    from backend.dispatcher.runner import _gateway
    from backend.llm_engine.suggestions import propose_unit

    client, _ = _gateway()
    folder = (item.path_cached or "").rsplit("/", 1)[0]
    return lambda evidence: propose_unit(
        client, evidence, file_name=item.name, folder=folder, doc_id=str(document.doc_id)
    )


def resume_document(
    session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer | None = None
) -> RouteCOutcome:
    """``resume_from_staged`` for Route C (file 06 §7). A HALTED single-run document is rebuilt from its own
    ``schema.json`` and ``raw.parquet`` with the rules as they are now; the original file is not read again.
    A workbook (tables and several runs) is processed again from its file, which is small by nature."""
    document = session.get(Document, doc_id)
    if document is None or document.status != DocumentStatus.HALTED or document.route != "C":
        raise ValueError(f"document {doc_id} is not a HALTED Route C document")
    staged = load_staged(BucketStore(minio, CIR), document)
    document.status = DocumentStatus.PROCESSING
    document.staged_payload_uri = None
    session.flush()
    single_run = len(staged.telemetry_runs) == 1 and all(
        n.node_type == NodeType.RUN_SUMMARY for n in staged.nodes
    )
    if not single_run or staged.telemetry_runs[0].raw_parquet_uri is None:
        return process_document(session, minio, doc_id, indexer=indexer)
    run = staged.telemetry_runs[0]
    schema_bucket, schema_key = parse_uri(run.schema_uri)
    schema = json.loads(BucketStore(minio, schema_bucket).get(schema_key) or b"{}")
    if not schema.get("columns"):
        return process_document(session, minio, doc_id, indexer=indexer)
    name = session.scalar(
        select(DriveItem.name)
        .join(DocumentSource, DocumentSource.blob_sha256 == DriveItem.blob_sha256)
        .where(DocumentSource.doc_id == doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY)
        .limit(1)
    )
    bucket, key = parse_uri(run.raw_parquet_uri)
    with tempfile.TemporaryDirectory(prefix="dcl-resume-") as workdir:
        path = Path(workdir) / "raw.parquet"
        minio.fget_object(bucket, key, str(path))
        source = source_from_schema(schema, name or "")
        return process_document(session, minio, doc_id, indexer=indexer, resume_from=(source, path))


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


def unlocated_table_documents(session: Session) -> list[uuid.UUID]:
    """Committed Route C documents with a table or table_row node that has no stable-anchor locator
    (neither sheet + cell_range nor line_start): written before rows carried their positions."""
    from backend.postgres.models import DocumentNode

    rows = session.scalars(
        select(DocumentNode.doc_id)
        .join(Document, Document.doc_id == DocumentNode.doc_id)
        .where(
            Document.route == "C",
            Document.status.in_([DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS]),
            DocumentNode.node_type.in_([NodeType.TABLE, NodeType.TABLE_ROW]),
            DocumentNode.line_start.is_(None),
            DocumentNode.cell_range.is_(None),
        )
        .distinct()
    ).all()
    return list(rows)
