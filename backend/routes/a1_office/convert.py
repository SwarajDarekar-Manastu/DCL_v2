"""A1.3 Docling conversion (file 03 §A1.3): runs by OCR plan, options per run, page confidences.

Docling takes one OCR engine and one language list per conversion, so the triaged pages are cut into runs:
contiguous pages sharing one plan (no OCR for digital pages; engine + languages for a scanned script group).
Every run converts with TableFormer ACCURATE, formula and code enrichment and picture classification;
scanned runs OCR the full page. Picture description through Docling's remote API is never used: figures go
to VisionService (A1.6) so prompts and schemas are ours and logged. Runs execute on CPU (the GPU belongs to
the models role, decision H12).

Docling converters are cached per OCR plan in the worker process: building one loads the layout, table,
formula and code models (2–5 s on CPU), which a document with many alternating digital and scanned runs
used to pay per run.

Docling runs Tesseract's orientation detection (OSD, `--psm 0`) on every OCR'd page and logs an ERROR when
the page has too few characters for it; OCR then proceeds with our explicit script model and orientation 0,
so `QuietOsd` logs that one case as INFO. Other OSD failures stay errors. Rotation comes from triage.

Second pass (A1.3): a scanned page whose `ocr_score` stays below 0.6 is converted again with EasyOCR when
its script is Latin; a page that is still low goes whole to `transcribe_page` (Gemini, any script).
"""

import io
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from backend.routes.a1_office.triage import PageDecision

LOW_OCR_SCORE = 0.6
TESSERACT_SCRIPT_MODELS = {  # the parse image ships Tesseract script models (S4), one per script group
    "latin": "Latin",
    "cyrillic": "Cyrillic",
    "devanagari": "Devanagari",
    "arabic": "Arabic",
    "mixed": "Latin",
}
DOCLING_LANGUAGE_CODES = {
    "rapidocr": {"ja": "japan", "zh": "chinese", "ko": "korean"},
    "easyocr": {"en": "en", "de": "de", "fr": "fr", "es": "es", "it": "it"},
}


@dataclass(frozen=True)
class OcrPlan:
    engine: str
    languages: tuple[str, ...]


@dataclass(frozen=True)
class Run:
    """Pages `first..last` (1-based, inclusive) converted with one plan; `ocr=None` means the text layer."""

    first: int
    last: int
    ocr: OcrPlan | None

    @property
    def pages(self) -> range:
        return range(self.first, self.last + 1)


@dataclass
class RunResult:
    run: Run
    document: Any  # docling_core DoclingDocument
    page_confidence: dict[int, dict[str, Any]] = field(default_factory=dict)


def engine_languages(engine: str, language: str | None, script: str | None = None) -> tuple[str, ...]:
    """Tesseract: the script model of the page (`Latin`, `Cyrillic`, …). RapidOCR and EasyOCR: the language
    code for the BCP-47 tag (EasyOCR always with English as a fallback)."""
    if engine == "tesseract":
        return (TESSERACT_SCRIPT_MODELS.get(str(script or "latin"), "Latin"),)
    codes = DOCLING_LANGUAGE_CODES.get(engine, {})
    primary = (language or "en").split("-")[0].lower()
    chosen = [codes[primary]] if primary in codes else []
    if engine == "easyocr" and codes["en"] not in chosen:
        chosen.append(codes["en"])
    return tuple(chosen)


def plan_runs(decisions: Iterable[PageDecision]) -> list[Run]:
    """Contiguous pages with the same plan form one run; blank pages stay in the surrounding run."""
    runs: list[Run] = []
    for decision in sorted(decisions, key=lambda d: d.page_no):
        plan = (
            OcrPlan(
                decision.ocr_engine, engine_languages(decision.ocr_engine, decision.language, decision.script)
            )
            if decision.ocr_engine
            else None
        )
        if runs and runs[-1].ocr == plan and runs[-1].last == decision.page_no - 1:
            runs[-1] = Run(runs[-1].first, decision.page_no, plan)
        else:
            runs.append(Run(decision.page_no, decision.page_no, plan))
    return runs


def pipeline_options(ocr: OcrPlan | None):
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.pipeline_options import (
        EasyOcrOptions,
        OcrMode,
        PdfPipelineOptions,
        RapidOcrOptions,
        TableFormerMode,
        TesseractCliOcrOptions,
    )

    options = PdfPipelineOptions()
    options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.do_formula_enrichment = True
    options.do_code_enrichment = True
    options.do_picture_classification = True
    options.do_picture_description = False
    options.enable_remote_services = False
    options.do_ocr = ocr is not None
    if ocr is not None:
        builders = {
            "tesseract": TesseractCliOcrOptions,
            "rapidocr": RapidOcrOptions,
            "easyocr": EasyOcrOptions,
        }
        options.ocr_options = builders[ocr.engine](lang=list(ocr.languages), mode=OcrMode.FULL_PAGE)
    return options


DOCLING_TESSERACT_LOGGER = "docling.models.stages.ocr.tesseract_ocr_cli_model"
CONVERTER_CACHE = 3  # text layer + the scanned plans of one document; each holds its own models


class QuietOsd(logging.Filter):
    """Docling's "OSD failed … Too few characters" on a near-empty page is expected: log it as INFO."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.ERROR and record.getMessage().startswith("OSD failed"):
            if "Too few characters" in record.getMessage():
                record.levelno, record.levelname = logging.INFO, "INFO"
        return True


def quiet_osd() -> None:
    logger = logging.getLogger(DOCLING_TESSERACT_LOGGER)
    if not any(isinstance(f, QuietOsd) for f in logger.filters):
        logger.addFilter(QuietOsd())


@lru_cache(maxsize=CONVERTER_CACHE)
def _converter(ocr: OcrPlan | None):
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption

    quiet_osd()
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options(ocr))}
    )


def convert_run(pdf_bytes: bytes, run: Run, name: str = "document.pdf") -> RunResult:
    from docling_core.types.io import DocumentStream

    result = _converter(run.ocr).convert(
        DocumentStream(name=name, stream=io.BytesIO(pdf_bytes)), page_range=(run.first, run.last)
    )
    pages = result.confidence.model_dump(mode="json").get("pages", {}) if result.confidence else {}
    return RunResult(run, result.document, {int(k): v for k, v in pages.items()})


def low_ocr_pages(result: RunResult) -> list[int]:
    """Pages of an OCR run whose ocr_score stayed below the threshold (candidates for the second pass)."""
    if result.run.ocr is None:
        return []
    low = []
    for page_no in result.run.pages:
        score = result.page_confidence.get(page_no, {}).get("ocr_score")
        if score is None or score != score or score < LOW_OCR_SCORE:  # NaN means no OCR text at all
            low.append(page_no)
    return low
