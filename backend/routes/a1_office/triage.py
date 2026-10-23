"""A1.2 page triage (file 03 §A1.2): decide what each page costs and which OCR engine reads it.

Signals per page: the pre-flight text layer (characters, garbage ratio) and one Flash-Lite `triage_page`
call on a 768 px thumbnail, which also reports language, script, rotation and handwriting regions. The
deterministic signals bound the model: an image-only page is never `digital_*`, and a page whose text layer
is good is never `scanned_printed` (the scan already carries usable text). Without cloud permission for the
root the page type comes from the signals alone.

Scanned pages are grouped by OCR engine for A1.3, because Docling takes one engine and language list per
run: Tesseract for Latin, Cyrillic, Devanagari and Arabic; RapidOCR for CJK
(`routes.A1.ocr_engine_by_script`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from backend.llm_engine.gemini_types import Image
from backend.llm_engine.vision.schemas import HandwritingRegion, PageTriage, PageType, Script
from backend.routes.a1_office.preflight import Preflight, render_page

THUMBNAIL_LONG_SIDE_PX = 768
DEFAULT_OCR_ENGINE_BY_SCRIPT: dict[str, str] = {
    Script.LATIN: "tesseract",
    Script.CYRILLIC: "tesseract",
    Script.DEVANAGARI: "tesseract",
    Script.ARABIC: "tesseract",
    Script.CJK: "rapidocr",
    Script.MIXED: "tesseract",
}
DIGITAL_TYPES = frozenset({PageType.DIGITAL_TEXT, PageType.DIGITAL_WITH_FIGURES, PageType.TABLE_DENSE})
OCR_TYPES = frozenset(
    {PageType.SCANNED_PRINTED, PageType.SCANNED_FORM_WITH_HANDWRITING, PageType.HANDWRITTEN_NOTES}
)


@dataclass(frozen=True)
class PageDecision:
    page_no: int
    page_type: PageType
    language: str | None
    script: Script | None
    is_rotated: bool
    image_only: bool
    ocr_engine: str | None
    handwriting_regions: list[HandwritingRegion] = field(default_factory=list)
    has_handwriting: bool = False
    has_tables: bool = False
    has_figures: bool = False
    triage_source: str = "signals"
    prompt_version: str | None = None

    def meta(self) -> dict:
        """The `pages/{n}.meta.json` triage part of the CIR (file 03 §2)."""
        return {
            "page_type": str(self.page_type),
            "language": self.language,
            "script": str(self.script) if self.script else None,
            "is_rotated": self.is_rotated,
            "image_only": self.image_only,
            "ocr_engine": self.ocr_engine,
            "triage_source": self.triage_source,
            "prompt_version": self.prompt_version,
            "handwriting_regions": [r.model_dump(mode="json") for r in self.handwriting_regions],
        }


def combine(reading: PageTriage | None, image_only: bool) -> PageType:
    """The model's page type, bounded by what the text layer proves."""
    if reading is None:
        return PageType.SCANNED_PRINTED if image_only else PageType.DIGITAL_TEXT
    page_type = reading.page_type
    if image_only and page_type in DIGITAL_TYPES:
        return PageType.SCANNED_PRINTED
    if not image_only and page_type == PageType.SCANNED_PRINTED:
        return PageType.DIGITAL_WITH_FIGURES if reading.has_figures else PageType.DIGITAL_TEXT
    return page_type


def ocr_engine(page_type: PageType, script: Script | None, table: Mapping[str, str]) -> str | None:
    if page_type not in OCR_TYPES:
        return None
    return table.get(script or Script.LATIN, table[Script.LATIN])


def triage_pages(
    preflight: Preflight,
    vision,
    *,
    context: str,
    doc_id: str | None = None,
    cloud_allowed: bool = True,
    engine_by_script: Mapping[str, str] | None = None,
) -> list[PageDecision]:
    """One decision per page; `vision` is a VisionService (cached, logged)."""
    table = {**DEFAULT_OCR_ENGINE_BY_SCRIPT, **(engine_by_script or {})}
    decisions = []
    for signals in preflight.pages:
        reading: PageTriage | None = None
        prompt_version = None
        if cloud_allowed:
            thumbnail = render_page(preflight.pdf_bytes, signals.page_no, long_side_px=THUMBNAIL_LONG_SIDE_PX)
            output = vision.triage_page(
                Image(thumbnail, "image/png"),
                context=f"{context} · page {signals.page_no} of {preflight.page_count}",
                doc_id=doc_id,
                anchor=f"page:{signals.page_no}:",
            )
            reading, prompt_version = output.reading, output.prompt_version
        page_type = combine(reading, signals.image_only)
        script = reading.script if reading else None
        decisions.append(
            PageDecision(
                page_no=signals.page_no,
                page_type=page_type,
                language=reading.language if reading else None,
                script=script,
                is_rotated=reading.is_rotated if reading else False,
                image_only=signals.image_only,
                ocr_engine=ocr_engine(page_type, script, table),
                handwriting_regions=list(reading.handwriting_regions) if reading else [],
                has_handwriting=reading.has_handwriting if reading else False,
                has_tables=reading.has_tables if reading else False,
                has_figures=reading.has_figures if reading else False,
                triage_source="vision+signals" if reading else "signals",
                prompt_version=prompt_version,
            )
        )
    return decisions


def ocr_groups(decisions: list[PageDecision]) -> dict[tuple[str, str | None], list[int]]:
    """Pages to OCR grouped by (engine, language): each Docling run gets one engine and one language list."""
    groups: dict[tuple[str, str | None], list[int]] = {}
    for decision in decisions:
        if decision.ocr_engine:
            groups.setdefault((decision.ocr_engine, decision.language), []).append(decision.page_no)
    return groups
