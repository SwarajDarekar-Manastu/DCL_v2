"""Route D — hardware inspection photos (file 03 §8): one image → `ProcessedDocument` with one `photo` node.

1. Normalize: HEIC → JPEG (pillow-heif), EXIF orientation applied, EXIF date/camera/lens read. GPS is stripped
   from every derivative and never stored (the test site location is sensitive and not needed).
2. pHash for burst clusters: `cluster_photos` groups photos of one folder taken within 60 s whose pHash
   distance is ≤ 6 (S1's assembler applies it, file 03 §1.3). A member gets its representative's reading
   (`representative=`) and makes no vision call.
3. Classify first (Flash-Lite `classify_image`): exported plots and screenshots go to `digitize_plot`,
   diagrams to `read_schematic`, phone photos of documents to `transcribe_page`, hardware photos to
   `inspect_hardware_photo` with the folder breadcrumb and file name. People/other: catalog only, no
   description and no image vector (prompts never describe people).
4. The node text is the narrative plus the structured list; the structured reading stays in metadata. The
   image vector is computed by `index_document` from the web asset (EmbeddingGemma 2 vision encoder).
5. Assets: 1,600 px web JPEG and 256 px thumbnail (`photos/{sha256}/web.jpg`, `thumb.jpg`) with pHash and
   GPS-free EXIF.
Flags: LOW_CONFIDENCE_EXTRACTION (SOFT) when the top failure-mode confidence is below 0.5 or the model
cannot determine the component; SENSITIVE_CONTENT (HARD) when visible text carries an export-control marking.
"""

import io
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps, ImageStat

from backend.dispatcher.contract import (
    DocumentFields,
    ExtractionCrop,
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    ParseFailureEvidence,
    ProcessedAsset,
    ProcessedDocument,
    ProcessedNode,
    SensitiveEvidence,
)
from backend.dispatcher.folder_context import FolderContext
from backend.llm_engine.gemini_types import Image
from backend.llm_engine.vision.schemas import ImageClass
from backend.postgres.enums import AssetKind, DocKind, FlagSeverity, FlagType, NodeSource, NodeType, Route

PARSER_VERSION = 1
WEB_LONG_SIDE = 1600
THUMB_LONG_SIDE = 256
CLUSTER_MAX_DISTANCE = 6
CLUSTER_MAX_SECONDS = 60
DARK_MEAN_LUMINANCE = 40
LOW_CONFIDENCE = 0.5
GPS_TAG = 0x8825
EXIF_TAGS = {
    0x010F: "make",
    0x0110: "model",
    0x0132: "datetime",
    0x9003: "datetime_original",
    0xA434: "lens_model",
    0x829A: "exposure_time",
    0x829D: "f_number",
    0x8827: "iso",
}
EXPORT_MARKINGS = ("EXPORT CONTROLLED", "ITAR", "RESTRICTED")
KIND_BY_CLASS = {
    ImageClass.HARDWARE_PHOTO: DocKind.HARDWARE_PHOTO,
    ImageClass.PLOT_OR_SCREENSHOT: DocKind.PLOT_FIGURE,
    ImageClass.DIAGRAM: DocKind.DIAGRAM,
    ImageClass.DOCUMENT_SCAN: DocKind.UNKNOWN,
    ImageClass.PEOPLE_OR_OTHER: DocKind.UNKNOWN,
}


@dataclass(frozen=True)
class Normalized:
    image: PILImage.Image
    exif: dict
    taken_at: datetime | None
    phash: str


@dataclass(frozen=True)
class PhotoReading:
    """What a cluster member inherits from its representative."""

    image_class: ImageClass
    content: str
    metadata: dict
    confidence: float | None


def _register_heif() -> None:
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return
    register_heif_opener()


def normalize(data: bytes) -> Normalized:
    """Decode (HEIC included), apply EXIF orientation, read EXIF without GPS, compute the pHash."""
    import imagehash

    _register_heif()
    raw = PILImage.open(io.BytesIO(data))
    exif_raw = raw.getexif()
    exif = {name: str(exif_raw.get(tag)) for tag, name in EXIF_TAGS.items() if exif_raw.get(tag) is not None}
    sub = exif_raw.get_ifd(0x8769) if hasattr(exif_raw, "get_ifd") else {}
    for tag, name in EXIF_TAGS.items():
        if name not in exif and sub.get(tag) is not None:
            exif[name] = str(sub.get(tag))
    taken_at = None
    for key in ("datetime_original", "datetime"):
        if key in exif:
            try:
                taken_at = datetime.strptime(exif[key], "%Y:%m:%d %H:%M:%S")
                break
            except ValueError:
                continue
    image = ImageOps.exif_transpose(raw).convert("RGB")
    return Normalized(image, exif, taken_at, str(imagehash.phash(image)))


