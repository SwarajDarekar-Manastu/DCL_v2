"""Dispatch (file 03 §1, §1.6, §12): landed blobs inside ``processing.scope`` become documents.

For each processing-scope subtree: the eligible items (LANDED, Tier-4 inspected, not restricted)
are typed from their first bytes, assembled into logical documents, and written as ``documents`` +
``document_sources`` rows. One document per primary blob: content that already belongs to a
document (a copy in another folder) is skipped. Route gating: no adapter → ``UNSUPPORTED_FORMAT``
HARD and HALTED with a staged payload; a route that is disabled (``routes.<X>.enabled``, default
false) or has no implementation yet → ``WAITING_FOR_ROUTE`` without a flag. Assembler and folder
uncertainties are SOFT ``CONFLICT`` flags.

CLI: ``python -m backend.dispatcher.routing dispatch`` (uses DCL_DATABASE_URL and the .env).
"""

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.adapters import Adapter, adapter_for
from backend.dispatcher.assembler import DocumentPlan, FileRef, assemble, load_section_file_sets
from backend.dispatcher.contract import ConflictEvidence, ConflictSide, Flag, FlagAnchor, ParseFailureEvidence
from backend.dispatcher.folder_context import FolderContext, Sibling, build_folder_context
from backend.dispatcher.type_resolution import HEAD_BYTES, ResolvedType, resolve_type
from backend.postgres import pipeline_config
from backend.postgres.enums import (
    DocumentSourceRole,
    DocumentStatus,
    DriveItemStatus,
    FlagSeverity,
    FlagType,
    Route,
    SourceOrigin,
)
from backend.postgres.models import (
    Blob,
    BlobDerivation,
    Document,
    DocumentRelation,
    DocumentSource,
    DriveFolder,
    DriveItem,
    ReviewFlag,
    SyncRoot,
)
from backend.review.flags import upsert_document_flag
from backend.storage.minio import CIR, BucketStore, parse_uri, uri
from backend.sync.inspect import zip_member_names
from backend.sync.scope import in_scope

PROCESSED_MARK = "processed_awaiting_commit"  # set by a route whose commit path is not there yet


@dataclass(frozen=True)
class Release:
    doc_id: uuid.UUID
    task: str
    queue: str


@dataclass
class DispatchResult:
    created: int = 0
    superseded: int = 0
    waiting: int = 0
    halted: int = 0
    skipped_existing: int = 0
    conflicts: int = 0
    released: int = 0
    by_route: dict[str, int] = field(default_factory=dict)
    to_process: list[Release] = field(default_factory=list)


@dataclass(frozen=True)
class Candidate:
    item: DriveItem
    folder_names: list[str]
    resolved: ResolvedType


def enabled_routes(session: Session) -> set[Route]:
    return {r for r in Route if pipeline_config.get(session, f"routes.{r}.enabled", default=False) is True}


@dataclass(frozen=True)
class RouteGate:
    """What may run now: the routes that are on, minus the file kinds parked by ``routes.held_kinds``."""

    on: frozenset[Route]
    held_kinds: frozenset[str] = frozenset()

    def runs(self, route: Route | None, kind: str) -> bool:
        return route in self.on and kind not in self.held_kinds


def route_gate(session: Session) -> RouteGate:
    held = pipeline_config.get(session, pipeline_config.HELD_KINDS, default=[]) or []
    return RouteGate(frozenset(enabled_routes(session)), frozenset(held))


def _read(minio: Minio, blob: Blob, length: int | None = None) -> bytes:
    bucket, key = parse_uri(blob.minio_uri)
    response = minio.get_object(bucket, key, offset=0, length=length or blob.size_bytes)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _resolve(minio: Minio, blob: Blob, name: str, head: bytes) -> ResolvedType:
    """Type from the first bytes; ZIP-based files also by their member names (DOCX/PPTX/XLSX/.wbpz)."""
    zip_names = None
    if head.startswith(b"PK\x03\x04"):
        _, key = parse_uri(blob.minio_uri)
        zip_names = zip_member_names(minio, key, blob.size_bytes)
    return resolve_type(head, name, zip_names)


