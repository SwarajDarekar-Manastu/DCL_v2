"""A1.0 visual twin (file 03 §A1.0): a PDF compiled from `.tex` or the JSON section set that Route A2 indexes.

Route A2 (S6) owns the text; this module gives it what only the PDF has:

- `page_map(headings, pages)`: every A2 section heading located in the PDF page texts, in document order
  (normalized text, numbering kept; a heading that is not found takes the page of the one before it, so the
  map is monotonic and every section has a page; a page holding three or more numbered headings in full
  ("2.1 Instrumentation") is a table of contents and is skipped). A2 sets `page_no` on its nodes from it
  and writes `page_map.json`.
- `pdf_only_pages(pages, source_text)`: pages whose words are mostly absent from the source (scanned
  appendices, signature and approval pages, an image-only page).
- `process_twin(...)`: page renders for every page (PAGE_RENDER assets, the citation highlights), the page
  map in the CIR, and the PDF-only pages run through the full A1 pipeline as if there were no twin; their
  nodes come back under the section "Appendix (PDF-only)" with their real page numbers.
"""

import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import pikepdf
import pypdfium2 as pdfium

from backend.dispatcher.contract import Flag, ProcessedAsset, ProcessedNode
from backend.postgres.enums import AssetKind
from backend.routes.a1_office.assets import image_fields
from backend.routes.a1_office.preflight import render_page

APPENDIX = "Appendix (PDF-only)"
PDF_ONLY_SHARE = 0.3  # a page sharing less than this share of its words with the source is PDF-only
MIN_WORDS = 15  # fewer words (or none: a scan) counts as PDF-only content when the page has any image
RENDER_DPI = 150
WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.]", " ", text)).strip().casefold()


def page_texts(pdf_bytes: bytes) -> list[str]:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return [document[i].get_textpage().get_text_range() for i in range(len(document))]
    finally:
        document.close()


TOC_HEADINGS = 3  # a page that contains this many numbered headings is a table of contents, not their pages
NUMBERED = re.compile(r"^\d+(?:\.\d+)*\.?\s")


def _strip_number(text: str) -> str:
    return re.sub(r"^[\d.]+\s*", "", text)


def _on_page(target: str, page: str) -> bool:
    words = _strip_number(target)
    return bool(target) and (target in page or bool(words) and words in page)


def page_map(headings: list[str], pages: list[str]) -> dict[int, int]:
    """heading index → 1-based page; order-constrained, a miss inherits the previous page. Pages that contain
    TOC_HEADINGS or more headings (a text table of contents) are skipped, so a heading listed in the contents
    maps to the page where its section starts."""
    normalized = [_normalized(p) for p in pages]
    targets = [_normalized(h) for h in headings]
    numbered = [t for t in targets if NUMBERED.match(t)]
    toc = {  # only full "number title" matches count: a body page may mention three short titles in prose
        page_no
        for page_no, text in enumerate(normalized, start=1)
        if sum(t in text for t in numbered) >= TOC_HEADINGS
    }
    out: dict[int, int] = {}
    current = 1
    for index, target in enumerate(targets):
        ahead = [p for p in range(current, len(pages) + 1) if p not in toc]
        found = next((p for p in ahead if target and target in normalized[p - 1]), None)
        if found is None:  # numbering or punctuation differ: the title without its number
            found = next((p for p in ahead if _on_page(target, normalized[p - 1])), None)
        current = found or current
        out[index] = current
    return out


def pdf_only_pages(pages: list[str], source_text: str, image_pages: set[int] = frozenset()) -> list[int]:
    source = {w.casefold() for w in WORD.findall(source_text)}
    out = []
    for page_no, text in enumerate(pages, start=1):
        words = [w.casefold() for w in WORD.findall(text)]
        if len(words) < MIN_WORDS:
            if page_no in image_pages:
                out.append(page_no)
            continue
        if sum(w in source for w in words) / len(words) < PDF_ONLY_SHARE:
            out.append(page_no)
    return out


def _image_pages(pdf_bytes: bytes) -> set[int]:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return {
            i + 1
            for i in range(len(document))
            if any(obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE for obj in document[i].get_objects())
        }
    finally:
        document.close()