def cluster_photos(photos: Sequence[tuple[str, str, datetime | None]]) -> dict[str, str]:
    """`{photo_id: representative_id}` for one folder's photos `(id, phash, taken_at)`; the first photo of a
    burst (by time) represents it. Photos without a time only join on an identical pHash."""
    import imagehash

    ordered = sorted(photos, key=lambda p: (p[2] or datetime.max, p[0]))
    representative: dict[str, str] = {}
    heads: list[tuple[str, imagehash.ImageHash, datetime | None]] = []
    for photo_id, phash, taken_at in ordered:
        value = imagehash.hex_to_hash(phash)
        for head_id, head_hash, head_time in heads:
            close_in_time = (
                taken_at is not None
                and head_time is not None
                and abs((taken_at - head_time).total_seconds()) <= CLUSTER_MAX_SECONDS
            )
            if (value - head_hash) <= CLUSTER_MAX_DISTANCE and (close_in_time or value == head_hash):
                representative[photo_id] = head_id
                break
        else:
            heads.append((photo_id, value, taken_at))
            representative[photo_id] = photo_id
    return representative


def _jpeg(image: PILImage.Image, long_side: int) -> tuple[bytes, int, int]:
    copy = image.copy()
    copy.thumbnail((long_side, long_side))
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=88)  # no exif= argument: derivatives carry no EXIF, so no GPS
    return buffer.getvalue(), copy.width, copy.height


def _for_model(image: PILImage.Image) -> bytes:
    """The image sent to Gemini: web size, auto-contrasted when very dark (file 03 §8 edge cases)."""
    if ImageStat.Stat(image.convert("L")).mean[0] < DARK_MEAN_LUMINANCE:
        image = ImageOps.autocontrast(image, cutoff=1)
    return _jpeg(image, WEB_LONG_SIDE)[0]


def render_photo(reading) -> str:
    lines = [reading.description]
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


def read_photo(
    vision, model_image: bytes, *, context: str, doc_id: str | None
) -> tuple[PhotoReading, list[Flag]]:
    from backend.routes.a1_office.figures import render_plot, render_schematic

    image = Image(model_image, "image/jpeg")
    anchor = "page:1:"
    classified = vision.classify_image(image, folder_context=context, doc_id=doc_id, anchor=anchor).reading
    image_class = classified.image_class
    flags: list[Flag] = []
    base = {"image_class": str(image_class), "classification_confidence": classified.confidence}
    if image_class == ImageClass.HARDWARE_PHOTO:
        reading = vision.inspect_hardware_photo(
            image, folder_context=context, doc_id=doc_id, anchor=anchor
        ).reading
        top = max((m.confidence for m in reading.failure_modes), default=None)
        if (
            top is not None and top < LOW_CONFIDENCE
        ) or "cannot determine component" in reading.description.lower():
            flags.append(
                Flag(
                    flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
                    severity=FlagSeverity.SOFT,
                    anchor=FlagAnchor(page=1),
                    evidence=LowConfidenceEvidence(crops=[ExtractionCrop(crop_uri="photo", confidence=top)]),
                )
            )
        marking = next((m for m in EXPORT_MARKINGS for t in reading.visible_text if m in t.upper()), None)
        if marking:
            flags.append(
                Flag(
                    flag_type=FlagType.SENSITIVE_CONTENT,
                    severity=FlagSeverity.HARD,
                    anchor=FlagAnchor(page=1),
                    evidence=SensitiveEvidence(
                        pattern=marking, redacted_preview=f"visible text {marking!r}", page=1
                    ),
                )
            )
        return PhotoReading(
            image_class,
            render_photo(reading),
            {**base, "structured_reading": reading.model_dump(mode="json")},
            top,
        ), flags
    if image_class == ImageClass.PLOT_OR_SCREENSHOT:
        reading = vision.digitize_plot(
            image, caption=None, context=context, doc_id=doc_id, anchor=anchor
        ).reading
        return PhotoReading(
            image_class,
            render_plot(reading),
            {**base, "structured_reading": reading.model_dump(mode="json")},
            reading.confidence,
        ), flags
    if image_class == ImageClass.DIAGRAM:
        reading = vision.read_schematic(
            image, caption=None, context=context, doc_id=doc_id, anchor=anchor
        ).reading
        return PhotoReading(
            image_class,
            render_schematic(reading),
            {**base, "structured_reading": reading.model_dump(mode="json", by_alias=True)},
            None,
        ), flags
    if image_class == ImageClass.DOCUMENT_SCAN:
        reading = vision.transcribe_page(image, context=context, doc_id=doc_id, anchor=anchor).reading
        return PhotoReading(
            image_class, reading.markdown, {**base, "language": reading.language}, reading.confidence
        ), flags
    return PhotoReading(image_class, "", base, None), flags