def retype_waiting(session: Session, minio: Minio) -> dict[str, int]:
    """Re-resolve the route of documents still WAITING_FOR_ROUTE (nothing derived exists yet), e.g. after a
    type-resolution fix. Returns ``{"old->new": count}``."""
    changes: dict[str, int] = {}
    rows = session.execute(
        select(Document, Blob, DriveItem.name)
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .join(Blob, Blob.sha256 == DocumentSource.blob_sha256)
        .join(DriveItem, DriveItem.blob_sha256 == Blob.sha256)
        .where(
            DocumentSource.role == DocumentSourceRole.PRIMARY,
            Document.status == DocumentStatus.WAITING_FOR_ROUTE,
        )
    ).all()
    seen: set = set()
    for document, blob, name in rows:
        if document.doc_id in seen:
            continue  # one row per document (several locations may hold its blob)
        seen.add(document.doc_id)
        resolved = _resolve(minio, blob, name, _read(minio, blob, HEAD_BYTES))
        new_route = resolved.route.value if resolved.route else None
        if new_route != document.route:
            key = f"{document.route}->{new_route}"
            changes[key] = changes.get(key, 0) + 1
            document.route = new_route
            if new_route is None:
                document.status = DocumentStatus.WAITING_FOR_ROUTE  # unsupported now: left for an operator
    session.flush()
    return changes


def reset_waiting(session: Session, route: Route) -> int:
    """Remove documents of ``route`` that are still WAITING_FOR_ROUTE and carry only untouched (OPEN) flags,
    so the next dispatch assembles them again (after an assembler fix). Nothing derived exists for them."""
    removed = 0
    documents = session.scalars(
        select(Document).where(
            Document.route == route.value, Document.status == DocumentStatus.WAITING_FOR_ROUTE
        )
    ).all()
    for document in documents:
        flags = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == document.doc_id)).all()
        if any(flag.status != "OPEN" for flag in flags):
            continue  # a human has acted on it: keep
        for flag in flags:
            session.delete(flag)
        for source in session.scalars(select(DocumentSource).where(DocumentSource.doc_id == document.doc_id)):
            session.delete(source)
        session.delete(document)
        removed += 1
    session.flush()
    return removed


def folder_tree(session: Session) -> tuple[dict[str, DriveFolder], dict[str, list[str]]]:
    folders = {
        f.item_id: f for f in session.scalars(select(DriveFolder).where(DriveFolder.deleted_at.is_(None)))
    }
    ancestors: dict[str, list[str]] = {}

    def chain(folder_id: str | None) -> list[str]:
        if folder_id is None or folder_id not in folders:
            return []
        if folder_id not in ancestors:
            ancestors[folder_id] = [folder_id, *chain(folders[folder_id].parent_item_id)]
        return ancestors[folder_id]

    for folder_id in folders:
        chain(folder_id)
    return folders, ancestors


def group_key(scope: Sequence[str], root_name: str, folder_chain: Sequence[str]) -> str:
    for folder_id in folder_chain:
        if folder_id in scope:
            return folder_id
    return f"root:{root_name}"


def _context(
    candidate: Candidate, roots: dict[str, SyncRoot], folders: dict[str, DriveFolder], siblings
) -> FolderContext:
    item = candidate.item
    root = roots[item.root_name]
    folder = folders.get(item.parent_item_id or "")
    override = (
        SourceOrigin(folder.source_origin_override) if folder and folder.source_origin_override else None
    )
    return build_folder_context(
        item.root_name,
        candidate.folder_names,
        item.name,
        siblings,
        root_origin=SourceOrigin(root.default_source_origin),
        folder_origin_override=override,
    )


def _conflict_flag(message: str, subject: str) -> Flag:
    digest = hashlib.sha256(message.encode()).hexdigest()[:16]
    return Flag(
        flag_type=FlagType.CONFLICT,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(content_sha256=digest),
        evidence=ConflictEvidence(
            subject=subject,
            relation="note",
            a=ConflictSide(label="assembler", value=message, provenance="file 03 §1.3"),
        ),
    )


