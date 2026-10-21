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
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from backend.postgres.models import Blob, Document, DocumentSource, DriveFolder, DriveItem, SyncRoot
from backend.review.flags import upsert_document_flag
from backend.storage.minio import CIR, BucketStore, parse_uri
from backend.sync.scope import in_scope

IMPLEMENTED_ROUTES: frozenset[Route] = frozenset()  # grows as route adapters land (Route C next)


@dataclass
class DispatchResult:
    created: int = 0
    waiting: int = 0
    halted: int = 0
    skipped_existing: int = 0
    conflicts: int = 0
    by_route: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    item: DriveItem
    folder_names: list[str]
    resolved: ResolvedType


def enabled_routes(session: Session) -> set[Route]:
    return {r for r in Route if pipeline_config.get(session, f"routes.{r}.enabled", default=False) is True}


def _read(minio: Minio, blob: Blob, length: int | None = None) -> bytes:
    bucket, key = parse_uri(blob.minio_uri)
    response = minio.get_object(bucket, key, offset=0, length=length or blob.size_bytes)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _folder_tree(session: Session) -> tuple[dict[str, DriveFolder], dict[str, list[str]]]:
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


def _group_key(scope: Sequence[str], root_name: str, folder_chain: Sequence[str]) -> str:
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
            a=ConflictSide(label="assembler", value=message, provenance="dispatcher"),
            b=ConflictSide(label="expected", value="one unambiguous document", provenance="file 03 §1.3"),
        ),
    )


def _write_plan(
    session: Session,
    plan: DocumentPlan,
    by_blob: dict[str, Candidate],
    context: FolderContext,
    routes_on: set[Route],
    cir: BucketStore,
    head: bytes,
    result: DispatchResult,
) -> None:
    primary = by_blob[plan.primary.blob_sha256]
    route = primary.resolved.route
    if route is None:
        status = DocumentStatus.HALTED
    elif route in routes_on and route in IMPLEMENTED_ROUTES:
        status = DocumentStatus.PROCESSING
    else:
        status = DocumentStatus.WAITING_FOR_ROUTE
    sha = plan.primary.blob_sha256
    document = Document(
        route=route,
        title=plan.title,
        status=status,
        source_origin=context.source_origin,
        trust_tier=context.trust_tier,
        test_plan_id=context.test_plan_id,
        test_run_id=context.test_run_id,
        hardware_item=context.hardware_item,
        folder_context=context.model_dump(mode="json"),
        metadata_sources={"assembler": {"missing_includes": plan.missing_includes}}
        if plan.missing_includes
        else {},
    )
    if status == DocumentStatus.HALTED:
        flag = Flag(
            flag_type=FlagType.UNSUPPORTED_FORMAT,
            severity=FlagSeverity.HARD,
            evidence=ParseFailureEvidence(
                error=f"no adapter for {primary.resolved.mime}",
                magic_bytes_hex=head[:16].hex(),
                size_bytes=primary.item.size_bytes,
                detected_mime=primary.resolved.mime,
                extension=primary.item.extension,
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
    for part, role in plan.parts:
        session.add(DocumentSource(doc_id=document.doc_id, blob_sha256=part.blob_sha256, role=role))
    if status == DocumentStatus.HALTED:
        upsert_document_flag(session, document.doc_id, flag)
        result.halted += 1
    elif status == DocumentStatus.WAITING_FOR_ROUTE:
        result.waiting += 1
    for message in [*plan.conflicts, *context.conflicts]:
        upsert_document_flag(session, document.doc_id, _conflict_flag(message, plan.title), route)
        result.conflicts += 1
    result.created += 1
    key = route.value if route else "none"
    result.by_route[key] = result.by_route.get(key, 0) + 1


def dispatch(
    session: Session, minio: Minio, section_file_sets: Sequence[Sequence[str]] | None = None
) -> DispatchResult:
    result = DispatchResult()
    scope = pipeline_config.processing_scope(session)
    routes_on = enabled_routes(session)
    sets = load_section_file_sets() if section_file_sets is None else section_file_sets
    roots = {r.root_name: r for r in session.scalars(select(SyncRoot))}
    folders, ancestors = _folder_tree(session)
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
        group = groups[_group_key(scope, item.root_name, chain)]
        blob = session.get(Blob, item.blob_sha256)
        heads[item.blob_sha256] = _read(minio, blob, HEAD_BYTES)
        folder_names = item.path_cached.split("/")[:-1]
        group[item.blob_sha256] = Candidate(
            item, folder_names, resolve_type(heads[item.blob_sha256], item.name)
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
            _write_plan(
                session, plan, by_blob, context, routes_on, cir, heads[plan.primary.blob_sha256], result
            )
        session.commit()
    return result


def main(argv: list[str]) -> int:
    import argparse
    import os
    from pathlib import Path

    from sqlalchemy import create_engine

    from backend.config import get_settings, load_settings
    from backend.postgres.session import normalize_url
    from backend.storage.minio import client_from_settings

    parser = argparse.ArgumentParser(prog="python -m backend.dispatcher.routing")
    parser.add_argument("command", choices=["dispatch"])
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    settings = load_settings(Path(args.env_file)) if args.env_file else get_settings()
    engine = create_engine(
        normalize_url(os.environ.get("DCL_DATABASE_URL") or settings.stack_database_url().get_secret_value())
    )
    with Session(engine, expire_on_commit=False) as session:
        result = dispatch(session, client_from_settings(settings))
    print(
        f"created {result.created} documents ({result.waiting} WAITING_FOR_ROUTE, {result.halted} HALTED), "
        f"{result.conflicts} CONFLICT flags, {result.skipped_existing} items already in documents"
    )
    print(f"  by route: {dict(sorted(result.by_route.items()))}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
