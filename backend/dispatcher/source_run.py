"""Routes A2, B, E and G on the shared runner. A2: S6's LaTeX and report JSON (``backend.routes.a2_source``).

The files of the document are its ``document_sources`` (primary, parts, visual twin) with paths relative
to the processing subtree the assembler grouped them in (``routing.group_key``), so includes resolve as
planned. ``folder_files`` lists that subtree's landed files; ``read_file`` fetches a sibling by that path
(images, ``.bib``, ``.sty``). The assembler's conflicts are already flags on the document (the dispatcher
raised them), so none are passed again.
"""

import uuid
from pathlib import PurePosixPath

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.location import Location, primary_location
from backend.dispatcher.routing import folder_tree, group_key
from backend.dispatcher.runner import Outcome, RunContext, read_object, run_document, vision_for
from backend.indexing.commit import Indexer
from backend.postgres import pipeline_config
from backend.postgres.enums import DocumentSourceRole, DriveItemStatus, Route
from backend.postgres.models import Blob, DocumentSource, DriveItem

MAX_FOLDER_FILES = 5000


def subtree_base(session: Session, where: Location) -> str:
    """The path the assembler made the document's file paths relative to ('' = the root group)."""
    folders, chains = folder_tree(session)
    key = group_key(
        pipeline_config.processing_scope(session), where.root_name, chains.get(where.parent_item_id or "", [])
    )
    folder = folders.get(key)
    return folder.path_cached if folder is not None and folder.path_cached else ""


def _relative(path: str, base: str) -> str:
    return path[len(base) + 1 :] if base and path.startswith(base + "/") else path


def process_a2_document(
    session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer | None = None
) -> Outcome:
    from backend.routes.a2_source import route as a2

    def build(ctx: RunContext):
        base = subtree_base(ctx.session, ctx.where)
        rows = ctx.session.execute(
            select(DocumentSource.blob_sha256, DocumentSource.role, Blob.minio_uri)
            .join(Blob, Blob.sha256 == DocumentSource.blob_sha256)
            .where(DocumentSource.doc_id == ctx.document.doc_id)
        ).all()
        files = []
        for sha, role, minio_uri in rows:
            where = primary_location(ctx.session, sha)
            path = _relative(where.path_cached or where.name, base) if where else sha
            files.append(
                a2.SourceFile(
                    path=path,
                    blob_sha256=sha,
                    data=read_object(ctx.minio, minio_uri),
                    role=DocumentSourceRole(role),
                )
            )
        listing_base = base or str(PurePosixPath(ctx.where.path_cached or ctx.where.name).parent)
        landed = ctx.session.execute(
            select(DriveItem.path_cached, Blob.minio_uri)
            .join(Blob, Blob.sha256 == DriveItem.blob_sha256)
            .where(
                DriveItem.status == DriveItemStatus.LANDED,
                DriveItem.path_cached.startswith(listing_base + "/"),
            )
            .order_by(DriveItem.path_cached)
            .limit(MAX_FOLDER_FILES)
        ).all()
        by_path = {_relative(path, base): minio_uri for path, minio_uri in landed}

        def read_file(path: str) -> bytes | None:
            minio_uri = by_path.get(path)
            return read_object(ctx.minio, minio_uri) if minio_uri else None

        stores = a2.Stores(put_cir=ctx.put_cir, put_asset=ctx.put_asset)
        primary = next(f for f in files if f.role == DocumentSourceRole.PRIMARY)
        if primary.path.casefold().endswith(".json"):
            return a2.process_json(files, title=ctx.document.title, folder=ctx.folder, stores=stores)
        return a2.process_latex(
            files,
            title=ctx.document.title,
            folder=ctx.folder,
            stores=stores,
            folder_files=list(by_path),
            read_file=read_file,
            conflicts=(),
            vision=vision_for(ctx.session) if ctx.cloud_allowed else None,
            cloud_allowed=ctx.cloud_allowed,
            doc_id=str(ctx.document.doc_id),
        )

    return run_document(session, minio, doc_id, Route.A2, a2.PARSER_VERSION, build, indexer)


