"""Gold data for S2's document-model comparison study (DECISIONS.md 2026-10-23): schema and loader.

The gold itself is local only, under the git-ignored ``data/gold/`` (it carries company pages and readings):

- ``layout.json``: about 30 real pages with region boxes by class (layout models: precision/recall per class)
- ``tables.json``: cell-level truth for hard tables (merged headers, borderless, rotated pages, photos)
- ``equations.json``: LaTeX truth; ``truth_source = tex`` when the ``.tex`` twin exists, else an S5
  transcription
- ``handwriting.json``: S5's readings of handwritten regions, with a confidence

Boxes are ``[x0, y0, x1, y1]`` normalised to the rendered page (rotation applied), origin top-left. ``source``
is the file path under ``data/samples/``.

    from backend.tests.benchmark.gold.gold import load_gold
    gold = load_gold()            # data/gold/ of this checkout, or load_gold(Path(...))
"""

from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "data" / "gold"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegionClass(StrEnum):
    TEXT = "text"
    TITLE = "title"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    EQUATION = "equation"
    CAPTION = "caption"
    HANDWRITING = "handwriting"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"


Box = tuple[float, float, float, float]


def _check_box(box: Box) -> Box:
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError(f"box {box} is not normalised [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
    return box


class _Located(_Model):
    page_id: str
    source: str = Field(description="path under data/samples/")
    page_no: int = Field(ge=1)
    bbox: Box

    @model_validator(mode="after")
    def _box(self) -> Self:
        _check_box(self.bbox)
        return self


class Region(_Model):
    class_: RegionClass = Field(alias="class")
    bbox: Box
    text: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _box(self) -> Self:
        _check_box(self.bbox)
        return self


class GoldPage(_Model):
    page_id: str
    source: str
    page_no: int = Field(ge=1)
    kind: str = Field(
        description="e.g. digital_latex_report, digital_standard_landscape, phone_photo_of_printed_form"
    )
    regions: list[Region] = Field(min_length=1)


class Cell(_Model):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    text: str
    header: bool = False


class GoldTable(_Located):
    table_id: str
    tags: list[str] = Field(
        description="borderless, merged_header, rotated_page, rotated_text_cells, phone_photo, …"
    )
    header_rows: int | None = None
    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    cells: list[Cell]

    @model_validator(mode="after")
    def _grid(self) -> Self:
        """Every grid slot is covered by exactly one cell."""
        covered: dict[tuple[int, int], tuple[int, int]] = {}
        for cell in self.cells:
            if cell.row + cell.row_span > self.n_rows or cell.col + cell.col_span > self.n_cols:
                raise ValueError(
                    f"{self.table_id}: r{cell.row}c{cell.col} leaves the {self.n_rows}x{self.n_cols} grid"
                )
            for r in range(cell.row, cell.row + cell.row_span):
                for c in range(cell.col, cell.col + cell.col_span):
                    if (r, c) in covered:
                        raise ValueError(f"{self.table_id}: slot r{r}c{c} covered twice")
                    covered[(r, c)] = (cell.row, cell.col)
        if len(covered) != self.n_rows * self.n_cols:
            raise ValueError(
                f"{self.table_id}: {self.n_rows * self.n_cols - len(covered)} grid slots not covered"
            )
        return self


class GoldEquation(_Located):
    eq_id: str
    latex: str = Field(min_length=1)
    truth_source: Literal["tex", "transcription"]
    tex_file: str | None = Field(
        default=None, description="path under data/samples/ when truth_source is tex"
    )
    tex_line: int | None = None
    number: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _tex(self) -> Self:
        if self.truth_source == "tex" and not self.tex_file:
            raise ValueError(f"{self.eq_id}: a tex truth names its tex_file")
        return self


class HandwritingReading(_Located):
    reading_id: str
    text: str = Field(min_length=1, description="' / ' separates lines or rows, ' | ' separates columns")
    confidence: Literal["clear", "ambiguous"]
    note: str | None = None


class Gold(_Model):
    pages: list[GoldPage]
    tables: list[GoldTable]
    equations: list[GoldEquation]
    handwriting: list[HandwritingReading]

    @model_validator(mode="after")
    def _references(self) -> Self:
        pages = {p.page_id: p for p in self.pages}
        if len(pages) != len(self.pages):
            raise ValueError("duplicate page_id")
        for item in [*self.tables, *self.equations, *self.handwriting]:
            page = pages.get(item.page_id)
            if page is None or (page.source, page.page_no) != (item.source, item.page_no):
                raise ValueError(f"{item.page_id}: not a gold page with that source and page number")
        return self

    def page(self, page_id: str) -> GoldPage:
        return next(p for p in self.pages if p.page_id == page_id)


def load_gold(root: Path = DEFAULT_ROOT) -> Gold:
    """Read and validate the four gold files under ``root`` (missing files count as empty, except layout)."""
    import json

    def read(name: str, key: str) -> list:
        path = root / name
        return json.loads(path.read_text(encoding="utf-8"))[key] if path.is_file() else []

    if not (root / "layout.json").is_file():
        raise FileNotFoundError(
            f"{root / 'layout.json'} (the gold is local only; see DECISIONS.md 2026-10-23)"
        )
    return Gold(
        pages=read("layout.json", "pages"),
        tables=read("tables.json", "tables"),
        equations=read("equations.json", "equations"),
        handwriting=read("handwriting.json", "readings"),
    )
