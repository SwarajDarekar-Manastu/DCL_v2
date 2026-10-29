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

Formula and code enrichment (Docling's CodeFormula VLM on CPU) is capped per document: an
`EnrichmentBudget` is set around a document's conversions (`enrichment_budget`), the model's elements beyond
`limit` are skipped (their text stays the layout text) and counted. Batching was measured and does not help
on CPU (3 formulas: batch 1 79–107 s, batch 5 113 s, batch 16 117 s; about 30 s per formula), so Docling's
batch size stays. ECSS-E-ST-35-06C ran past the cpu_parse limit in this stage on the live re-run. Docling's
own stage profile (`timings`) is kept per run so a slow document shows where the time went.

Second pass (A1.3): a scanned page whose `ocr_score` stays below 0.6 is converted again with EasyOCR when
its script is Latin; a page that is still low goes whole to `transcribe_page` (Gemini, any script).
"""

import gzip
import io
import json
import logging
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from backend.common.parallel import check
from backend.routes.a1_office.triage import PageDecision

LOW_OCR_SCORE = 0.6
MAX_RUN_PAGES = 100  # each run is saved when done, so a task's turn can end between runs (common/parallel.py)
WORK = "work/"  # what one processing of a file keeps between its turns; cleared when it starts and ends
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
    timings: dict[str, float] = field(default_factory=dict)  # Docling stage → seconds (summed)


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


def plan_runs(decisions: Iterable[PageDecision], max_pages: int = MAX_RUN_PAGES) -> list[Run]:
    """Contiguous pages with the same plan form one run of at most `max_pages`; blank pages stay in the
    surrounding run. Docling reads page by page, so where a run ends does not change what it reads."""
    runs: list[Run] = []
    for decision in sorted(decisions, key=lambda d: d.page_no):
        plan = (
            OcrPlan(
                decision.ocr_engine, engine_languages(decision.ocr_engine, decision.language, decision.script)
            )
            if decision.ocr_engine
            else None
        )
        last = runs[-1] if runs else None
        if last and last.ocr == plan and last.last == decision.page_no - 1 and len(last.pages) < max_pages:
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


ENRICHMENT_MAX = 200  # default of pipeline_config `routes.A1.formula_enrichment_max`


@dataclass
class EnrichmentBudget:
    """Formula and code items one document may send to the CodeFormula model."""

    limit: int = ENRICHMENT_MAX
    used: int = 0
    skipped: int = 0


_BUDGET: ContextVar[EnrichmentBudget | None] = ContextVar("a1_enrichment_budget", default=None)


@contextmanager
def enrichment_budget(limit: int = ENRICHMENT_MAX):
    budget = EnrichmentBudget(limit=limit)
    token = _BUDGET.set(budget)
    try:
        yield budget
    finally:
        _BUDGET.reset(token)


def cap_enrichment(model) -> None:
    """Wrap a Docling enrichment model so the current document's budget decides which elements it gets."""
    if getattr(model, "_dcl_capped", False):
        return
    original = model.prepare_element

    def prepare_element(conv_res, element):
        prepared = original(conv_res=conv_res, element=element)
        budget = _BUDGET.get()
        if prepared is None or budget is None:
            return prepared
        if budget.used >= budget.limit:
            budget.skipped += 1
            return None
        budget.used += 1
        return prepared

    model.prepare_element = prepare_element
    model._dcl_capped = True


@lru_cache(maxsize=CONVERTER_CACHE)
def _converter(ocr: OcrPlan | None):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.settings import settings
    from docling.document_converter import DocumentConverter, PdfFormatOption

    quiet_osd()
    settings.debug.profile_pipeline_timings = True
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options(ocr))}
    )
    pipeline = converter._get_pipeline(InputFormat.PDF)  # built now so its enrichment model can be capped
    for model in pipeline.enrichment_pipe:
        if type(model).__name__.startswith("CodeFormula"):
            cap_enrichment(model)
    return converter


def _timings(result) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, item in (getattr(result, "timings", None) or {}).items():
        times = getattr(item, "times", None) or []
        out[key] = round(float(sum(times)), 3)
    return out


def convert_run(pdf_bytes: bytes, run: Run, name: str = "document.pdf") -> RunResult:
    from docling_core.types.io import DocumentStream

    result = _converter(run.ocr).convert(
        DocumentStream(name=name, stream=io.BytesIO(pdf_bytes)), page_range=(run.first, run.last)
    )
    pages = result.confidence.model_dump(mode="json").get("pages", {}) if result.confidence else {}
    return RunResult(run, result.document, {int(k): v for k, v in pages.items()}, _timings(result))


def run_key(run: Run) -> str:
    plan = f"{run.ocr.engine}-{'+'.join(run.ocr.languages)}" if run.ocr else "text"
    return f"{WORK}runs/{run.first:04d}-{run.last:04d}-{plan}.json.gz"


def dump_run(result: RunResult) -> bytes:
    return gzip.compress(
        json.dumps(
            {
                "document": result.document.export_to_dict(),
                "page_confidence": result.page_confidence,
                "timings": result.timings,
            }
        ).encode()
    )


def load_run(run: Run, data: bytes) -> RunResult:
    from docling_core.types.doc import DoclingDocument

    saved = json.loads(gzip.decompress(data))
    document = DoclingDocument.model_validate(saved["document"])
    confidence = {int(page): scores for page, scores in saved["page_confidence"].items()}
    return RunResult(run, document, confidence, saved["timings"])


def saved_runs(
    convert: Callable[..., RunResult],
    get: Callable[[str], bytes | None],
    put: Callable[[str, bytes], str],
    deadline: float | None = None,
    load: Callable[[Run, bytes], RunResult] = load_run,
    dump: Callable[[RunResult], bytes] = dump_run,
) -> Callable[..., RunResult]:
    """`convert` keeping each run in the CIR (`work/runs/…`): a document whose task's turn ended between
    runs goes on from the runs already done. A new run starts only within the turn (`deadline`)."""

    def run(pdf_bytes: bytes, plan: Run, name: str = "document.pdf") -> RunResult:
        key = run_key(plan)
        if (data := get(key)) is not None:
            return load(plan, data)
        check(deadline)
        result = convert(pdf_bytes, plan, name)
        put(key, dump(result))
        return result

    return run


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
