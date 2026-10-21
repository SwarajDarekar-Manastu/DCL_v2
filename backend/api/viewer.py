"""Shared document viewer: deep-link contract and anchor resolution (file 08 §6, file 04 §4.4).

Deep link (chat citations, Review UI, Benchmark drilldowns):

    {CONSOLE_URL}/docs/{doc_id}/viewer?anchor=<kind>:<value>:<content_sha256>

    kind   value                         example
    page   page number, 1-based          page:12:9f86d081884c7d65
    line   first line, 1-based           line:120:ab12cd34ef56ab78
    t      milliseconds from the start   t:83500:
    cells  <sheet>!<A1 range>            cells:Run 1!A1:D20:0c1d2e3f4a5b6c7d

The hash part is lowercase hex (16 to 64 characters) or empty; the trailing colon is always written.
The anchor never carries a node id. The format is owned by `backend.dispatcher.contract`; build links
with `viewer_path(doc_id, anchor.locator_fields())`.

The Console page calls GET /docs/{doc_id}/viewer?anchor=…[&translate=true] and renders the returned
`ViewerPayload`. Resolution: same locator and same hash → `exact`; hash differs or is missing →
`page_fallback` (the page, line, time or sheet is shown and the UI says so); locator gone →
`document_only`.
"""

from collections.abc import Callable
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from minio import Minio
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.assets import get_minio
from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.dispatcher.contract import Anchor, AnchorError, format_anchor
from backend.indexing.anchors import ResolutionStatus, resolve_anchor
from backend.postgres.enums import AssetKind, DocumentSourceRole, DriveItemStatus
from backend.postgres.models import Asset, Document, DocumentNode, DocumentSource, DriveItem
from backend.postgres.session import get_session
from backend.storage.minio import RAW, presign_get, raw_key, uri

# ---------------------------------------------------------------- anchor parameter
# The format is owned by backend.dispatcher.contract (parse_anchor / format_anchor / Anchor).


def viewer_path(doc_id: UUID | str, fields: dict[str, Any]) -> str:
    """Path of the Console viewer for an anchor's locator fields; prefix it with the Console base URL."""
    return f"/docs/{doc_id}/viewer?anchor={quote(format_anchor(fields), safe=':!')}"


# ---------------------------------------------------------------- response models


class ViewerStatus(StrEnum):
    EXACT = "exact"
    PAGE_FALLBACK = "page_fallback"
    DOCUMENT_ONLY = "document_only"


class ViewerResolution(BaseModel):
    status: ViewerStatus
    message: str = ""  # shown to the reader when status is not exact


class Region(BaseModel):
    """A box on an image, normalized to 0..1 of the rendered image, origin top-left."""

    bbox: tuple[float, float, float, float] = Field(description="x0, y0, x1, y1 in 0..1")
    kind: Literal["cited", "handwriting", "flag"]
    label: str = ""
    confidence: float | None = None


class PageView(BaseModel):
    kind: Literal["page"] = "page"
    page_no: int
    page_count: int
    image_url: str  # presigned page render (15 min)
    width: int
    height: int
    regions: list[Region] = []
    text: str = ""  # OCR / extracted text of the page, for the text toggle


class ImageView(BaseModel):
    kind: Literal["image"] = "image"
    image_kind: Literal["photo", "plot", "diagram", "figure"]
    image_url: str
    width: int
    height: int
    regions: list[Region] = []
    caption: str = ""


class TableView(BaseModel):
    kind: Literal["table"] = "table"
    sheet_name: str | None = None
    header_rows: int = 1
    rows: list[list[str]]  # cell text, never HTML
    highlight: tuple[int, int, int, int] | None = None  # first row, first col, last row, last col (0-based)


class CodeView(BaseModel):
    kind: Literal["code"] = "code"
    language: str
    first_line: int = 1
    lines: list[str]
    highlight: tuple[int, int] | None = None  # first and last highlighted line numbers


