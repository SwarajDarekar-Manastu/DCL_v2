"""A1.7 handwriting (file 03 §A1.7, §A1.8): regions → crops → transcription → annotated spans with flags.

1. Regions come from the triage call (`box_2d` 0–1000, kinds value / correction / note); signatures and
   checkboxes are not transcribed (Docling reads checkbox state).
2. The context label is the nearest printed text on the same page: left of the region in the same line band,
   else above it within two line heights. The page's units come from labels such as `(bar)`.
3. `transcribe_handwriting` reads a 300 dpi crop with 20 px padding.
4. The reading enters the page as its own text node right after its label, written as
   `Label: [HW 0.85 | conf 0.92]`, so the uncertain span is visible wherever it is cited; the structure
   (box, label, value, unit, confidence, alternatives) stays in `metadata.handwriting`.
5. Confidence below 0.75 or illegible → LOW_CONFIDENCE_EXTRACTION, SOFT, or HARD when the label matches a
   `critical_field_patterns` entry (a value that feeds a calculation: a tare weight, a scaling factor).
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from backend.dispatcher.contract import (
    ExtractionCrop,
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    PageBox,
    ProcessedAsset,
    ProcessedNode,
    SetValue,
    Suggestion,
)
from backend.llm_engine.gemini_types import Image
from backend.llm_engine.vision.schemas import HandwritingKind
from backend.postgres.enums import AssetKind, FlagSeverity, FlagType, NodeSource, NodeType
from backend.routes.a1_office.preflight import image_fields, render_crop
from backend.routes.a1_office.triage import PageDecision

TRANSCRIBED_KINDS = frozenset({HandwritingKind.VALUE, HandwritingKind.CORRECTION, HandwritingKind.NOTE})
LOW_CONFIDENCE = 0.75
LINE_HEIGHT = 0.02  # fraction of the page height, used when the label box is unknown
UNIT_IN_LABEL = re.compile(r"[\(\[]\s*([^\)\]]{1,12})\s*[\)\]]")


@dataclass
class HandwritingResult:
    nodes: list[ProcessedNode]
    assets: list[ProcessedAsset] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    transcribed: int = 0


def region_box(page_no: int, box_2d: list[int]) -> PageBox:
    ymin, xmin, ymax, xmax = box_2d
    return PageBox(page_no=page_no, x0=xmin / 1000, y0=ymin / 1000, x1=xmax / 1000, y1=ymax / 1000)


def nearest_label(region: PageBox, texts: Iterable[ProcessedNode]) -> ProcessedNode | None:
    """Printed text to the left in the same line band, else directly above within two line heights."""
    left, above = [], []
    for node in texts:
        for box in node.bboxes:
            if box.page_no != region.page_no:
                continue
            band = min(box.y1, region.y1) - max(box.y0, region.y0)
            if band > 0 and box.x1 <= region.x0 + 0.01:
                left.append((region.x0 - box.x1, node))
            height = max(box.y1 - box.y0, LINE_HEIGHT)
            gap = region.y0 - box.y1
            if 0 <= gap <= 2 * height and box.x0 < region.x1 and box.x1 > region.x0:
                above.append((gap, node))
    for candidates in (left, above):
        if candidates:
            return min(candidates, key=lambda c: c[0])[1]
    return None


def label_text(node: ProcessedNode | None) -> str | None:
    if node is None:
        return None
    last_line = node.content.strip().splitlines()[-1] if node.content.strip() else ""
    return last_line[-80:] or None


def page_units(texts: Iterable[ProcessedNode], page_no: int) -> list[str]:
    units = []
    for node in texts:
        if node.page_no == page_no:
            units += [u.strip() for u in UNIT_IN_LABEL.findall(node.content)]
    return sorted(set(units))


def render_reading(label: str | None, reading) -> str:
    prefix = f"{label.rstrip(' :')}: " if label else ""
    if reading.illegible or reading.value_raw is None:
        return f"{prefix}[HW illegible]"
    value = (
        reading.value_raw
        if not reading.unit or reading.unit in reading.value_raw
        else f"{reading.value_raw} {reading.unit}"
    )
    return f"{prefix}[HW {value} | conf {reading.confidence:.2f}]"


def transcribe_regions(
    nodes: list[ProcessedNode],
    decisions: list[PageDecision],
    *,
    pdf_bytes: bytes,
    blob_sha256: str,
    vision,
    context: str,
    test_plan_id: str | None,
    doc_id: str | None,
    cloud_allowed: bool,
    critical_field_patterns: Iterable[str],
    put_asset: Callable[[str, bytes], str],
) -> HandwritingResult:
    critical = [re.compile(p, re.IGNORECASE) for p in critical_field_patterns]
    texts = [n for n in nodes if n.node_type == NodeType.CHILD]
    inserted: dict[str, list[ProcessedNode]] = {}
    tail: list[ProcessedNode] = []
    result = HandwritingResult(nodes=[])
    if not cloud_allowed:
        result.nodes = list(nodes)
        return result
    for decision in decisions:
        for index, region in enumerate(decision.handwriting_regions):
            if region.kind not in TRANSCRIBED_KINDS:
                continue
            box = region_box(decision.page_no, region.box_2d)
            label_node = nearest_label(box, texts)
            label = label_text(label_node)
            crop = render_crop(pdf_bytes, box, dpi=300, pad_px=20)
            crop_id = f"p{decision.page_no}_hw{index}"
            uri = put_asset(f"crops/{blob_sha256}/{crop_id}.png", crop)
            asset_ref = f"asset:{crop_id}"
            result.assets.append(
                ProcessedAsset(
                    ref=asset_ref,
                    kind=AssetKind.HANDWRITING_CROP,
                    minio_uri=uri,
                    page_no=box.page_no,
                    bbox=box.model_dump(exclude={"page_no"}),
                    **image_fields(crop),
                )
            )
            reading = vision.transcribe_handwriting(
                Image(crop, "image/png"),
                field_label=label,
                allowed_units=page_units(texts, decision.page_no),
                context=f"{context}" + (f" · {test_plan_id}" if test_plan_id else ""),
                doc_id=doc_id,
                anchor=f"page:{decision.page_no}:",
            ).reading
            result.transcribed += 1
            node = ProcessedNode(
                ref=f"hw/{crop_id}",
                node_type=NodeType.CHILD,
                level=label_node.level if label_node else 1,
                ordinal=0,
                breadcrumb=label_node.breadcrumb if label_node else (texts[0].breadcrumb if texts else ""),
                language=decision.language,
                content=render_reading(label, reading)
                + (" (handwritten correction)" if region.kind == HandwritingKind.CORRECTION else ""),
                page_no=decision.page_no,
                bboxes=[box],
                source=NodeSource.VLM,
                confidence=reading.confidence,
                asset_ref=asset_ref,
                metadata={
                    "handwriting": [
                        {
                            "bbox": box.model_dump(),
                            "label": label,
                            "kind": str(region.kind),
                            "value_raw": reading.value_raw,
                            "value_number": reading.value_number,
                            "unit": reading.unit,
                            "confidence": reading.confidence,
                            "alternatives": reading.alternatives,
                            "illegible": reading.illegible,
                            "notes": reading.notes,
                        }
                    ]
                },
            )
            (inserted.setdefault(label_node.ref, []) if label_node else tail).append(node)
            if reading.illegible or reading.confidence < LOW_CONFIDENCE:
                is_critical = bool(label) and any(p.search(label) for p in critical)
                result.flags.append(
                    Flag(
                        flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
                        severity=FlagSeverity.HARD if is_critical else FlagSeverity.SOFT,
                        anchor=FlagAnchor(page=decision.page_no, bbox=box.model_dump(exclude={"page_no"})),
                        evidence=LowConfidenceEvidence(
                            crops=[
                                ExtractionCrop(
                                    crop_uri=uri,
                                    model_value=reading.value_raw,
                                    alternatives=reading.alternatives,
                                    confidence=reading.confidence,
                                    printed_label=label,
                                )
                            ]
                        ),
                        suggested_resolution=Suggestion(
                            resolution=SetValue(
                                value=reading.value_raw, unit=reading.unit, illegible=reading.illegible
                            ),
                            confidence=reading.confidence,
                            rationale="model reading of the handwritten entry",
                            proposed_by="llm",
                        ),
                    )
                )
    for node in nodes:
        result.nodes.append(node)
        result.nodes.extend(inserted.get(node.ref, []))
    result.nodes.extend(tail)
    result.nodes = [n.model_copy(update={"ordinal": i}) for i, n in enumerate(result.nodes)]
    return result