def process_b_document(
    session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer | None = None
) -> Outcome:
    """Route B (scripts, notebooks, tooling docs) through S6's ``process_code``; CIR under {sha}/B/v1/."""
    from backend.routes.b_code import route as b

    def build(ctx: RunContext):
        return b.process_code(
            ctx.data,
            blob_sha256=ctx.blob.sha256,
            file_name=ctx.where.name,
            folder=ctx.folder,
            stores=b.Stores(put_cir=ctx.put_cir),
        )

    return run_document(session, minio, doc_id, Route.B, b.PARSER_VERSION, build, indexer)


def process_e_document(
    session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer | None = None
) -> Outcome:
    """Route E (draw.io, XSD, SVG, VSDX, DXF) through S6's ``process_diagram``; CIR under {sha}/E/v1/."""
    from backend.routes.e_diagrams import route as e

    def build(ctx: RunContext):
        return e.process_diagram(
            ctx.data,
            blob_sha256=ctx.blob.sha256,
            file_name=ctx.where.name,
            folder=ctx.folder,
            stores=e.Stores(put_cir=ctx.put_cir, put_asset=ctx.put_asset),
            vision=vision_for(ctx.session) if ctx.cloud_allowed else None,
            cloud_allowed=ctx.cloud_allowed,
            doc_id=str(ctx.document.doc_id),
        )

    return run_document(session, minio, doc_id, Route.E, e.PARSER_VERSION, build, indexer)


COMMITTED = ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS")


def _subtree_listing(ctx: RunContext, base: str) -> list[str]:
    listing_base = base or str(PurePosixPath(ctx.where.path_cached or ctx.where.name).parent)
    return [
        _relative(path, base)
        for path in ctx.session.scalars(
            select(DriveItem.path_cached)
            .where(
                DriveItem.status == DriveItemStatus.LANDED,
                DriveItem.path_cached.startswith(listing_base + "/"),
            )
            .order_by(DriveItem.path_cached)
            .limit(MAX_FOLDER_FILES)
        )
    ]


def write_references(session: Session, document, base: str) -> int:
    """``document_relations(REFERENCES)`` from ``catalog.references`` (paths in the processing subtree) to
    the documents those files became; files without a document yet are skipped (a re-run adds them)."""
    from backend.postgres.models import Document, DocumentRelation

    written = 0
    for path in (document.catalog or {}).get("references") or []:
        full = f"{base}/{path}" if base else path
        other = session.scalar(
            select(Document)
            .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
            .join(DriveItem, DriveItem.blob_sha256 == DocumentSource.blob_sha256)
            .where(
                DriveItem.path_cached == full,
                DriveItem.status == DriveItemStatus.LANDED,
                DocumentSource.role == DocumentSourceRole.PRIMARY,
            )
            .limit(1)
        )
        if other is None or other.doc_id == document.doc_id:
            continue
        a, b = sorted([document.doc_id, other.doc_id], key=str)
        if session.get(DocumentRelation, (a, b, "REFERENCES")) is None:
            session.add(DocumentRelation(doc_id_a=a, doc_id_b=b, relation="REFERENCES"))
            written += 1
    session.flush()
    return written


def process_g_document(
    session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer | None = None
) -> Outcome:
    """Route G (archives, ANSYS packages, CAD) through S6's ``g.process``. Kept archive members come back
    as ``derived_blobs`` (the commit path registers them); CAD references become REFERENCES relations."""
    from backend.postgres.models import Document
    from backend.routes.g_archives import route as g

    bases: dict[str, str] = {}

    def build(ctx: RunContext):
        base = bases["base"] = subtree_base(ctx.session, ctx.where)
        return g.process(
            ctx.data,
            blob_sha256=ctx.blob.sha256,
            file_name=ctx.where.name,
            folder=ctx.folder,
            stores=g.Stores(put_cir=ctx.put_cir),
            path=_relative(ctx.where.path_cached or ctx.where.name, base),
            folder_files=_subtree_listing(ctx, base),
            web_url=ctx.where.web_url,
        )

    outcome = run_document(session, minio, doc_id, Route.G, g.PARSER_VERSION, build, indexer)
    if outcome.status in COMMITTED:
        write_references(session, session.get(Document, doc_id), bases.get("base", ""))
    return outcome