class TextView(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    breadcrumb: str = ""


class VideoView(BaseModel):
    kind: Literal["video"] = "video"
    video_url: str
    t_ms: int = 0
    poster_url: str | None = None


ViewerView = Annotated[
    PageView | ImageView | TableView | CodeView | TextView | VideoView, Field(discriminator="kind")
]


class ViewerDocument(BaseModel):
    doc_id: UUID
    title: str
    doc_kind: str
    source_origin: Literal["internal", "external_kept"]
    trust_tier: int = Field(ge=1, le=6)
    language: str | None = None
    test_ids: list[str] = []
    doc_date: date | None = None
    status: str  # documents.status
    open_flags: int = 0


class OneDriveLocation(BaseModel):
    path: str
    web_url: str


class ViewerLinks(BaseModel):
    onedrive: list[OneDriveLocation] = []  # every location of the document (v_doc_locations)
    download_url: str | None = None  # presigned original (15 min)
    review_case_key: str | None = None  # open case on the cited page, if any


class ViewerTranslation(BaseModel):
    source_language: str | None = None
    available: bool = False  # content_en exists or on-the-fly translation is allowed
    translated_text: str | None = None  # only when translate=true was requested and the text exists
    pending: bool = False  # translation requested and being produced


class ViewerPayload(BaseModel):
    anchor: str  # normalized anchor parameter of the request ("" when none)
    document: ViewerDocument
    resolution: ViewerResolution
    view: ViewerView
    links: ViewerLinks
    translation: ViewerTranslation


# ---------------------------------------------------------------- payload from the database

PresignFn = Callable[[str], str]
CODE_NODES = {"code_symbol", "module_header", "config"}
TIME_NODES = {"transcript_window", "video_event"}
RESOLUTION_MESSAGE = {
    ResolutionStatus.EXACT: "",
    ResolutionStatus.PAGE_FALLBACK: "The cited passage changed after re-indexing; showing where it was.",
    ResolutionStatus.DOCUMENT_ONLY: "The cited location is no longer in this document; showing its start.",
}


class DocumentNotFound(LookupError):
    pass


def _primary_blob(session: Session, doc_id: UUID) -> str | None:
    return session.scalar(
        select(DocumentSource.blob_sha256).where(
            DocumentSource.doc_id == doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY
        )
    )


def _locations(session: Session, blob_sha256: str | None) -> list[OneDriveLocation]:
    if not blob_sha256:
        return []
    rows = session.execute(
        select(DriveItem.path_cached, DriveItem.name, DriveItem.web_url)
        .where(DriveItem.blob_sha256 == blob_sha256, DriveItem.status != DriveItemStatus.DELETED)
        .order_by(DriveItem.path_cached)
    )
    return [OneDriveLocation(path=path or name, web_url=url) for path, name, url in rows if url]


def _nodes(session: Session, node_ids: list[UUID]) -> list[DocumentNode]:
    if not node_ids:
        return []
    rows = session.scalars(select(DocumentNode).where(DocumentNode.node_id.in_(node_ids)))
    return sorted(rows, key=lambda n: n.ordinal)


def _first_nodes(session: Session, doc_id: UUID, limit: int = 3) -> list[DocumentNode]:
    stmt = select(DocumentNode).where(DocumentNode.doc_id == doc_id).order_by(DocumentNode.ordinal)
    return list(session.scalars(stmt.limit(limit)))


def _page_render(session: Session, blob_sha256: str | None, page_no: int) -> Asset | None:
    if not blob_sha256:
        return None
    return session.scalar(
        select(Asset).where(
            Asset.blob_sha256 == blob_sha256, Asset.kind == AssetKind.PAGE_RENDER, Asset.page_no == page_no
        )
    )


def _view(
    session: Session,
    doc: Document,
    blob_sha256: str | None,
    page_no: int | None,
    nodes: list[DocumentNode],
    boxes: list[Region],
    anchor: Anchor | None,
    presign: PresignFn,
) -> PageView | ImageView | CodeView | TextView | VideoView:
    render = _page_render(session, blob_sha256, page_no or 1)
    if render and render.width and render.height:
        page_text = "\n\n".join(n.content for n in nodes)
        return PageView(
            page_no=page_no or 1,
            page_count=doc.page_count or page_no or 1,
            image_url=presign(render.minio_uri),
            width=render.width,
            height=render.height,
            regions=boxes,
            text=page_text,
        )
    first = nodes[0] if nodes else None
    if first and first.node_type in CODE_NODES:
        lines = first.content.splitlines() or [""]
        start = first.line_start or 1
        wanted = anchor.line_start if anchor and anchor.line_start else None
        highlight = (wanted, wanted) if wanted else (start, first.line_end or start + len(lines) - 1)
        return CodeView(language=doc.language or "text", first_line=start, lines=lines, highlight=highlight)
    if first and first.node_type == "photo" and first.asset_id:
        asset = session.get(Asset, first.asset_id)
        if asset and asset.width and asset.height:
            return ImageView(
                image_kind="photo",
                image_url=presign(asset.minio_uri),
                width=asset.width,
                height=asset.height,
                caption=first.breadcrumb or "",
            )
    if first and first.node_type in TIME_NODES and blob_sha256:
        start_ms = anchor.t_start_ms if anchor and anchor.t_start_ms is not None else first.t_start_ms or 0
        return VideoView(video_url=presign(uri(RAW, raw_key(blob_sha256))), t_ms=start_ms)
    return TextView(
        text="\n\n".join(n.content for n in nodes) or "This document has no indexed content yet.",
        breadcrumb=first.breadcrumb or "" if first else "",
    )


def build_viewer_payload(
    session: Session, doc_id: UUID, anchor_text: str, translate: bool, presign: PresignFn
) -> ViewerPayload:
    """Resolve the anchor to the current nodes (page + hash, falling back to the page) and shape the view."""
    anchor = Anchor.parse(doc_id, anchor_text) if anchor_text else None  # validate input before reading
    doc = session.get(Document, doc_id)
    if doc is None:
        raise DocumentNotFound(str(doc_id))
    blob = _primary_blob(session, doc_id)

    status, page_no, nodes, boxes = ResolutionStatus.EXACT, None, [], []
    if anchor is not None:
        resolution = resolve_anchor(session, anchor)
        status, page_no = resolution.status, resolution.page_no
        nodes = _nodes(session, [m.node_id for m in resolution.matches])
        # already filtered to the resolved page by resolve_anchor (exact matches only)
        boxes = [Region(bbox=(b.x0, b.y0, b.x1, b.y1), kind="cited") for b in resolution.boxes]
    if not nodes:  # no anchor, or the anchor's location is gone: open the start of the document
        nodes = _first_nodes(session, doc_id)
    page_no = page_no or (nodes[0].page_no if nodes else None)

    translated = [n.content_en for n in nodes if n.content_en]
    source_language = doc.language or (nodes[0].language if nodes else None)
    return ViewerPayload(
        anchor=format_anchor(anchor.locator_fields()) if anchor else "",
        document=ViewerDocument(
            doc_id=doc.doc_id,
            title=doc.title or "Untitled document",
            doc_kind=doc.doc_kind,
            source_origin=doc.source_origin,
            trust_tier=doc.trust_tier or 2,
            language=doc.language,
            test_ids=[t for t in (doc.test_plan_id, doc.test_run_id) if t],
            doc_date=doc.doc_date,
            status=doc.status,
        ),
        resolution=ViewerResolution(status=ViewerStatus(status.value), message=RESOLUTION_MESSAGE[status]),
        view=_view(session, doc, blob, page_no, nodes, boxes, anchor, presign),
        links=ViewerLinks(
            onedrive=_locations(session, blob),
            download_url=presign(uri(RAW, raw_key(blob))) if blob else None,
        ),
        translation=ViewerTranslation(
            source_language=source_language,
            available=bool(translated),
            translated_text="\n\n".join(translated) if translate and translated else None,
        ),
    )


# ---------------------------------------------------------------- routes

router = APIRouter(tags=["viewer"])
Viewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.VIEWER))]


@router.get("/docs/{doc_id}/viewer")
def get_viewer(
    doc_id: UUID,
    user: Viewer,
    session: Annotated[Session, Depends(get_session)],
    minio: Annotated[Minio, Depends(get_minio)],
    anchor: Annotated[str, Query(max_length=600)] = "",
    translate: bool = False,
) -> ViewerPayload:
    try:
        return build_viewer_payload(session, doc_id, anchor, translate, lambda u: presign_get(minio, u))
    except AnchorError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DocumentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no document {doc_id}") from exc