def _write_plan(
    session: Session,
    plan: DocumentPlan,
    by_blob: dict[str, Candidate],
    context: FolderContext,
    gate: RouteGate,
    cir: BucketStore,
    head: bytes,
    result: DispatchResult,
) -> None:
    primary = by_blob[plan.primary.blob_sha256]
    _new_document(
        session,
        NewDocument(
            sha=plan.primary.blob_sha256,
            title=plan.title,
            name=primary.item.name,
            extension=primary.item.extension,
            size_bytes=primary.item.size_bytes,
            resolved=primary.resolved,
            parts=plan.parts,
            conflicts=[*plan.conflicts, *context.conflicts],
            metadata={
                "assembler": {
                    key: value
                    for key, value in (("missing_includes", plan.missing_includes), ("notes", plan.notes))
                    if value
                }
            }
            if plan.missing_includes or plan.notes
            else {},
        ),
        context,
        gate,
        cir,
        head,
        result,
    )


@dataclass
class NewDocument:
    sha: str
    title: str
    name: str
    extension: str | None
    size_bytes: int | None
    resolved: ResolvedType
    parts: Sequence = ()
    conflicts: Sequence[str] = ()
    metadata: dict = field(default_factory=dict)


def _new_document(
    session: Session,
    new: NewDocument,
    context: FolderContext,
    gate: RouteGate,
    cir: BucketStore,
    head: bytes,
    result: DispatchResult,
) -> Document:
    """One document for one primary blob: PROCESSING when its route is on, its kind is not held and an
    adapter accepts the file, WAITING_FOR_ROUTE otherwise, HALTED with UNSUPPORTED_FORMAT when no route
    takes the type."""
    route = new.resolved.route
    adapter = adapter_for(route, head, new.name) if gate.runs(route, new.resolved.kind) else None
    if route is None:
        status = DocumentStatus.HALTED
    elif adapter is not None:
        status = DocumentStatus.PROCESSING
    else:
        status = DocumentStatus.WAITING_FOR_ROUTE
    sha = new.sha
    document = Document(
        route=route,
        title=new.title,
        status=status,
        source_origin=context.source_origin,
        trust_tier=context.trust_tier,
        test_plan_id=context.test_plan_id,
        test_run_id=context.test_run_id,
        hardware_item=context.hardware_item,
        doc_date=context.doc_date,
        date_source="path" if context.doc_date else None,
        folder_context=context.model_dump(mode="json"),
        metadata_sources=new.metadata,
    )
    if status == DocumentStatus.HALTED:
        flag = Flag(
            flag_type=FlagType.UNSUPPORTED_FORMAT,
            severity=FlagSeverity.HARD,
            evidence=ParseFailureEvidence(
                error=f"no adapter for {new.resolved.mime}",
                magic_bytes_hex=head[:16].hex(),
                size_bytes=new.size_bytes,
                detected_mime=new.resolved.mime,
                extension=new.extension,
                first_kb_preview=head[:1024].decode("utf-8", errors="replace"),
            ),
        )
        staged = {"blob_sha256": sha, "route": None, "flags": [flag.model_dump(mode="json")]}
        document.staged_payload_uri = cir.put(
            f"{sha}/staged.json", json.dumps(staged).encode(), "application/json"
        )
    session.add(document)
    session.flush()
    session.add(DocumentSource(doc_id=document.doc_id, blob_sha256=sha, role=DocumentSourceRole.PRIMARY))
    for part, role in new.parts:
        session.add(DocumentSource(doc_id=document.doc_id, blob_sha256=part.blob_sha256, role=role))
    if status == DocumentStatus.HALTED:
        upsert_document_flag(session, document.doc_id, flag)
        result.halted += 1
    elif status == DocumentStatus.WAITING_FOR_ROUTE:
        result.waiting += 1
    else:
        result.to_process.append(_release(document.doc_id, adapter))
    for message in new.conflicts:
        upsert_document_flag(session, document.doc_id, _conflict_flag(message, new.title), route)
        result.conflicts += 1
    result.created += 1
    key = route.value if route else "none"
    result.by_route[key] = result.by_route.get(key, 0) + 1
    return document


GONE = (DocumentStatus.SUPERSEDED, DocumentStatus.DELETED, DocumentStatus.QUARANTINED)


