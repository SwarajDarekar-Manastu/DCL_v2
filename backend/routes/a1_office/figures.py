"""A1.6 figures (file 03 §A1.6): classify, then read each figure with the matching VisionService call.

Docling's picture classifier labels each figure. Charts go to `digitize_plot`, engineering drawings and flow
charts to `read_schematic`, photographs to `inspect_hardware_photo` (Route D schema, asset kind
`photo_in_doc`), table images to `read_table_image` (they become `table` nodes). Logos, icons, signatures,
stamps and codes are skipped (kept in the CIR only). Maps, screenshots and other images keep their caption.
The node text is the structured reading rendered as text, plus the caption and the body sentences that
refer to the figure ("Figure 4 shows…"); the reading itself stays in `metadata.structured_reading`. Every
figure crop is an asset (`figures/{sha256}/{figure_id}.png`) so the viewer shows the original next to it.
The crop is Docling's region clipped against the page's other layout items and padded only into whitespace
(crops.py); a figure covering the page is `class = full_page_image` (its picture class stays in
`picture_class` and decides the reading).
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.dispatcher.contract import (
    ExtractionCrop,
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    ProcessedAsset,
    ProcessedNode,
)
from backend.llm_engine.gemini_types import Image, StructuredOutputError
from backend.llm_engine.vision.schemas import DrawingKind, PhotoKind
from backend.postgres.enums import AssetKind, FlagSeverity, FlagType, NodeSource, NodeType
from backend.routes.a1_office.assets import image_fields
from backend.routes.a1_office.crops import (
    CROP_DPI,
    SheetItem,
    clip_to_layout,
    is_full_page,
    pad_into_whitespace,
)

log = logging.getLogger(__name__)

PLOT_CLASSES = frozenset({"bar_chart", "box_plot", "line_chart", "pie_chart", "scatter_plot"})
SCHEMATIC_CLASSES = frozenset({"engineering_drawing", "flow_chart"})
PHOTO_CLASSES = frozenset({"photograph"})
TABLE_CLASSES = frozenset({"table"})
SKIP_CLASSES = frozenset(
    {
        "logo",
        "icon",
        "signature",
        "stamp",
        "bar_code",
        "qr_code",
        "music",
        "crossword_puzzle",
        "calendar",
        "page_thumbnail",
    }
)
FIGURE_NUMBER = re.compile(r"\b(?:fig(?:ure)?|abb(?:ildung)?|図)\.?\s*(\d+)", re.IGNORECASE)
LOW_PHOTO_CONFIDENCE = 0.5
# No padding: Docling regions are tight, and section headings carry no box to stop a pad (Moog fig18).
CROP_PAD = 0.0


@dataclass
class FigureResult:
    nodes: list[ProcessedNode]
    assets: list[ProcessedAsset] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    crops: list[SheetItem] = field(default_factory=list)


def figure_about(context: str, node: ProcessedNode, texts: list[ProcessedNode]) -> str:
    """Where a figure sits in its document, for the model (plan step D2): the file, the page, the section
    heading Docling put it under, and the body sentences that cite it ("Figure 4 shows ...")."""
    parts = [context]
    if node.page_no:
        parts.append(f"page {node.page_no}")
    section = node.breadcrumb.split(" › ", 1)[1] if " › " in (node.breadcrumb or "") else None
    if section:
        parts.append(f"section: {section}")
    cited = _referencing_sentences(node.metadata.get("caption"), texts)
    if cited:
        parts.append("the text says: " + " ".join(cited))
    return " · ".join(parts)


def _referencing_sentences(caption: str | None, texts: list[ProcessedNode]) -> list[str]:
    number = FIGURE_NUMBER.search(caption or "")
    if not number:
        return []
    pattern = re.compile(rf"\b(?:fig(?:ure)?|abb(?:ildung)?)\.?\s*{number.group(1)}\b", re.IGNORECASE)
    found = []
    for node in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", node.content):
            if pattern.search(sentence) and sentence not in found:
                found.append(sentence.strip())
    return found[:3]


def _axis(name: str, axis) -> str:
    return f"{name}: {axis.label or '?'} [{axis.unit or '-'}] {axis.range or ''}".rstrip() + (
        " (log scale)" if axis.log_scale else ""
    )


def render_plot(reading) -> str:
    lines = [f"Plot ({reading.plot_type}). " + _axis("x axis", reading.x_axis)]
    lines += [_axis("y axis", axis) for axis in reading.y_axes]
    for series in reading.series:
        points = "; ".join(f"({p.x}, {p.y})" for p in series.key_points)
        panel = f" [panel {series.panel}]" if series.panel else ""
        lines.append(
            f"Series {series.name or ''}{panel}: {points}" + (f" — {series.trend}" if series.trend else "")
        )
    lines += [f"Annotation: {a}" for a in reading.annotations]
    return "\n".join(lines)


def render_schematic(reading) -> str:
    if reading.drawing_kind == DrawingKind.FLOWCHART:
        lines = ["Flowchart steps: " + "; ".join(reading.steps)]
    else:
        kind = (
            "Mechanical drawing parts"
            if reading.drawing_kind == DrawingKind.MECHANICAL
            else "Schematic components"
        )
        lines = [f"{kind}: " + "; ".join(f"{c.tag or c.label or '?'} ({c.type})" for c in reading.components)]
    lines += [
        f"{c.source} → {c.target}"
        + (f" [{c.medium}]" if c.medium else "")
        + (f" {c.label}" if c.label else "")
        for c in reading.connections
    ]
    if reading.notes:
        lines.append(f"Notes: {reading.notes}")
    return "\n".join(lines)


def render_photo(reading) -> str:
    """A photo's node text, for Route D photos and photos inside documents alike."""
    lines = [f"Photo ({str(reading.photo_kind).replace('_', ' ')}): {reading.description}"]
    if reading.readings:
        lines.append("Readings: " + ", ".join(reading.readings))
    if reading.components_visible:
        lines.append("Components visible: " + ", ".join(reading.components_visible))
    for mode in reading.failure_modes:
        lines.append(
            f"Failure mode: {mode.mode} at {mode.location or '?'} ({mode.severity or '?'}, "
            f"confidence {mode.confidence:.2f})"
        )
    if reading.visible_text:
        lines.append("Visible text: " + ", ".join(reading.visible_text))
    lines.append(f"Test stage: {reading.test_stage_hint}")
    return "\n".join(lines)


