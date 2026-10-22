"""Route A1 for PDFs (file 03 §4): one landed PDF → `ProcessedDocument` (S1's contract) + CIR + assets.

Order: pre-flight (A1.1) → page triage (A1.2) → Docling runs by OCR plan (A1.3) with the second pass →
structure (A1.11, references) → figures (A1.6) → tables QA (A1.4) → handwriting (A1.7) → metadata (L1) →
page renders and the CIR. The common tail (`backend/indexing/index_document`) takes it from there.

Second pass: a scanned page whose `ocr_score` stays below 0.6 is converted again with EasyOCR when its script
is Latin; if it is still low (or EasyOCR is not installed) it goes whole to `transcribe_page` when cloud
processing is allowed, else it keeps its OCR text with a LOW_CONFIDENCE_EXTRACTION (SOFT) flag.

CIR (`dcl-cir/{sha256}/A1/v{parser_version}/`): `docling/{first}-{last}.json` per run, `pages/{n}.txt`,
`pages/{n}.meta.json` (triage, signals, Docling confidence, OCR engine and pass), `page_hashes.json`.
Assets: `pages/{sha256}/{page:04d}.png` at 150 dpi, figure and handwriting crops at 300 dpi.
Not yet here: the visual-twin check and page map (A1.0), DOCX/PPTX (A1.9–A1.10), checkbox state calls.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from backend.dispatcher.contract import (
    DocumentFields,
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    ParseFailureEvidence,
    ProcessedAsset,
    ProcessedDocument,
    ProcessedNode,
    UnitHash,
)
from backend.dispatcher.folder_context import FolderContext
from backend.llm_engine.gemini_types import GeminiError, Image
from backend.postgres.enums import AssetKind, FlagSeverity, FlagType, NodeSource, NodeType, Route
from backend.routes.a1_office.convert import OcrPlan, Run, RunResult, convert_run, low_ocr_pages, plan_runs
from backend.routes.a1_office.figures import read_figures
from backend.routes.a1_office.handwriting import transcribe_regions
from backend.routes.a1_office.metadata import extract_metadata, humanize, plan_conflicts
from backend.routes.a1_office.preflight import Preflight, PreflightFailure, preflight, render_page
from backend.routes.a1_office.structure import PageContext, build_structure
from backend.routes.a1_office.tables_qa import check_tables
from backend.routes.a1_office.triage import PageDecision, triage_pages

PARSER_VERSION = 1
RENDER_DPI = 150

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Stores:
    """Where the route writes: `put_cir(relative_key, bytes) -> uri` under the document's CIR prefix and
    `put_asset(key, bytes) -> uri` in dcl-assets (S1's BucketStore in the workers)."""

    put_cir: Callable[[str, bytes], str]
    put_asset: Callable[[str, bytes], str]


def _strip_nul(value):
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    return value


def without_nul(processed: ProcessedDocument) -> ProcessedDocument:
    """PostgreSQL text cannot hold NUL bytes, which some PDF text layers carry (seen live on an Elsevier
    paper: the commit failed); they carry no meaning, so every string of the output drops them."""
    data = processed.model_dump(mode="json")
    cleaned = _strip_nul(data)
    return processed if cleaned == data else ProcessedDocument.model_validate(cleaned)


def _failed(
    blob_sha256: str, file_name: str, failure: PreflightFailure, data: bytes, cir_uri: str
) -> ProcessedDocument:
    flag = Flag(
        flag_type=FlagType.PARSE_FAILURE,
        severity=FlagSeverity.HARD,
        evidence=ParseFailureEvidence(
            error=str(failure),
            magic_bytes_hex=data[:16].hex(),
            size_bytes=len(data),
            detected_mime="application/pdf",
            extension=file_name.rsplit(".", 1)[-1],
        ),
    )
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.A1,
        parser_version=PARSER_VERSION,
        cir_uri=cir_uri,
        document=DocumentFields(title=humanize(file_name), page_count=0),
        flags=[flag],
    )