def dispatch_derived(
    session: Session, minio: Minio, gate: RouteGate, cir: BucketStore, result: DispatchResult
) -> None:
    """Documents for derived blobs (``blob_derivations``) whose parent is the primary blob of a live
    document: the child keeps the parent's folder context with the parent's title added to the breadcrumb;
    ``metadata_sources.derived_from`` names the parent document and the member path."""
    claimed = select(DocumentSource.blob_sha256)
    rows = session.execute(
        select(BlobDerivation, Document)
        .join(DocumentSource, DocumentSource.blob_sha256 == BlobDerivation.parent_blob_sha256)
        .join(Document, Document.doc_id == DocumentSource.doc_id)
        .where(
            DocumentSource.role == DocumentSourceRole.PRIMARY,
            BlobDerivation.child_blob_sha256.is_not(None),
            BlobDerivation.child_blob_sha256.not_in(claimed),
            Document.status.not_in(GONE),
        )
        .order_by(BlobDerivation.parent_blob_sha256, BlobDerivation.member_path)
    ).all()
    seen: set[str] = set()
    for link, parent in rows:
        sha = link.child_blob_sha256
        if sha in seen:
            continue  # the same content inside two parents: one document, first parent wins
        seen.add(sha)
        blob = session.get(Blob, sha)
        head = _read(minio, blob, HEAD_BYTES)
        name = PurePosixPath(link.member_path).name
        context = FolderContext.model_validate(parent.folder_context or {})
        context = context.model_copy(
            update={
                "breadcrumb": [*context.breadcrumb, parent.title or ""],
                "path_cached": f"{context.path_cached}/{link.member_path}",
                "conflicts": [],  # the parent's conflicts stay on the parent
            }
        )
        _new_document(
            session,
            NewDocument(
                sha=sha,
                title=PurePosixPath(name).stem,
                name=name,
                extension=PurePosixPath(name).suffix.casefold() or None,
                size_bytes=blob.size_bytes,
                resolved=_resolve(minio, blob, name, head),
                metadata={
                    "derived_from": {
                        "doc_id": str(parent.doc_id),
                        "member_path": link.member_path,
                        "kind": link.kind,
                    }
                },
            ),
            context,
            gate,
            cir,
            head,
            result,
        )
    session.flush()


def _release(doc_id: uuid.UUID, adapter: Adapter) -> Release:
    return Release(doc_id=doc_id, task=adapter.task, queue=str(adapter.queue))


def release_waiting(session: Session, minio: Minio, gate: RouteGate, result: DispatchResult) -> None:
    """Parked documents (WAITING_FOR_ROUTE) whose route is now enabled, whose kind is not held and that have
    an adapter for their primary file become PROCESSING (file 06 §3: re-dispatched automatically when the
    registry gains one). Documents a route already processed (waiting only for their commit path) stay
    parked."""
    rows = session.execute(
        select(Document, Blob, DriveItem.name)
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .join(Blob, Blob.sha256 == DocumentSource.blob_sha256)
        .join(DriveItem, DriveItem.blob_sha256 == Blob.sha256)
        .where(
            DocumentSource.role == DocumentSourceRole.PRIMARY,
            Document.status == DocumentStatus.WAITING_FOR_ROUTE,
            Document.route.in_([r.value for r in gate.on]),
            DriveItem.status.not_in(DEAD_LOCATION),
        )
        .order_by(DriveItem.path_cached)
    ).all()
    seen: set[uuid.UUID] = set()
    for document, blob, name in rows:
        if document.doc_id in seen or PROCESSED_MARK in (document.metadata_sources or {}):
            continue
        seen.add(document.doc_id)
        head = _read(minio, blob, HEAD_BYTES)
        if gate.held_kinds and _resolve(minio, blob, name, head).kind in gate.held_kinds:
            continue
        adapter = adapter_for(Route(document.route), head, name)
        if adapter is None:
            continue
        document.status = DocumentStatus.PROCESSING
        result.to_process.append(_release(document.doc_id, adapter))
        result.released += 1
    session.flush()


Enqueue = Callable[[Release], None]


