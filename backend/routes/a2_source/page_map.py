"""Page map from a LaTeX document to its compiled PDF twin (file 03 §A2.2 step 7, §1.3 "visual twin").

Each section heading is looked up in the twin's page text, in document order and never backwards:
``3 Test Setup`` matches a page that prints ``3. Test Setup``. Pages that print many headings (table of
contents, list of figures) are not candidates. Nodes take the page of their section, so a citation can open
the PDF page next to the ``.tex`` line.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

TOC_MIN_HEADINGS = 3
TOC_FRACTION = 0.3


@dataclass(frozen=True)
class Heading:
    key: str
    number: str
    title: str


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", text)).strip()


def page_texts(pdf_bytes: bytes) -> list[str]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        texts = []
        for index in range(len(pdf)):
            page = pdf[index]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range())
            finally:
                textpage.close()
                page.close()
        return texts
    finally:
        pdf.close()


def _needles(heading: Heading) -> list[str]:
    title = normalize(heading.title)
    if not title:
        return []
    return [normalize(f"{heading.number} {heading.title}"), title] if heading.number else [title]


def map_headings(headings: Sequence[Heading], pages: Sequence[str]) -> dict[str, int]:
    """Heading key → 1-based twin page; headings not found are left out."""
    normalized = [f" {normalize(p)} " for p in pages]
    needles = {h.key: _needles(h) for h in headings}
    threshold = max(TOC_MIN_HEADINGS, int(TOC_FRACTION * len(headings)))
    listing_pages = {
        i
        for i, text in enumerate(normalized)
        if sum(any(f" {n} " in text for n in needles[h.key][:1]) for h in headings if needles[h.key])
        >= threshold
    }
    found: dict[str, int] = {}
    cursor = 0
    for heading in headings:
        for needle in needles[heading.key]:
            hit = next(
                (
                    i
                    for i in range(cursor, len(normalized))
                    if i not in listing_pages and f" {needle} " in normalized[i]
                ),
                None,
            )
            if hit is not None:
                found[heading.key] = hit + 1
                cursor = hit
                break
    return found
