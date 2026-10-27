"""A1.1 pre-flight (file 03 §A1.1): can the PDF be read, and what does each page's text layer look like.

- A PDF that needs a user password → `PreflightFailure("encrypted")`; the route raises PARSE_FAILURE (HARD).
  One that opens without a password (owner-password restrictions only, e.g. the ECSS standards) is decrypted
  in memory and processed (file 03 §A1.1 as amended 2026-10-23); `decrypted = True`.
- A damaged file is repaired by rewriting it with pikepdf (`repaired = True`); unrepairable → failure.
- Per page: characters in the text layer, a garbage ratio, embedded image count and the share of the page
  the images cover, rotation, size.
  A page with fewer than 50 characters or more than 40% garbage is image-only for triage. Garbage is counted
  by Unicode category (private use, unassigned, control, replacement character) and by "words" that carry no
  run of two letters, so Japanese or Cyrillic text is not garbage while a font without a ToUnicode map is.
- More than 400 pages → processing windows of 100 pages over the same CIR.
"""

import io
import unicodedata
from dataclasses import dataclass, field

import pikepdf
import pypdfium2 as pdfium

IMAGE_ONLY_MAX_CHARS = 50
GARBAGE_MAX_RATIO = 0.40
WINDOW_PAGES = 100
WINDOWED_ABOVE_PAGES = 400
BAD_CATEGORIES = frozenset({"Co", "Cn", "Cs", "Cc"})


class PreflightFailure(ValueError):
    """The PDF cannot be processed; `reason` goes into the PARSE_FAILURE flag."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class PageSignals:
    page_no: int
    width_pt: float
    height_pt: float
    rotation: int
    chars: int
    garbage_ratio: float
    image_count: int
    image_cover: float = 0.0  # share of the page under image objects, 0..1

    @property
    def image_only(self) -> bool:
        return self.chars < IMAGE_ONLY_MAX_CHARS or self.garbage_ratio > GARBAGE_MAX_RATIO


@dataclass(frozen=True)
class Preflight:
    pdf_bytes: bytes
    page_count: int
    repaired: bool
    pages: list[PageSignals]
    windows: list[tuple[int, int]] = field(default_factory=list)
    decrypted: bool = False

    def page(self, page_no: int) -> PageSignals:
        return self.pages[page_no - 1]


def image_cover(images, width: float, height: float) -> float:
    """Share of the page under image objects (their bounds clipped to the page, overlaps counted twice)."""
    area = 0.0
    for image in images:
        left, bottom, right, top = image.get_bounds()
        area += max(0.0, min(right, width) - max(left, 0.0)) * max(0.0, min(top, height) - max(bottom, 0.0))
    return min(1.0, area / (width * height)) if width and height else 0.0


def garbage_ratio(text: str) -> float:
    """Share of the text that is not language: bad code points plus symbol-soup tokens."""
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    bad = sum(
        1
        for ch in stripped
        if ch == "�" or unicodedata.category(ch) in BAD_CATEGORIES or (unicodedata.category(ch) == "Cc")
    )
    tokens = text.split()
    soup = [t for t in tokens if len(t) >= 3 and not _has_letter_run(t) and not _is_number_like(t)]
    soup_chars = sum(len(t) for t in soup)
    return min(1.0, (bad + soup_chars) / len(stripped))


def _has_letter_run(token: str) -> bool:
    run = 0
    for ch in token:
        run = run + 1 if ch.isalpha() else 0
        if run >= 2 or (ch.isalpha() and unicodedata.east_asian_width(ch) in "WF"):
            return True
    return False


def _is_number_like(token: str) -> bool:
    return sum(ch.isdigit() for ch in token) >= len(token) / 2


def windows(page_count: int) -> list[tuple[int, int]]:
    """1-based inclusive page windows; one window when the document is not long."""
    if page_count <= WINDOWED_ABOVE_PAGES:
        return [(1, page_count)] if page_count else []
    return [
        (start, min(start + WINDOW_PAGES - 1, page_count)) for start in range(1, page_count + 1, WINDOW_PAGES)
    ]


def decrypt(pdf_bytes: bytes) -> tuple[bytes, bool]:
    """The bytes without encryption when the PDF opens with an empty user password; a PDF that needs a
    password is a failure. Damaged files pass through unchanged (repaired in `_open`)."""
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes)) as probe:
            if not probe.is_encrypted:
                return pdf_bytes, False
            out = io.BytesIO()
            probe.save(out, encryption=False)
            return out.getvalue(), True
    except pikepdf.PasswordError as exc:
        raise PreflightFailure("encrypted", "the PDF needs a password") from exc
    except pikepdf.PdfError:
        return pdf_bytes, False


def _open(pdf_bytes: bytes) -> tuple[pdfium.PdfDocument, bytes, bool]:
    try:
        return pdfium.PdfDocument(pdf_bytes), pdf_bytes, False
    except pdfium.PdfiumError:
        pass
    try:
        out = io.BytesIO()
        with pikepdf.open(io.BytesIO(pdf_bytes)) as damaged:
            damaged.save(out)
        repaired = out.getvalue()
        return pdfium.PdfDocument(repaired), repaired, True
    except (pikepdf.PdfError, pdfium.PdfiumError) as exc:
        raise PreflightFailure("unrepairable", str(exc)[:200]) from exc


def preflight(pdf_bytes: bytes) -> Preflight:
    pdf_bytes, decrypted = decrypt(pdf_bytes)
    document, usable, repaired = _open(pdf_bytes)
    try:
        if len(document) == 0:
            raise PreflightFailure("no_pages", "the PDF has no pages")
        pages = []
        for index in range(len(document)):
            page = document[index]
            text = page.get_textpage().get_text_range()
            width, height = page.get_size()
            images = [obj for obj in page.get_objects() if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE]
            pages.append(
                PageSignals(
                    page_no=index + 1,
                    width_pt=width,
                    height_pt=height,
                    rotation=page.get_rotation(),
                    chars=len("".join(text.split())),
                    garbage_ratio=garbage_ratio(text),
                    image_count=len(images),
                    image_cover=image_cover(images, width, height),
                )
            )
        return Preflight(usable, len(pages), repaired, pages, windows(len(pages)), decrypted)
    finally:
        document.close()


def render_page(
    pdf_bytes: bytes, page_no: int, *, long_side_px: int | None = None, dpi: int | None = None
) -> bytes:
    """PNG of one page: thumbnail by long side (triage 768 px) or render at a dpi (150 assets, 300 crops)."""
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_no - 1]
        width, height = page.get_size()
        if long_side_px is not None:
            scale = long_side_px / max(width, height)
        else:
            scale = (dpi or 150) / 72
        image = page.render(scale=scale).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        document.close()


def render_crop(pdf_bytes: bytes, box, *, dpi: int = 300, pad_px: int = 20) -> bytes:
    """PNG of a region (`PageBox`, 0..1 top-left) at `dpi` with `pad_px` padding, for Gemini (A1.3, A1.7)."""
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        image = document[box.page_no - 1].render(scale=dpi / 72).to_pil()
        width, height = image.size
        left = max(0, int(box.x0 * width) - pad_px)
        top = max(0, int(box.y0 * height) - pad_px)
        right = min(width, int(box.x1 * width) + pad_px)
        bottom = min(height, int(box.y1 * height) + pad_px)
        buffer = io.BytesIO()
        image.crop((left, top, max(right, left + 1), max(bottom, top + 1))).save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        document.close()