def _readable(read: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """A vision reading, or None when the model's reply does not fit the reading's schema: that figure keeps
    its caption and citing sentences and is flagged, the document goes on (one unusable chart failed a whole
    400-page datasheet, 2026-10-26). Transient gateway errors still raise and retry the task."""
    try:
        return read(*args, **kwargs)
    except StructuredOutputError as exc:
        log.warning("figure reading unusable, kept with its caption: %s", exc)
        return None


def read_figures(
    nodes: list[ProcessedNode],
    *,
    pdf_bytes: bytes,
    blob_sha256: str,
    vision,
    context: str,
    doc_id: str | None,
    cloud_allowed: bool,
    put_asset: Callable[[str, bytes], str],
) -> FigureResult:
    """Replace every figure placeholder by its reading (or drop it when it is decoration)."""
    texts = [n for n in nodes if n.node_type == NodeType.CHILD]
    layout = [(n.ref, b) for n in nodes for b in n.bboxes]
    out: list[ProcessedNode] = []
    result = FigureResult(nodes=out)
    for node in nodes:
        if node.node_type != NodeType.FIGURE:
            out.append(node)
            continue
        figure_class = node.metadata.get("picture_class") or node.metadata.get("class") or "other"
        if figure_class in SKIP_CLASSES:
            result.skipped.append(node.ref)
            continue
        box = node.bboxes[0] if node.bboxes else None
        caption = node.metadata.get("caption")
        asset_ref = None
        crop = None
        if box is not None and is_full_page(box):
            node = node.model_copy(
                update={
                    "metadata": {**node.metadata, "class": "full_page_image", "picture_class": figure_class}
                }
            )
        if box is not None:
            from backend.routes.a1_office.preflight import render_crop  # PDF stack: not in the media image

            others = [b for ref, b in layout if ref != node.ref]
            box = pad_into_whitespace(clip_to_layout(box, others), others, CROP_PAD)
            crop = render_crop(pdf_bytes, box, dpi=CROP_DPI, pad_px=0)
            result.crops.append(SheetItem(crop, f"{node.metadata.get('class') or figure_class} · {node.ref}"))
            kind = AssetKind.PHOTO_IN_DOC if figure_class in PHOTO_CLASSES else AssetKind.FIGURE_CROP
            uri = put_asset(f"figures/{blob_sha256}/{node.ref}.png", crop)
            asset_ref = f"asset:{node.ref}"
            result.assets.append(
                ProcessedAsset(
                    ref=asset_ref,
                    kind=kind,
                    minio_uri=uri,
                    page_no=box.page_no,
                    bbox=box.model_dump(exclude={"page_no"}),
                    **image_fields(crop),
                )
            )
        reading, rendered, capability = None, None, None
        if cloud_allowed and crop is not None:
            image = Image(crop, "image/png")
            anchor = f"page:{node.page_no}:" if node.page_no else None
            about = figure_about(context, node, texts)  # page, section, the sentences citing it (step D2)
            figure_context = f"{about} · {caption or 'no caption'}"
            if figure_class in PLOT_CLASSES:
                capability = "digitize_plot"
                output = _readable(
                    vision.digitize_plot,
                    image,
                    caption=caption,
                    context=about,
                    doc_id=doc_id,
                    anchor=anchor,
                )
                if output is not None:
                    reading, rendered = output.reading, render_plot(output.reading)
            elif figure_class in SCHEMATIC_CLASSES:
                capability = "read_schematic"
                output = _readable(
                    vision.read_schematic,
                    image,
                    caption=caption,
                    context=about,
                    doc_id=doc_id,
                    anchor=anchor,
                )
                if output is not None:
                    reading, rendered = output.reading, render_schematic(output.reading)
            elif figure_class in PHOTO_CLASSES:
                capability = "inspect_hardware_photo"
                output = _readable(
                    vision.inspect_hardware_photo,
                    image,
                    folder_context=figure_context,
                    doc_id=doc_id,
                    anchor=anchor,
                )
                reading, rendered = (output.reading, render_photo(output.reading)) if output else (None, None)
                top = max((m.confidence for m in reading.failure_modes), default=None) if reading else None
                if (
                    reading is not None
                    and reading.photo_kind
                    == PhotoKind.INSPECTION  # a product picture has no damage to confirm
                    and (
                        (top is not None and top < LOW_PHOTO_CONFIDENCE)
                        or "cannot determine component" in reading.description.lower()
                    )
                ):
                    result.flags.append(
                        Flag(
                            flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
                            severity=FlagSeverity.SOFT,
                            anchor=FlagAnchor(page=node.page_no, bbox=box.model_dump(exclude={"page_no"})),
                            evidence=LowConfidenceEvidence(
                                crops=[ExtractionCrop(crop_uri=uri, confidence=top)]
                            ),
                        )
                    )
            elif figure_class in TABLE_CLASSES and (
                output := _readable(
                    vision.read_table_image,
                    image,
                    caption=caption,
                    context=about,
                    doc_id=doc_id,
                    anchor=anchor,
                )
            ):
                capability = "read_table_image"
                table = output.reading
                out.append(
                    node.model_copy(
                        update={
                            "node_type": NodeType.TABLE,
                            "content": table.html_table,
                            "source": NodeSource.VLM,
                            "confidence": table.confidence,
                            "asset_ref": asset_ref,
                            "metadata": {
                                **node.metadata,
                                "n_rows": table.n_rows,
                                "n_cols": table.n_cols,
                                "units_by_column": table.units_by_column,
                                "from_image": True,
                            },
                        }
                    )
                )
                continue
        if (
            cloud_allowed
            and crop is not None
            and reading is None
            and figure_class in PLOT_CLASSES | SCHEMATIC_CLASSES | PHOTO_CLASSES | TABLE_CLASSES
        ):  # the model's reading was unusable: the crop is kept for a person to read
            result.flags.append(
                Flag(
                    flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
                    severity=FlagSeverity.SOFT,
                    anchor=FlagAnchor(page=node.page_no, bbox=box.model_dump(exclude={"page_no"})),
                    evidence=LowConfidenceEvidence(crops=[ExtractionCrop(crop_uri=uri, confidence=None)]),
                )
            )
        parts = [
            p
            for p in (
                rendered,
                f"Caption: {caption}" if caption else None,
                *_referencing_sentences(caption, texts),
            )
            if p
        ]
        confidence = getattr(reading, "confidence", None)
        if confidence is None and reading is not None and getattr(reading, "failure_modes", None):
            confidence = max(m.confidence for m in reading.failure_modes)
        out.append(
            node.model_copy(
                update={
                    "content": "\n".join(parts) or (caption or ""),
                    "source": NodeSource.VLM if reading is not None else node.source,
                    "confidence": confidence,
                    "asset_ref": asset_ref,
                    "metadata": {
                        **node.metadata,
                        "capability": capability,
                        "structured_reading": reading.model_dump(mode="json", by_alias=True)
                        if reading
                        else None,
                    },
                }
            )
        )
    return result
