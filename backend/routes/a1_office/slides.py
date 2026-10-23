"""A1.10 PPTX / PPT / ODP (file 03 §A1.10): one slide node per slide, read from the file itself.

- `.ppt` and `.odp` are converted to `.pptx` by S4's LibreOffice client first; the deck is also converted to
  PDF once for the slide renders (PAGE_RENDER assets, page n = slide n) the viewer and `describe_slide` use.
- A slide node holds the title, the body text with its bullet levels, tables as rows, chart data read from
  the chart XML (categories and series values, no vision call), and the speaker notes. `page_no` is the slide
  number.
- Slides are grouped under parent nodes by the deck's sections (PowerPoint section markers), else every
  SECTION_SIZE slides.
- When pictures, charts, SmartArt or other graphics cover more than GRAPHIC_SHARE of the slide, the slide
  render goes to `describe_slide` (cloud permission needed); the reading becomes a figure node under the
  slide (source vlm). Charts are already structured, so a slide covered only by charts is not described.
- CIR: `slides.json` (every slide as read). Language comes from one `triage_page` call on the first slide
  render; the L1 fields from extract_metadata.
"""

import dataclasses
import io
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

from backend.dispatcher.contract import ProcessedAsset, ProcessedDocument, ProcessedNode
from backend.dispatcher.folder_context import FolderContext
from backend.llm_engine.gemini_types import GeminiError, Image
from backend.postgres.enums import AssetKind, NodeSource, NodeType, Route
from backend.routes.a1_office.metadata import extract_metadata, humanize
from backend.routes.a1_office.preflight import render_page

log = logging.getLogger(__name__)

SECTION_SIZE = 8
GRAPHIC_SHARE = 0.25
RENDER_DPI = 150
P14 = "{http://schemas.microsoft.com/office/powerpoint/2010/main}"


@dataclass
class Slide:
    number: int
    slide_id: int
    title: str = ""
    body: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    charts: list[str] = field(default_factory=list)
    notes: str = ""
    graphic_share: float = 0.0  # pictures, SmartArt and other graphics (charts excluded)

    def text(self) -> str:
        parts = [f"Slide {self.number}: {self.title}".rstrip(": ")]
        parts += self.body
        parts += [f"Table:\n{t}" for t in self.tables]
        parts += [f"Chart: {c}" for c in self.charts]
        if self.notes:
            parts.append(f"Speaker notes: {self.notes}")
        return "\n".join(p for p in parts if p.strip())


def _chart_text(chart) -> str:
    title = chart.chart_title.text_frame.text.strip() if chart.has_title else ""
    lines = [title] if title else []
    for plot in chart.plots:
        categories = [str(c) for c in plot.categories]
        for series in plot.series:
            values = list(series.values)
            pairs = (
                ", ".join(f"{c} = {v}" for c, v in zip(categories, values, strict=False))
                if categories
                else ", ".join(str(v) for v in values)
            )
            lines.append(f"{series.name}: {pairs}")
    return "; ".join(lines)


def _walk(shapes):
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(shape.shapes)
        else:
            yield shape


def _area(shape, width: int, height: int) -> float:
    if shape.width is None or shape.height is None or not width or not height:
        return 0.0
    w = max(0, min(int(shape.left or 0) + int(shape.width), width) - max(int(shape.left or 0), 0))
    h = max(0, min(int(shape.top or 0) + int(shape.height), height) - max(int(shape.top or 0), 0))
    return (w * h) / (width * height)


def _sections(presentation) -> dict[int, str]:
    """slide id → section name from the deck's p14:sectionLst (empty when the deck has no sections)."""
    out: dict[int, str] = {}
    for section in presentation.part._element.iter(f"{P14}section"):
        for slide_ref in section.iter(f"{P14}sldId"):
            out[int(slide_ref.get("id"))] = section.get("name") or ""
    return out


def read_slides(pptx_bytes: bytes) -> tuple[list[Slide], dict[int, str], str | None]:
    """The slides, their section names by slide id, and the deck title from the core properties."""
    deck = Presentation(io.BytesIO(pptx_bytes))
    width, height = int(deck.slide_width or Emu(0)), int(deck.slide_height or Emu(0))
    slides = []
    for number, page in enumerate(deck.slides, start=1):
        slide = Slide(number=number, slide_id=page.slide_id)
        title_shape = page.shapes.title
        slide.title = title_shape.text_frame.text.strip() if title_shape is not None else ""
        share = 0.0
        for shape in _walk(page.shapes):
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            if getattr(shape, "has_chart", False) and shape.has_chart:
                slide.charts.append(_chart_text(shape.chart))
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in shape.table.rows]
                slide.tables.append("\n".join(rows))
                continue
            if shape.has_text_frame and shape.text_frame.text.strip():
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip()
                    if text:
                        slide.body.append(("  " * paragraph.level) + "- " + text)
                continue
            if (
                shape.shape_type in (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.MEDIA)
                or (shape.shape_type in (MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT, MSO_SHAPE_TYPE.LINKED_PICTURE))
                or getattr(shape, "has_smart_art", False)
                or shape.__class__.__name__ == "GraphicFrame"
            ):
                share += _area(shape, width, height)
        slide.graphic_share = min(1.0, share)
        if page.has_notes_slide:
            slide.notes = page.notes_slide.notes_text_frame.text.strip()
        slides.append(slide)
    return slides, _sections(deck), (deck.core_properties.title or None)