def process_photo(
    data: bytes,
    *,
    blob_sha256: str,
    file_name: str,
    folder: FolderContext,
    vision,
    put_asset: Callable[[str, bytes], str],
    cloud_allowed: bool = True,
    doc_id: str | None = None,
    representative: PhotoReading | None = None,
    cluster_id: str | None = None,
) -> tuple[ProcessedDocument, PhotoReading | None]:
    """One photo → document (+ the reading, so the caller can hand it to the burst's other members)."""
    cir_uri = f"s3://dcl-cir/{blob_sha256}/D/v{PARSER_VERSION}/"
    title = Path(file_name).stem.replace("_", " ")
    try:
        normalized = normalize(data)
    except (OSError, ValueError) as exc:
        flag = Flag(
            flag_type=FlagType.PARSE_FAILURE,
            severity=FlagSeverity.HARD,
            evidence=ParseFailureEvidence(
                error=f"undecodable image: {exc}"[:300], magic_bytes_hex=data[:16].hex(), size_bytes=len(data)
            ),
        )
        return ProcessedDocument(
            blob_sha256=blob_sha256,
            route=Route.D,
            parser_version=PARSER_VERSION,
            cir_uri=cir_uri,
            document=DocumentFields(title=title, page_count=0),
            flags=[flag],
        ), None
    web, web_w, web_h = _jpeg(normalized.image, WEB_LONG_SIDE)
    thumb, thumb_w, thumb_h = _jpeg(normalized.image, THUMB_LONG_SIDE)
    assets = [
        ProcessedAsset(
            ref="photo:web",
            kind=AssetKind.PHOTO_WEB,
            minio_uri=put_asset(f"photos/{blob_sha256}/web.jpg", web),
            width=web_w,
            height=web_h,
            bytes=len(web),
            phash=normalized.phash,
            exif=normalized.exif,
        ),
        ProcessedAsset(
            ref="photo:thumb",
            kind=AssetKind.PHOTO_THUMB,
            minio_uri=put_asset(f"photos/{blob_sha256}/thumb.jpg", thumb),
            width=thumb_w,
            height=thumb_h,
            bytes=len(thumb),
            phash=normalized.phash,
            exif=normalized.exif,
        ),
    ]
    context = " / ".join([*folder.breadcrumb, file_name])
    flags: list[Flag] = []
    reading = representative
    if reading is None and cloud_allowed:
        reading, flags = read_photo(vision, _for_model(normalized.image), context=context, doc_id=doc_id)
    nodes: list[ProcessedNode] = []
    image_class = reading.image_class if reading else None
    if reading is not None and image_class != ImageClass.PEOPLE_OR_OTHER and reading.content:
        nodes.append(
            ProcessedNode(
                ref="photo",
                node_type=NodeType.PHOTO,
                ordinal=0,
                breadcrumb=" › ".join([*folder.breadcrumb, title]),
                content=reading.content,
                page_no=1,
                source=NodeSource.VLM,
                confidence=reading.confidence,
                asset_ref="photo:web",
                metadata={
                    **reading.metadata,
                    "cluster_id": cluster_id,
                    "inherited": representative is not None,
                },
            )
        )
    document = DocumentFields(
        title=title,
        doc_kind=KIND_BY_CLASS.get(image_class, DocKind.HARDWARE_PHOTO)
        if image_class
        else DocKind.HARDWARE_PHOTO,
        source_origin=folder.source_origin,
        trust_tier=folder.trust_tier,
        test_plan_id=folder.test_plan_id,
        test_run_id=folder.test_run_id,
        hardware_item=folder.hardware_item,
        doc_date=normalized.taken_at.date() if normalized.taken_at else None,
        date_source="exif" if normalized.taken_at else None,
        page_count=1,
        unit_count=1,
    )
    doc = ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.D,
        parser_version=PARSER_VERSION,
        cir_uri=cir_uri,
        document=document,
        nodes=nodes,
        assets=assets,
        flags=flags,
    )
    return doc, reading


def burst_readings(photos: Iterable[tuple[str, bytes]]) -> dict[str, tuple[str, datetime | None]]:
    """`{id: (phash, taken_at)}` for `cluster_photos`, computed without any model call."""
    out = {}
    for photo_id, data in photos:
        normalized = normalize(data)
        out[photo_id] = (normalized.phash, normalized.taken_at)
    return out