def dispatch(
    session: Session,
    minio: Minio,
    section_file_sets: Sequence[Sequence[str]] | None = None,
    enqueue: Enqueue | None = None,
) -> DispatchResult:
    """Create documents for new content, release parked ones, and hand every PROCESSING document to
    ``enqueue`` after its transaction committed (a worker never sees an uncommitted document)."""
    result = DispatchResult()
    scope = pipeline_config.processing_scope(session)
    gate = route_gate(session)
    sets = load_section_file_sets() if section_file_sets is None else section_file_sets
    roots = {r.root_name: r for r in session.scalars(select(SyncRoot))}
    folders, ancestors = folder_tree(session)
    claimed = set(session.scalars(select(DocumentSource.blob_sha256)))
    cir = BucketStore(minio, CIR)

    items = session.scalars(
        select(DriveItem)
        .join(Blob, Blob.sha256 == DriveItem.blob_sha256)
        .where(
            DriveItem.status == DriveItemStatus.LANDED,
            DriveItem.detected_mime.is_not(None),
            Blob.restricted.is_(False),
        )
        .order_by(DriveItem.path_cached)
    ).all()
    groups: dict[str, dict[str, Candidate]] = defaultdict(dict)
    heads: dict[str, bytes] = {}
    collected: set[str] = set()
    for item in items:
        chain = ancestors.get(item.parent_item_id or "", [])
        if not item.path_cached or not in_scope(scope, item.root_name, chain, item.path_cached):
            continue
        if item.blob_sha256 in claimed:
            result.skipped_existing += 1
            continue
        if item.blob_sha256 in collected:
            continue  # another copy of the same content (any subtree): one document, first path wins
        collected.add(item.blob_sha256)
        group = groups[group_key(scope, item.root_name, chain)]
        blob = session.get(Blob, item.blob_sha256)
        heads[item.blob_sha256] = _read(minio, blob, HEAD_BYTES)
        folder_names = item.path_cached.split("/")[:-1]
        group[item.blob_sha256] = Candidate(
            item, folder_names, _resolve(minio, blob, item.name, heads[item.blob_sha256])
        )

    for key, by_blob in groups.items():
        base = folders[key].path_cached if key in folders and folders[key].path_cached else ""
        refs = []
        for sha, candidate in by_blob.items():
            relative = candidate.item.path_cached[len(base) + 1 :] if base else candidate.item.path_cached
            refs.append(FileRef(path=relative, blob_sha256=sha, kind=candidate.resolved.kind))

        def read_text(ref: FileRef, _by_blob=by_blob) -> str:
            return _read(minio, session.get(Blob, ref.blob_sha256)).decode("utf-8", errors="replace")

        siblings_by_folder: dict[str | None, list[Sibling]] = defaultdict(list)
        for candidate in by_blob.values():
            siblings_by_folder[candidate.item.parent_item_id].append(
                Sibling(
                    name=candidate.item.name,
                    extension=candidate.item.extension,
                    size_bytes=candidate.item.size_bytes,
                )
            )
        for plan in assemble(refs, read_text, sets):
            primary = by_blob[plan.primary.blob_sha256]
            context = _context(primary, roots, folders, siblings_by_folder[primary.item.parent_item_id])
            _write_plan(session, plan, by_blob, context, gate, cir, heads[plan.primary.blob_sha256], result)
        session.commit()
    result.superseded = replace_older(session)
    dispatch_derived(session, minio, gate, cir, result)
    release_waiting(session, minio, gate, result)
    session.commit()
    if enqueue is not None:
        for release in result.to_process:
            enqueue(release)
    return result


# ---------------------------------------------------------------- supersession (file 02 §5.1)

DEAD_LOCATION = (DriveItemStatus.DELETED,)
SETTLED = (DocumentStatus.SUPERSEDED, DocumentStatus.DELETED)


def _set_status(document: Document, status: DocumentStatus, primary_blob: str) -> None:
    """``staged_payload_uri`` is set exactly while HALTED (CHECK). The staged JSON stays at its key
    ``dcl-cir/{sha256}/staged.json``, so a document returning to HALTED points at it again."""
    document.status = status
    document.staged_payload_uri = (
        uri(CIR, f"{primary_blob}/staged.json") if status == DocumentStatus.HALTED else None
    )


def _primary_document(session: Session, blob_sha256: str) -> Document | None:
    return session.scalar(
        select(Document)
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .where(DocumentSource.blob_sha256 == blob_sha256, DocumentSource.role == DocumentSourceRole.PRIMARY)
    )


