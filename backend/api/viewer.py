"""Shared document viewer: deep-link contract and anchor resolution (file 08 §6, file 04 §4.4).

Deep link (chat citations, Review UI, Benchmark drilldowns):

    {CONSOLE_URL}/docs/{doc_id}/viewer?anchor=<kind>:<value>:<content_sha256>

    kind   value                         example
    page   page number, 1-based          page:12:9f86d081884c7d65
    line   first line, 1-based           line:120:ab12cd34ef56ab78
    t      milliseconds from the start   t:83500:
    cells  <sheet>!<A1 range>            cells:Run 1!A1:D20:0c1d2e3f4a5b6c7d

The hash part is lowercase hex (16 to 64 characters) or empty; the trailing colon is always written.
The anchor never carries a node id. Build links with `viewer_path()`; fields use the names of the
stable `Anchor` model (page_no, line_start, t_start_ms, sheet_name, cell_range, content_sha256).

The Console page calls GET /docs/{doc_id}/viewer?anchor=…[&translate=true] and renders the returned
`ViewerPayload`. Resolution: same locator and same hash → `exact`; hash differs or is missing →
`page_fallback` (the page, line, time or sheet is shown and the UI says so); locator gone →
`document_only`.
"""

import re
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, TypedDict
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.auth import ConsoleRole, ConsoleUser, require_role

# ---------------------------------------------------------------- anchor parameter


class AnchorFields(TypedDict, total=False):
    page_no: int
    line_start: int
    t_start_ms: int
    sheet_name: str
    cell_range: str
    content_sha256: str


class AnchorParamError(ValueError):
    pass


_HASH = re.compile(r"[0-9a-f]{16,64}")
_RANGE = re.compile(r"[A-Z]{1,3}[1-9][0-9]*(:[A-Z]{1,3}[1-9][0-9]*)?")


def _positive_int(value: str, name: str, minimum: int) -> int:
    if not value.isdigit() or int(value) < minimum:
        raise AnchorParamError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


def parse_anchor_param(param: str) -> AnchorFields:
    kind, sep, rest = param.partition(":")
    if not sep:
        raise AnchorParamError("anchor must look like <kind>:<value>:<hash>")
    value, sep, content_hash = rest.rpartition(":")
    if not sep:  # no hash part written: "page:12"
        value, content_hash = rest, ""
    if content_hash and not _HASH.fullmatch(content_hash):
        raise AnchorParamError("hash must be 16 to 64 lowercase hex characters")
    fields: AnchorFields = {"content_sha256": content_hash} if content_hash else {}
    if kind == "page":
        fields["page_no"] = _positive_int(value, "page", 1)
    elif kind == "line":
        fields["line_start"] = _positive_int(value, "line", 1)
    elif kind == "t":
        fields["t_start_ms"] = _positive_int(value, "t", 0)
    elif kind == "cells":
        sheet, bang, cell_range = value.rpartition("!")
        if not bang or not sheet or not _RANGE.fullmatch(cell_range):
            raise AnchorParamError("cells must look like <sheet>!<A1 range>")
        fields["sheet_name"], fields["cell_range"] = sheet, cell_range
    else:
        raise AnchorParamError(f"unknown anchor kind {kind!r} (page, line, t, cells)")
    return fields


def format_anchor_param(fields: AnchorFields) -> str:
    content_hash = fields.get("content_sha256", "")
    if "page_no" in fields:
        kind, value = "page", str(fields["page_no"])
    elif "line_start" in fields:
        kind, value = "line", str(fields["line_start"])
    elif "t_start_ms" in fields:
        kind, value = "t", str(fields["t_start_ms"])
    elif "sheet_name" in fields and "cell_range" in fields:
        kind, value = "cells", f"{fields['sheet_name']}!{fields['cell_range']}"
    else:
        raise AnchorParamError("anchor needs page_no, line_start, t_start_ms or sheet_name + cell_range")
    param = f"{kind}:{value}:{content_hash}"
    parse_anchor_param(param)  # refuse to emit a link the viewer cannot read
    return param


def viewer_path(doc_id: UUID | str, fields: AnchorFields) -> str:
    """Path of the Console viewer for an anchor; prefix it with the Console base URL."""
    return f"/docs/{doc_id}/viewer?anchor={quote(format_anchor_param(fields), safe=':!')}"


# ---------------------------------------------------------------- response models


class ResolutionStatus(StrEnum):
    EXACT = "exact"
    PAGE_FALLBACK = "page_fallback"
    DOCUMENT_ONLY = "document_only"


class ViewerResolution(BaseModel):
    status: ResolutionStatus
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


# ---------------------------------------------------------------- routes

router = APIRouter(tags=["viewer"])
Viewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.VIEWER))]


@router.get("/docs/{doc_id}/viewer")
def get_viewer(
    doc_id: UUID,
    user: Viewer,
    anchor: Annotated[str, Query(max_length=600)] = "",
    translate: bool = False,
) -> ViewerPayload:
    try:
        parse_anchor_param(anchor) if anchor else {}
    except AnchorParamError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "viewer resolution is not wired yet: needs the Anchor model, document and asset models, "
        "presign (S1) and resolve_anchor (S2)",
    )