def _subset(pdf_bytes: bytes, pages: list[int]) -> bytes:
    with pikepdf.open(io.BytesIO(pdf_bytes)) as source, pikepdf.new() as out:
        for page_no in pages:
            out.pages.append(source.pages[page_no - 1])
        buffer = io.BytesIO()
        out.save(buffer)
        return buffer.getvalue()


@dataclass
class TwinResult:
    page_map: dict[int, int]
    pdf_only_pages: list[int]
    assets: list[ProcessedAsset] = field(default_factory=list)
    appendix_nodes: list[ProcessedNode] = field(default_factory=list)
    appendix_assets: list[ProcessedAsset] = field(default_factory=list)
    appendix_flags: list[Flag] = field(default_factory=list)


def _remap_page(value: int | None, real: list[int]) -> int | None:
    return real[value - 1] if value is not None and 1 <= value <= len(real) else value


def process_twin(
    pdf_bytes: bytes,
    headings: list[str],
    source_text: str,
    *,
    blob_sha256: str,
    title: str,
    put_asset: Callable[[str, bytes], str],
    put_cir: Callable[[str, bytes], str],
    appendix: Callable[..., object] | None = None,
) -> TwinResult:
    """`appendix(pdf_bytes, put_asset=…, put_cir=…)` runs A1 on the PDF-only pages (a bound `process_pdf`)."""
    pages = page_texts(pdf_bytes)
    mapping = page_map(headings, pages)
    only = pdf_only_pages(pages, source_text, _image_pages(pdf_bytes))
    result = TwinResult(mapping, only)
    for page_no in range(1, len(pages) + 1):
        png = render_page(pdf_bytes, page_no, dpi=RENDER_DPI)
        uri = put_asset(f"pages/{blob_sha256}/{page_no:04d}.png", png)
        result.assets.append(
            ProcessedAsset(
                ref=f"page:{page_no}",
                kind=AssetKind.PAGE_RENDER,
                minio_uri=uri,
                page_no=page_no,
                **image_fields(png),
            )
        )
    put_cir(
        "page_map.json",
        json.dumps(
            {
                "headings": [{"heading": h, "page_no": mapping[i]} for i, h in enumerate(headings)],
                "pdf_only": only,
            },
            ensure_ascii=False,
        ).encode(),
    )
    if not only or appendix is None:
        return result

    def sub_asset(key: str, data: bytes) -> str:
        match = re.fullmatch(rf"pages/{blob_sha256}/(\d{{4}})\.png", key)
        if match:  # renders of the subset are the real pages, already rendered above
            return f"s3://dcl-assets/pages/{blob_sha256}/{only[int(match.group(1)) - 1]:04d}.png"
        return put_asset(key.replace(f"{blob_sha256}/", f"{blob_sha256}/appendix-", 1), data)

    processed = appendix(
        _subset(pdf_bytes, only),
        put_asset=sub_asset,
        put_cir=lambda key, data: put_cir(f"appendix/{key}", data),
    )
    for node in processed.nodes:
        result.appendix_nodes.append(
            node.model_copy(
                update={
                    "ref": f"appendix/{node.ref}",
                    "parent_ref": f"appendix/{node.parent_ref}" if node.parent_ref else None,
                    "asset_ref": f"appendix/{node.asset_ref}" if node.asset_ref else None,
                    "page_no": _remap_page(node.page_no, only),
                    "page_end": _remap_page(node.page_end, only),
                    "bboxes": [
                        b.model_copy(update={"page_no": _remap_page(b.page_no, only)}) for b in node.bboxes
                    ],
                    "breadcrumb": f"{title} › {APPENDIX}"
                    + (f" › {node.breadcrumb.split(' › ', 1)[1]}" if " › " in node.breadcrumb else ""),
                }
            )
        )
    for asset in processed.assets:
        if asset.kind == AssetKind.PAGE_RENDER:
            continue
        result.appendix_assets.append(
            asset.model_copy(
                update={"ref": f"appendix/{asset.ref}", "page_no": _remap_page(asset.page_no, only)}
            )
        )
    for flag in processed.flags:
        anchor = flag.anchor.model_copy(update={"page": _remap_page(flag.anchor.page, only)})
        result.appendix_flags.append(flag.model_copy(update={"anchor": anchor}))
    return result