def _groups(slides: list[Slide], sections: dict[int, str]) -> list[tuple[str, list[Slide]]]:
    if sections:
        groups: list[tuple[str, list[Slide]]] = []
        for slide in slides:
            name = sections.get(slide.slide_id, "")
            if not groups or groups[-1][0] != name:
                groups.append((name, []))
            groups[-1][1].append(slide)
        return groups
    return [
        (f"Slides {chunk[0].number}–{chunk[-1].number}", chunk)
        for chunk in (slides[i : i + SECTION_SIZE] for i in range(0, len(slides), SECTION_SIZE))
    ]


def process_slides(
    pptx_bytes: bytes,
    pdf_bytes: bytes | None,
    *,
    blob_sha256: str,
    file_name: str,
    folder: FolderContext,
    vision,
    put_asset: Callable[[str, bytes], str],
    put_cir: Callable[[str, bytes], str] | None = None,
    cloud_allowed: bool = True,
    doc_id: str | None = None,
) -> ProcessedDocument:
    slides, sections, core_title = read_slides(pptx_bytes)
    deck_title = core_title or next((s.title for s in slides if s.title), None) or humanize(file_name)
    context = " / ".join([*folder.breadcrumb, file_name])
    nodes: list[ProcessedNode] = []
    assets: list[ProcessedAsset] = []
    renders: dict[int, bytes] = {}
    if pdf_bytes is not None:
        for slide in slides:
            try:
                png = render_page(pdf_bytes, slide.number, dpi=RENDER_DPI)
            except (IndexError, ValueError):
                break  # the PDF has fewer pages than the deck (hidden slides): no render for the rest
            renders[slide.number] = png
            uri = put_asset(f"pages/{blob_sha256}/{slide.number:04d}.png", png)
            assets.append(
                ProcessedAsset(
                    ref=f"page:{slide.number}",
                    kind=AssetKind.PAGE_RENDER,
                    minio_uri=uri,
                    page_no=slide.number,
                )
            )
    language = None
    if cloud_allowed and 1 in renders:
        try:
            language = vision.triage_page(
                Image(renders[1], "image/png"),
                context=f"{context} · slide 1",
                doc_id=doc_id,
                anchor="page:1:",
            ).reading.language
        except GeminiError as exc:
            log.warning("triage of slide 1 of %s failed: %s", file_name, exc)
    for k, (name, members) in enumerate(_groups(slides, sections)):
        section_ref = f"section/{k}"
        crumb = f"{deck_title} › {name}" if name else deck_title
        nodes.append(
            ProcessedNode(
                ref=section_ref,
                node_type=NodeType.PARENT,
                level=1,
                ordinal=len(nodes),
                breadcrumb=deck_title,
                language=language,
                content="\n".join([name or crumb, *(f"Slide {s.number}: {s.title}" for s in members)]),
                page_no=members[0].number,
                page_end=members[-1].number,
                source=NodeSource.PRINTED,
            )
        )
        for slide in members:
            slide_ref = f"slide/{slide.number}"
            nodes.append(
                ProcessedNode(
                    ref=slide_ref,
                    parent_ref=section_ref,
                    node_type=NodeType.SLIDE,
                    level=2,
                    ordinal=len(nodes),
                    breadcrumb=f"{crumb} › Slide {slide.number}"
                    + (f": {slide.title}" if slide.title else ""),
                    language=language,
                    content=slide.text(),
                    page_no=slide.number,
                    source=NodeSource.PRINTED,
                    asset_ref=f"page:{slide.number}" if slide.number in renders else None,
                    metadata={"graphic_share": round(slide.graphic_share, 3), "has_notes": bool(slide.notes)},
                )
            )
            if not (cloud_allowed and slide.graphic_share > GRAPHIC_SHARE and slide.number in renders):
                continue
            try:
                output = vision.describe_slide(
                    Image(renders[slide.number], "image/png"),
                    slide_text=slide.text(),
                    context=context,
                    doc_id=doc_id,
                    anchor=f"page:{slide.number}:",
                )
            except GeminiError as exc:
                log.warning("describe_slide failed on slide %s of %s: %s", slide.number, file_name, exc)
                continue
            reading = output.reading
            described = "\n".join(
                p
                for p in (
                    reading.summary,
                    reading.diagram_description or "",
                    ("Key numbers: " + "; ".join(reading.key_numbers)) if reading.key_numbers else "",
                )
                if p
            )
            nodes.append(
                ProcessedNode(
                    ref=f"{slide_ref}/described",
                    parent_ref=slide_ref,
                    node_type=NodeType.FIGURE,
                    level=3,
                    ordinal=len(nodes),
                    breadcrumb=f"{crumb} › Slide {slide.number} › figure",
                    language=language,
                    content=described,
                    page_no=slide.number,
                    source=NodeSource.VLM,
                    asset_ref=f"page:{slide.number}",
                    metadata={"model": output.model, "prompt_version": output.prompt_version},
                )
            )
    if put_cir is not None:  # CIR: the slides as read, for re-indexing without the file
        put_cir(
            "slides.json", json.dumps([dataclasses.asdict(s) for s in slides], ensure_ascii=False).encode()
        )
    full_text = "\n".join(s.text() for s in slides)
    metadata = extract_metadata(
        file_name=file_name,
        title=deck_title,
        first_page_text=slides[0].text() if slides else "",
        full_text=full_text,
        furniture=[],
        folder=folder,
        page_languages=[language],
        page_count=len(slides),
    )
    from backend.routes.a1_office.route import PARSER_VERSION

    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.A1,
        parser_version=PARSER_VERSION,
        cir_uri=f"s3://dcl-cir/{blob_sha256}/A1/v{PARSER_VERSION}/",
        document=metadata.fields,
        nodes=nodes,
        assets=assets,
        flags=metadata.flags,
    )
