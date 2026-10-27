"""A1.7 handwritten pages (file 03 §A1.7, §A1.8): the entries the page reader was not sure of go to a person.

A page that is a scan or photo of a hand-filled form is read whole by `transcribe_page` (triage `read_whole`),
printed and handwritten text together; nothing is cropped. The reader lists the handwritten entries it is not
sure of (`doubtful`). Each becomes one LOW_CONFIDENCE_EXTRACTION flag on the page, SOFT, or HARD when its
label matches a `critical_field_patterns` entry (a value that feeds a calculation: a tare weight, a scaling
factor), with the page image, the printed label, the reading, its alternatives and a `set_value` suggestion.

The flag is anchored by page and a key made from the label, and the entry is kept under the same key in
`metadata.handwriting` of the page node that holds its text, so a person's value replaces the reading there
on every rebuild (indexing/overlays.py).
"""

import hashlib
import re
from collections import Counter
from collections.abc import Iterable

from backend.dispatcher.contract import (
    ILLEGIBLE,
    ExtractionCrop,
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    ProcessedNode,
    SetValue,
    Suggestion,
)
from backend.llm_engine.vision.schemas import HandwritingDoubt
from backend.postgres.enums import FlagSeverity, FlagType


def doubt_key(page_no: int, label: str | None, occurrence: int) -> str:
    """The anchor of one doubtful entry: the same label on the same page keeps its key across rebuilds."""
    return hashlib.sha256(f"handwriting|{page_no}|{label or ''}|{occurrence}".encode()).hexdigest()[:32]


def page_doubts(
    nodes: list[ProcessedNode],
    page_no: int,
    doubts: list[HandwritingDoubt],
    *,
    page_uri: str,
    critical: Iterable[re.Pattern],
) -> tuple[list[ProcessedNode], list[Flag]]:
    """The page's nodes with each doubtful entry in the metadata of the node holding its text (the first
    node when the text is not found), and one flag per entry."""
    critical = list(critical)
    seen: Counter[str] = Counter()
    entries: dict[int, list[dict]] = {}
    flags = []
    for doubt in doubts:
        label = doubt.field_label
        seen[label or ""] += 1
        key = doubt_key(page_no, label, seen[label or ""])
        text = doubt.value_raw or ILLEGIBLE
        holder = next((i for i, n in enumerate(nodes) if text in n.content), 0)
        entries.setdefault(holder, []).append(
            {
                "key": key,
                "label": label,
                "value_raw": doubt.value_raw,
                "unit": doubt.unit,
                "confidence": doubt.confidence,
                "alternatives": doubt.alternatives,
                "illegible": doubt.illegible,
            }
        )
        is_critical = bool(label) and any(p.search(label) for p in critical)
        flags.append(
            Flag(
                flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
                severity=FlagSeverity.HARD if is_critical else FlagSeverity.SOFT,
                anchor=FlagAnchor(page=page_no, content_sha256=key),
                evidence=LowConfidenceEvidence(
                    crops=[
                        ExtractionCrop(
                            crop_uri=page_uri,
                            model_value=doubt.value_raw,
                            alternatives=doubt.alternatives,
                            confidence=doubt.confidence,
                            printed_label=label,
                        )
                    ]
                ),
                suggested_resolution=Suggestion(
                    resolution=SetValue(value=doubt.value_raw, unit=doubt.unit, illegible=doubt.illegible),
                    confidence=doubt.confidence,
                    rationale="the page reader's reading of the handwritten entry",
                    proposed_by="llm",
                ),
            )
        )
    annotated = [
        node.model_copy(update={"metadata": {**node.metadata, "handwriting": entries[i]}})
        if i in entries
        else node
        for i, node in enumerate(nodes)
    ]
    return annotated, flags
