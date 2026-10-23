"""Crop geometry and quality for A1 (figures, tables, handwriting) and the per-document contact sheet.

- `clip_to_layout`: a figure or table box loses any overlap with another layout item that is not inside it
  (Docling's picture regions sometimes reach into the neighbouring text column; seen on the Moog brochure).
- `pad_into_whitespace`: padding grows each side only up to the nearest other layout item on that side.
- `crop_quality`: a crop must be at least MIN_SIDE_PX on each side at the crop resolution, cover at least
  MIN_AREA_FRACTION of the page and stay under MAX_ASPECT:1; handwriting candidates that fail are dropped and
  counted (ECSS-E-ST-35-06C p. 90 produced 20×60 px slivers of a table cell's border).
- `contact_sheet`: every crop of a document as a thumbnail with its class and node ref, one PNG at
  `qa/{sha256}/crops.png`, so a person judges a document's crops in one image.
- A figure covering FULL_PAGE_FRACTION of the page is a `full_page_image` (S5's M5 check).
"""

import io
from collections.abc import Iterable
from dataclasses import dataclass

from backend.dispatcher.contract import PageBox

CROP_DPI = 200  # stored crops: Pillow from layout boxes at 150–200 dpi (DECISIONS 2026-10-23)
MIN_SIDE_PX = 48  # measured at GATE_DPI: 48 px at 300 dpi ≈ 11.5 pt, a small handwritten digit
GATE_DPI = 300
MIN_AREA_FRACTION = 0.003
MAX_ASPECT = 12.0
CONTAINED = 0.8  # share of another item's area inside the box for it to count as part of the figure
FULL_PAGE_FRACTION = 0.85
THUMB_PX = 220
LABEL_PX = 28
COLUMNS = 6


def _area(box: PageBox) -> float:
    return max(0.0, box.x1 - box.x0) * max(0.0, box.y1 - box.y0)


def _overlap(a: PageBox, b: PageBox) -> tuple[float, float, float, float] | None:
    x0, y0, x1, y1 = max(a.x0, b.x0), max(a.y0, b.y0), min(a.x1, b.x1), min(a.y1, b.y1)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _with(box: PageBox, **changes) -> PageBox:
    return PageBox(**{**box.model_dump(), **changes})


def clip_to_layout(box: PageBox, others: Iterable[PageBox]) -> PageBox:
    """Cut away every overlap with a layout item that mostly lies outside the box, keeping the most area."""
    for other in others:
        if other.page_no != box.page_no or _overlap(box, other) is None:
            continue
        inside = _overlap(box, other)
        inside_area = (inside[2] - inside[0]) * (inside[3] - inside[1])
        if _area(other) and inside_area / _area(other) >= CONTAINED:
            continue  # a label or caption inside the figure belongs to it
        if _area(box) and inside_area / _area(box) >= CONTAINED:
            continue  # a section or page region that holds the figure is not a neighbour
        cuts = [
            _with(box, x1=other.x0) if other.x0 > box.x0 else None,
            _with(box, x0=other.x1) if other.x1 < box.x1 else None,
            _with(box, y1=other.y0) if other.y0 > box.y0 else None,
            _with(box, y0=other.y1) if other.y1 < box.y1 else None,
        ]
        cuts = [c for c in cuts if c is not None and _area(c) > 0]
        if cuts:
            box = max(cuts, key=_area)
    return box


def pad_into_whitespace(box: PageBox, others: Iterable[PageBox], pad: float) -> PageBox:
    """Grow each side by up to `pad` (page fraction), never into another layout item."""
    near = [o for o in others if o.page_no == box.page_no and _overlap(box, o) is None]
    left, top, right, bottom = box.x0 - pad, box.y0 - pad, box.x1 + pad, box.y1 + pad
    for o in near:
        vertical_band = o.y1 > box.y0 and o.y0 < box.y1
        horizontal_band = o.x1 > box.x0 and o.x0 < box.x1
        if vertical_band and o.x1 <= box.x0:
            left = max(left, o.x1)
        if vertical_band and o.x0 >= box.x1:
            right = min(right, o.x0)
        if horizontal_band and o.y1 <= box.y0:
            top = max(top, o.y1)
        if horizontal_band and o.y0 >= box.y1:
            bottom = min(bottom, o.y0)
    clamp = lambda v: min(1.0, max(0.0, v))  # noqa: E731
    return _with(box, x0=clamp(left), y0=clamp(top), x1=clamp(right), y1=clamp(bottom))


@dataclass(frozen=True)
class Quality:
    ok: bool
    reason: str | None = None


def crop_quality(box: PageBox, page_size_pt: tuple[float, float], dpi: int = GATE_DPI) -> Quality:
    width_px = (box.x1 - box.x0) * page_size_pt[0] * dpi / 72
    height_px = (box.y1 - box.y0) * page_size_pt[1] * dpi / 72
    if min(width_px, height_px) < MIN_SIDE_PX:
        return Quality(False, f"side {min(width_px, height_px):.0f} px < {MIN_SIDE_PX} px")
    if _area(box) < MIN_AREA_FRACTION - 1e-9:
        return Quality(False, f"area {_area(box) * 100:.2f} % of the page < {MIN_AREA_FRACTION * 100:.1f} %")
    aspect = max(width_px, height_px) / min(width_px, height_px)
    if aspect >= MAX_ASPECT:
        return Quality(False, f"aspect {aspect:.0f}:1 ≥ {MAX_ASPECT:.0f}:1")
    return Quality(True)


def inside_any(box: PageBox, containers: Iterable[PageBox], share: float = 0.5) -> bool:
    """True when at least `share` of the box lies inside one of the containers (a table cell region)."""
    for container in containers:
        if container.page_no != box.page_no:
            continue
        overlap = _overlap(box, container)
        if (
            overlap
            and _area(box)
            and (overlap[2] - overlap[0]) * (overlap[3] - overlap[1]) / _area(box) >= share
        ):
            return True
    return False


def is_full_page(box: PageBox) -> bool:
    return _area(box) >= FULL_PAGE_FRACTION


@dataclass(frozen=True)
class SheetItem:
    png: bytes
    label: str  # "<class> · <node ref>"


def contact_sheet(items: list[SheetItem], title: str) -> bytes | None:
    """One PNG with every crop as a thumbnail and its label; None when the document has no crop."""
    if not items:
        return None
    from PIL import Image, ImageDraw

    rows = (len(items) + COLUMNS - 1) // COLUMNS
    cell_w, cell_h = THUMB_PX + 10, THUMB_PX + LABEL_PX + 10
    sheet = Image.new("RGB", (COLUMNS * cell_w, rows * cell_h + 30), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), title[:160], fill="black")
    for i, item in enumerate(items):
        x, y = (i % COLUMNS) * cell_w + 5, (i // COLUMNS) * cell_h + 35
        try:
            thumb = Image.open(io.BytesIO(item.png)).convert("RGB")
            thumb.thumbnail((THUMB_PX, THUMB_PX))
        except Exception:  # noqa: BLE001 — an unreadable crop shows as a grey box with its label
            thumb = Image.new("RGB", (THUMB_PX, THUMB_PX), "#cccccc")
        sheet.paste(thumb, (x, y))
        draw.rectangle((x - 1, y - 1, x + thumb.width, y + thumb.height), outline="#888888")
        draw.text((x, y + THUMB_PX + 4), item.label[:40], fill="black")
    out = io.BytesIO()
    sheet.save(out, format="PNG", optimize=True)
    return out.getvalue()