def _second_pass(
    pdf_bytes: bytes,
    results: list[RunResult],
    decisions: dict[int, PageDecision],
    name: str,
    convert: Callable[..., RunResult],
) -> tuple[list[RunResult], list[int], dict[int, str]]:
    """Retry a Tesseract run with low pages through EasyOCR (Latin scripts) and keep the better run.
    Returns (results, pages still low, OCR pass per page)."""
    final, still_low, passes = [], [], {}
    for result in results:
        low = low_ocr_pages(result)
        latin = all(str(decisions[p].script or "latin") == "latin" for p in result.run.pages)
        if low and result.run.ocr and result.run.ocr.engine == "tesseract" and latin:
            try:
                retry = convert(
                    pdf_bytes, Run(result.run.first, result.run.last, OcrPlan("easyocr", ("en",))), name
                )
            except (ImportError, RuntimeError, OSError):
                retry = None
            if retry is not None and len(low_ocr_pages(retry)) < len(low):
                result, low = retry, low_ocr_pages(retry)
                passes.update({p: "easyocr" for p in result.run.pages})
        final.append(result)
        still_low += low
    return final, still_low, passes


def process_pdf(
    pdf_bytes: bytes,
    *,
    blob_sha256: str,
    file_name: str,
    folder: FolderContext,
    vision,
    stores: Stores,
    cloud_allowed: bool = True,
    doc_id: str | None = None,
    critical_field_patterns: Iterable[str] = (),
    engine_by_script: dict[str, str] | None = None,
    convert: Callable[..., RunResult] = convert_run,
) -> ProcessedDocument:
    cir_uri = f"s3://dcl-cir/{blob_sha256}/A1/v{PARSER_VERSION}/"
    try:
        checked: Preflight = preflight(pdf_bytes)
    except PreflightFailure as failure:
        return _failed(blob_sha256, file_name, failure, pdf_bytes, cir_uri)
    context = " / ".join([*folder.breadcrumb, file_name])
    pdf = checked.pdf_bytes
    decisions = triage_pages(
        checked,
        vision,
        context=context,
        doc_id=doc_id,
        cloud_allowed=cloud_allowed,
        engine_by_script=engine_by_script,
    )
    by_page = {d.page_no: d for d in decisions}

    first_pass = [convert(pdf, run, file_name) for run in plan_runs(decisions)]
    results, still_low, passes = _second_pass(pdf, first_pass, by_page, file_name, convert)

    page_contexts: dict[int, PageContext] = {}
    page_ocr: dict[int, float | None] = {}
    for result in results:
        for page_no in result.run.pages:
            score = result.page_confidence.get(page_no, {}).get("ocr_score")
            score = None if score is None or score != score else float(score)
            page_ocr[page_no] = score
            page_contexts[page_no] = PageContext(
                language=by_page[page_no].language,
                source=NodeSource.OCR if result.run.ocr else NodeSource.PRINTED,
                confidence=score if result.run.ocr else None,
            )
    structure = build_structure(
        [r.document for r in results], page_contexts, fallback_title=humanize(file_name)
    )
    nodes: list[ProcessedNode] = structure.nodes
    furniture = {page: list(lines) for page, lines in structure.furniture.items()}
    flags: list[Flag] = []
    assets: list[ProcessedAsset] = []

    for page_no in still_low:
        reading = None
        if cloud_allowed:
            image = Image(render_page(pdf, page_no, dpi=200), "image/png")
            try:
                reading = vision.transcribe_page(
                    image,
                    context=context,
                    language_hint=by_page[page_no].language,
                    doc_id=doc_id,
                    anchor=f"page:{page_no}:",
                ).reading
            except GeminiError as exc:  # e.g. a safety block on propellant chemistry: keep the OCR text
                log.warning("transcribe_page failed on page %s of %s: %s", page_no, file_name, exc)
        if reading is not None:
            keep = [n for n in nodes if n.page_no != page_no]
            crumb = next(
                (n.breadcrumb for n in nodes if n.page_no == page_no), structure.title or humanize(file_name)
            )
            paragraphs = [p.strip() for p in reading.markdown.split("\n\n") if p.strip()]
            nodes = keep + [
                ProcessedNode(
                    ref=f"vlm/p{page_no}/{i}",
                    node_type=NodeType.CHILD,
                    ordinal=0,
                    breadcrumb=crumb,
                    language=reading.language,
                    content=p,
                    page_no=page_no,
                    source=NodeSource.VLM,
                    confidence=reading.confidence,
                )
                for i, p in enumerate(paragraphs)
            ]
            # v2: the model's headers and footers replace the failed OCR's, one printed line each
            furniture[page_no] = [line for f in reading.furniture for line in f.splitlines() if line.strip()]
            passes[page_no] = "transcribe_page"
        else:
            flags.append(
                Flag(
                    flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
                    severity=FlagSeverity.SOFT,
                    anchor=FlagAnchor(page=page_no),
                    evidence=LowConfidenceEvidence(),
                )
            )
            passes[page_no] = "transcribe_failed" if cloud_allowed else "ocr_low"
    nodes = sorted(nodes, key=lambda n: (n.page_no or 0, n.ordinal))

    figures = read_figures(
        nodes,
        pdf_bytes=pdf,
        blob_sha256=blob_sha256,
        vision=vision,
        context=context,
        doc_id=doc_id,
        cloud_allowed=cloud_allowed,
        put_asset=stores.put_asset,
    )
    tables = check_tables(
        figures.nodes,
        pdf_bytes=pdf,
        page_ocr=page_ocr,
        vision=vision,
        context=context,
        doc_id=doc_id,
        cloud_allowed=cloud_allowed,
    )
    handwriting = transcribe_regions(
        tables.nodes,
        decisions,
        pdf_bytes=pdf,
        blob_sha256=blob_sha256,
        vision=vision,
        context=context,
        test_plan_id=folder.test_plan_id,
        doc_id=doc_id,
        cloud_allowed=cloud_allowed,
        critical_field_patterns=critical_field_patterns,
        put_asset=stores.put_asset,
    )
    nodes = [n.model_copy(update={"ordinal": i}) for i, n in enumerate(handwriting.nodes)]
    flags += figures.flags + tables.flags + handwriting.flags
    assets += figures.assets + handwriting.assets

    page_text = {
        p: "\n".join(n.content for n in nodes if n.page_no == p) for p in range(1, checked.page_count + 1)
    }
    metadata = extract_metadata(
        file_name=file_name,
        title=structure.title,
        first_page_text=page_text.get(1, ""),
        full_text="\n".join(page_text.values()),
        furniture=[t for p in sorted(furniture) for t in furniture[p]],
        folder=folder,
        page_languages=[d.language for d in decisions],
        page_count=checked.page_count,
    )
    flags += metadata.flags
    flags += plan_conflicts(folder, furniture, page_text.get(1, ""))

    for page_no in range(1, checked.page_count + 1):
        uri = stores.put_asset(
            f"pages/{blob_sha256}/{page_no:04d}.png", render_page(pdf, page_no, dpi=RENDER_DPI)
        )
        assets.append(
            ProcessedAsset(ref=f"page:{page_no}", kind=AssetKind.PAGE_RENDER, minio_uri=uri, page_no=page_no)
        )
    for result in results:
        stores.put_cir(
            f"docling/{result.run.first}-{result.run.last}.json",
            json.dumps(result.document.export_to_dict(), ensure_ascii=False).encode(),
        )
    hashes = {p: hashlib.sha256(t.encode("utf-8")).hexdigest() for p, t in page_text.items()}
    for page_no, decision in by_page.items():
        signals = checked.page(page_no)
        meta = {
            **decision.meta(),
            "chars": signals.chars,
            "garbage_ratio": signals.garbage_ratio,
            "rotation": signals.rotation,
            "ocr_pass": passes.get(page_no, "first" if decision.ocr_engine else None),
            "confidence": next(
                (r.page_confidence.get(page_no) for r in results if page_no in r.run.pages), None
            ),
        }
        stores.put_cir(
            f"pages/{page_no}.meta.json", json.dumps(meta, ensure_ascii=False, default=str).encode()
        )
        stores.put_cir(f"pages/{page_no}.txt", page_text.get(page_no, "").encode("utf-8"))
    stores.put_cir("page_hashes.json", json.dumps(hashes).encode())

    return without_nul(
        ProcessedDocument(
            blob_sha256=blob_sha256,
            route=Route.A1,
            parser_version=PARSER_VERSION,
            cir_uri=cir_uri,
            document=metadata.fields,
            nodes=nodes,
            assets=assets,
            mentions=structure.mentions,
            flags=_unique_flags(flags),
            unit_hashes=[UnitHash(unit="page", key=str(p), sha256=h) for p, h in sorted(hashes.items())],
        )
    )


def _unique_flags(flags: list[Flag]) -> list[Flag]:
    seen, out = set(), []
    for flag in flags:
        if flag.fingerprint not in seen:
            seen.add(flag.fingerprint)
            out.append(flag)
    return out
