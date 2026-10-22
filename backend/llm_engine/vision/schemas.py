"""Structured-output schemas of the shared vision sub-pipeline (file 03 §3).

Each model is sent to Gemini as the response schema and validates the reply. Boxes are Gemini's
`box_2d` = [ymin, xmin, ymax, xmax] normalized 0–1000 (top-left origin). Any number a vision call returns
is data with a confidence, never merged silently into printed text (file 03 §3 rule 3).
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Box2D = Annotated[list[int], Field(min_length=4, max_length=4)]


def check_box(box: list[int]) -> list[int]:
    ymin, xmin, ymax, xmax = box
    if not all(0 <= v <= 1000 for v in box) or ymin > ymax or xmin > xmax:
        raise ValueError(f"box_2d must be [ymin, xmin, ymax, xmax] within 0..1000, got {box}")
    return box


class Reading(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PageType(StrEnum):
    DIGITAL_TEXT = "digital_text"
    DIGITAL_WITH_FIGURES = "digital_with_figures"
    TABLE_DENSE = "table_dense"
    SCANNED_PRINTED = "scanned_printed"
    SCANNED_FORM_WITH_HANDWRITING = "scanned_form_with_handwriting"
    HANDWRITTEN_NOTES = "handwritten_notes"
    DRAWING_SCHEMATIC = "drawing_schematic"
    PHOTO_PAGE = "photo_page"
    BLANK_OR_SEPARATOR = "blank_or_separator"


class Script(StrEnum):
    LATIN = "latin"
    CYRILLIC = "cyrillic"
    DEVANAGARI = "devanagari"
    ARABIC = "arabic"
    CJK = "cjk"
    MIXED = "mixed"


class HandwritingKind(StrEnum):
    VALUE = "value"
    CORRECTION = "correction"
    NOTE = "note"
    CHECKBOX = "checkbox"
    SIGNATURE = "signature"


class HandwritingRegion(Reading):
    box_2d: Box2D
    kind: HandwritingKind

    @field_validator("box_2d")
    @classmethod
    def _box(cls, value: list[int]) -> list[int]:
        return check_box(value)


class PageTriage(Reading):
    """`triage_page` (Flash-Lite, page thumbnail): decides what each page costs (file 03 §A1.2)."""

    page_type: PageType
    has_handwriting: bool
    has_tables: bool
    has_figures: bool
    is_rotated: bool
    language: str = Field(description="BCP-47 tag of the main language on the page, e.g. en, de, ja")
    script: Script
    handwriting_regions: list[HandwritingRegion] = Field(default_factory=list)


class PageTranscription(Reading):
    """`transcribe_page` (3.8 Flash, high resolution): whole page when OCR stays below threshold."""

    markdown: str
    language: str
    confidence: Confidence
    illegible_regions: list[Box2D] = Field(default_factory=list)
    furniture: list[str] = Field(
        default_factory=list, description="printed headers, footers and margin identifiers, top first (v2)"
    )

    @field_validator("illegible_regions")
    @classmethod
    def _boxes(cls, value: list[list[int]]) -> list[list[int]]:
        return [check_box(box) for box in value]


class HandwritingReading(Reading):
    """`transcribe_handwriting` (3.8 Flash, high resolution, one crop).

    Never a guessed digit: an illegible reading carries no value, and a value_number must be exactly what
    value_raw says (locale decimal comma allowed); otherwise the number is dropped and only the raw text kept.
    """

    field_label: str | None
    value_raw: str | None
    value_number: float | None
    unit: str | None
    confidence: Confidence
    alternatives: list[str] = Field(default_factory=list)
    illegible: bool
    notes: str | None = None

    @model_validator(mode="after")
    def _no_guessed_digits(self) -> "HandwritingReading":
        if self.illegible:
            self.value_raw = None
            self.value_number = None
            self.confidence = min(self.confidence, 0.5)
        elif self.value_number is not None and not _raw_states_number(self.value_raw, self.value_number):
            self.value_number = None
        return self


def _raw_states_number(raw: str | None, number: float) -> bool:
    if not raw:
        return False
    digits = "".join(ch for ch in raw if ch.isdigit() or ch in ".,-")
    for candidate in (digits, digits.replace(",", "."), digits.replace(",", "")):
        try:
            if float(candidate) == number:
                return True
        except ValueError:
            continue
    return False


class TableReading(Reading):
    """`read_table_image` (3.8 Flash, table crop): HTML with spans, units per column."""

    html_table: str
    n_rows: int = Field(ge=0)
    n_cols: int = Field(ge=0)
    header_rows: int = Field(ge=0)
    units_by_column: list[str | None] = Field(default_factory=list)
    confidence: Confidence


class Axis(Reading):
    label: str | None
    unit: str | None
    range: list[float] = Field(default_factory=list, max_length=2)


class PlotPoint(Reading):
    x: float | str = Field(description="number on a numeric axis, category label on a bar chart")
    y: float


class PlotSeries(Reading):
    name: str | None
    key_points: list[PlotPoint] = Field(default_factory=list)
    trend: str | None = None


class PlotReading(Reading):
    """`digitize_plot` (3.8 Flash, figure crop + caption): key points, never a dense trace."""

    plot_type: str
    x_axis: Axis
    y_axes: list[Axis] = Field(default_factory=list)
    series: list[PlotSeries] = Field(default_factory=list)
    annotations: list[str] = Field(default_factory=list)
    confidence: Confidence


class SchematicComponent(Reading):
    tag: str | None
    type: str
    label: str | None = None


class SchematicConnection(Reading):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source: str = Field(alias="from")
    target: str = Field(alias="to")
    medium: str | None = None
    label: str | None = None


class SchematicReading(Reading):
    """`read_schematic` (3.8 Flash, figure crop): components and connections."""

    components: list[SchematicComponent] = Field(default_factory=list)
    connections: list[SchematicConnection] = Field(default_factory=list)
    notes: str | None = None


class FailureMode(Reading):
    mode: str
    location: str | None
    severity: str | None
    confidence: Confidence


class TestStage(StrEnum):
    PRE_TEST = "pre_test"
    POST_TEST = "post_test"
    DISASSEMBLY = "disassembly"
    UNKNOWN = "unknown"


class ImageClass(StrEnum):
    HARDWARE_PHOTO = "hardware_photo"
    PLOT_OR_SCREENSHOT = "plot_or_screenshot"
    DOCUMENT_SCAN = "document_scan"
    DIAGRAM = "diagram"
    PEOPLE_OR_OTHER = "people_or_other"


class ImageClassification(Reading):
    """`classify_image` (Flash-Lite, low resolution): Route D's first step (file 03 §8 step 3)."""

    image_class: ImageClass
    confidence: Confidence
    shows_people: bool


class HardwarePhotoReading(Reading):
    """`inspect_hardware_photo` (3.8 Flash, medium resolution, photo and folder context), no people."""

    components_visible: list[str] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    visible_text: list[str] = Field(default_factory=list)
    test_stage_hint: TestStage
    description: str


class SlideReading(Reading):
    """`describe_slide` (3.8 Flash, slide image + extracted text)."""

    summary: str
    diagram_description: str | None = None
    key_numbers: list[str] = Field(default_factory=list)


class VideoEvent(Reading):
    t_s: float = Field(ge=0.0)
    type: str
    description: str


class VideoTimeline(Reading):
    """`video_timeline` (3.8 Flash, timestamped keyframes of a test-cell clip)."""

    events: list[VideoEvent] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