def _held_by_a_live_location(session: Session, blob_sha256: str) -> bool:
    found = session.scalar(
        select(DriveItem.location_id)
        .where(DriveItem.blob_sha256 == blob_sha256, DriveItem.status.not_in(DEAD_LOCATION))
        .limit(1)
    )
    return found is not None


LIVE = (DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS)
OPEN_FLAGS = ("OPEN", "IN_PROGRESS", "REOPENED")


def replace_older(session: Session, blob_sha256: str | None = None) -> int:
    """For each location whose content was replaced in place, once the new content's document is searchable:
    SUPERSEDES new→old, and the old document becomes SUPERSEDED (out of search at once) with
    ``metadata_sources.replaced_by``, so ``dispatcher/versions.py purge_replaced`` removes it. Until then the
    old version stays searchable: search never goes blank while the new one is processed or reviewed
    (until 2026-10-27 the old one was superseded at dispatch). It runs at dispatch and when a document is
    committed (``blob_sha256``: that document's new content). A location reverted to an earlier version
    that is not removed yet gets that version back."""
    query = select(DriveItem).where(DriveItem.previous_blob_sha256.is_not(None))
    if blob_sha256 is not None:
        query = query.where(DriveItem.blob_sha256 == blob_sha256)
    superseded = 0
    for item in session.scalars(query).all():
        new_doc = _primary_document(session, item.blob_sha256) if item.blob_sha256 else None
        if new_doc is not None and new_doc.status == DocumentStatus.SUPERSEDED:
            _bring_back(session, new_doc)
        if new_doc is None or new_doc.status not in LIVE:
            continue  # the new content is not searchable yet (dispatch, route, review): the old one stays
        old_doc = _primary_document(session, item.previous_blob_sha256)
        if old_doc is not None and old_doc.doc_id != new_doc.doc_id:
            if session.get(DocumentRelation, (new_doc.doc_id, old_doc.doc_id, "SUPERSEDES")) is None:
                session.add(
                    DocumentRelation(doc_id_a=new_doc.doc_id, doc_id_b=old_doc.doc_id, relation="SUPERSEDES")
                )
            if old_doc.status not in SETTLED and not _held_by_a_live_location(
                session, item.previous_blob_sha256
            ):
                _set_status(old_doc, DocumentStatus.SUPERSEDED, item.previous_blob_sha256)
                old_doc.metadata_sources = {
                    **(old_doc.metadata_sources or {}),
                    "replaced_by": str(new_doc.doc_id),
                }
                superseded += 1
        item.previous_blob_sha256 = None
    session.flush()
    return superseded


def _bring_back(session: Session, document: Document) -> None:
    """A location reverted to this version before its removal: it is searchable again and replaces the
    version that replaced it (a removed one is gone: its bytes come back as new content instead)."""
    if (document.metadata_sources or {}).get("purged_at"):
        return
    open_flags = session.scalar(
        select(ReviewFlag.flag_id).where(
            ReviewFlag.doc_id == document.doc_id, ReviewFlag.status.in_(OPEN_FLAGS)
        )
    )
    document.status = DocumentStatus.ACTIVE_WITH_SOFT_FLAGS if open_flags else DocumentStatus.ACTIVE
    document.metadata_sources = {
        k: v for k, v in (document.metadata_sources or {}).items() if k != "replaced_by"
    }
    for relation in session.scalars(
        select(DocumentRelation).where(
            DocumentRelation.doc_id_b == document.doc_id, DocumentRelation.relation == "SUPERSEDES"
        )
    ):
        session.delete(relation)


