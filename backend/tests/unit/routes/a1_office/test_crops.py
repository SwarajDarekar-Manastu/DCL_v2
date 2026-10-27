"""Crop geometry (crops.py): the defects found in MinIO on 2026-10-23."""

import io

import pytest
from PIL import Image

from backend.dispatcher.contract import PageBox
from backend.routes.a1_office.crops import (
    SheetItem,
    clip_to_layout,
    contact_sheet,
    is_full_page,
    pad_into_whitespace,
)


def box(x0, y0, x1, y1, page=1):
    return PageBox(page_no=page, x0=x0, y0=y0, x1=x1, y1=y1)


def test_a_figure_that_reaches_into_the_next_column_is_clipped_at_it():
    figure = box(0.05, 0.2, 0.62, 0.5)  # Docling's region bleeds past the column gutter at 0.52
    column = box(0.52, 0.1, 0.95, 0.9)
    clipped = clip_to_layout(figure, [column])
    assert (clipped.x0, clipped.x1) == (0.05, 0.52) and (clipped.y0, clipped.y1) == (0.2, 0.5)


def test_labels_inside_the_figure_and_the_section_around_it_are_not_cut():
    figure = box(0.1, 0.2, 0.6, 0.5)
    label = box(0.2, 0.3, 0.3, 0.32)  # an axis label inside the plot
    section = box(0.0, 0.0, 1.0, 1.0)  # the parent region that holds the figure
    other_page = box(0.0, 0.0, 0.5, 0.5, page=2)
    assert clip_to_layout(figure, [label, section, other_page]) == figure


def test_padding_grows_only_into_whitespace():
    figure = box(0.1, 0.3, 0.6, 0.5)
    caption_above = box(0.1, 0.25, 0.6, 0.295)
    text_right = box(0.605, 0.3, 0.95, 0.5)
    padded = pad_into_whitespace(figure, [caption_above, text_right], 0.01)
    assert padded.y0 == 0.295 and padded.x1 == 0.605  # stopped by the neighbours
    assert padded.x0 == pytest.approx(0.09) and padded.y1 == pytest.approx(0.51)  # full pad into whitespace


def test_a_figure_covering_the_page_is_a_full_page_image():
    assert is_full_page(box(0.02, 0.02, 0.98, 0.97)) and not is_full_page(box(0.1, 0.4, 0.9, 0.7))


def test_contact_sheet_shows_every_crop_with_its_label():
    def png(color):
        out = io.BytesIO()
        Image.new("RGB", (400, 300), color).save(out, format="PNG")
        return out.getvalue()

    items = [SheetItem(png("red"), f"figure · n{i}") for i in range(7)] + [SheetItem(b"broken", "table · t1")]
    sheet = Image.open(io.BytesIO(contact_sheet(items, "brochure.pdf · crops")))
    assert sheet.width == 6 * 230 and sheet.height == 2 * 258 + 30  # 8 crops, 6 per row
    assert sheet.getpixel((5 + 50, 35 + 50)) == (255, 0, 0)  # the first thumbnail
    assert contact_sheet([], "empty") is None