def sweep_documents(session: Session) -> dict[str, int]:
    """Safety net: documents whose primary blob no live location holds are settled (SUPERSEDED when a
    newer document supersedes them, else DELETED); documents held only by quarantined locations are
    QUARANTINED, and come back when a location leaves quarantine (file 02 §7 document state machine)."""
    counts = {"superseded": 0, "deleted": 0, "quarantined": 0, "reactivated": 0}
    rows = session.execute(
        select(Document, DocumentSource.blob_sha256)
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .where(DocumentSource.role == DocumentSourceRole.PRIMARY, Document.status != DocumentStatus.DELETED)
    ).all()
    awaiting = set(  # an old version stays live until its replacement is searchable (replace_older)
        session.scalars(
            select(DriveItem.previous_blob_sha256).where(DriveItem.previous_blob_sha256.is_not(None))
        )
    )
    for document, blob_sha256 in rows:
        if blob_sha256 in awaiting:
            continue
        holders = set(
            session.scalars(
                select(DriveItem.status).where(
                    DriveItem.blob_sha256 == blob_sha256, DriveItem.status.not_in(DEAD_LOCATION)
                )
            )
        )
        if not holders:
            targeted = session.scalar(
                select(DocumentRelation.doc_id_a)
                .where(
                    DocumentRelation.doc_id_b == document.doc_id, DocumentRelation.relation == "SUPERSEDES"
                )
                .limit(1)
            )
            target = DocumentStatus.SUPERSEDED if targeted is not None else DocumentStatus.DELETED
            if document.status != target:
                _set_status(document, target, blob_sha256)
                counts["superseded" if target == DocumentStatus.SUPERSEDED else "deleted"] += 1
        elif holders == {DriveItemStatus.QUARANTINED}:
            if document.status != DocumentStatus.QUARANTINED:
                _set_status(document, DocumentStatus.QUARANTINED, blob_sha256)
                counts["quarantined"] += 1
        elif document.status == DocumentStatus.QUARANTINED:
            _set_status(
                document,
                DocumentStatus.WAITING_FOR_ROUTE if document.route else DocumentStatus.HALTED,
                blob_sha256,
            )
            counts["reactivated"] += 1
    session.flush()
    return counts


def main(argv: list[str]) -> int:
    import argparse
    import os
    from pathlib import Path

    from sqlalchemy import create_engine

    from backend.config import get_settings, load_settings
    from backend.postgres.session import normalize_url
    from backend.storage.minio import client_from_settings

    parser = argparse.ArgumentParser(prog="python -m backend.dispatcher.routing")
    parser.add_argument("command", choices=["dispatch", "sweep", "retype", "reassemble"])
    parser.add_argument(
        "--route", default="A2", help="reassemble: the route whose waiting documents are rebuilt"
    )
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    settings = load_settings(Path(args.env_file)) if args.env_file else get_settings()
    engine = create_engine(
        normalize_url(os.environ.get("DCL_DATABASE_URL") or settings.stack_database_url().get_secret_value())
    )
    with Session(engine, expire_on_commit=False) as session:
        if args.command == "sweep":
            print(sweep_documents(session))
            session.commit()
            return 0
        if args.command == "reassemble":
            removed = reset_waiting(session, Route(args.route))
            session.commit()
            print(f"removed {removed} waiting {args.route} documents; dispatching again")
            args.command = "dispatch"
        if args.command == "retype":
            print(retype_waiting(session, client_from_settings(settings)))
            session.commit()
            return 0
        result = dispatch(session, client_from_settings(settings))
    print(
        f"created {result.created} documents ({result.waiting} WAITING_FOR_ROUTE, {result.halted} HALTED), "
        f"{result.conflicts} CONFLICT flags, {result.skipped_existing} items already in documents"
    )
    print(f"  by route: {dict(sorted(result.by_route.items()))}; superseded: {result.superseded}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))


REPROCESSABLE = (DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS)


def redispatch_candidates(session: Session, route: Route, statuses=REPROCESSABLE) -> list[Document]:
    """The documents "re-process affected documents" would run again (file 08 §3.2 Routes)."""
    return list(
        session.scalars(
            select(Document)
            .where(Document.route == route.value, Document.status.in_([str(s) for s in statuses]))
            .order_by(Document.title)
        )
    )


def redispatch(session: Session, route: Route, statuses=REPROCESSABLE) -> list[Release]:
    """Set those documents PROCESSING and return the releases; the caller commits, then enqueues."""
    from backend.dispatcher.adapters import task_for_route

    found = task_for_route(route)
    if found is None:
        return []
    task, queue = found
    releases = []
    for document in redispatch_candidates(session, route, statuses):
        document.status = DocumentStatus.PROCESSING
        document.staged_payload_uri = None
        releases.append(Release(doc_id=document.doc_id, task=task, queue=str(queue)))
    session.flush()
    return releases
