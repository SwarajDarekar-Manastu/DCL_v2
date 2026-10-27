"""Structured-output schemas of the shared vision sub-pipeline (file 03 §3).

Each model is sent to Gemini as the response schema and validates the reply. Any number a vision call returns
is data with a confidence, never merged silently into printed text (file 03 §3 rule 3).
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Reading(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ImageMetadata(Reading):
    """What an image is, from the image and from its file's ingestion metadata (prompt image_context);
    returned by the capabilities that describe an image and kept with the image's node."""

    subject: str
    setting: str
    hardware: list[str] = []
    test_context: str | None = None
    from_metadata: str | None = None


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


class PageTriage(Reading):
    """`triage_page` (Flash-Lite, page thumbnail): decides what each page costs (file 03 §A1.2)."""

    page_type: PageType
    has_figures: bool
    is_rotated: bool
    language: str = Field(description="BCP-47 tag of the main language on the page, e.g. en, de, ja")
    script: Script


class HandwritingDoubt(Reading):
    """A handwritten entry the page reader is not sure of. An illegible entry carries no value."""

    field_label: str | None
    value_raw: str | None
    unit: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    confidence: Confidence
    illegible: bool

    @model_validator(mode="after")
    def _no_value_when_illegible(self) -> "HandwritingDoubt":
        if self.illegible:
            self.value_raw = None
            self.confidence = min(self.confidence, 0.5)
        return self


class PageTranscription(Reading):
    """`transcribe_page` (3.8 Flash, high resolution): a whole page, printed and handwritten, when OCR stays
    below threshold or the page is a scan or photo of a hand-filled form (file 03 §A1.7)."""

    markdown: str
    language: str
    confidence: Confidence
    doubtful: list[HandwritingDoubt] = Field(
        default_factory=list, description="handwritten entries the reader is not sure of, reading order (v3)"
    )
    furniture: list[str] = Field(
        default_factory=list, description="printed headers, footers and margin identifiers, top first (v2)"
    )


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
    log_scale: bool = False


class PlotPoint(Reading):
    x: float | str = Field(description="number on a numeric axis, category label on a bar chart")
    y: float


class PlotSeries(Reading):
    name: str | None
    key_points: list[PlotPoint] = Field(default_factory=list)
    trend: str | None = None
    panel: str | None = Field(default=None, description="the panel of a figure with several plots")


class PlotReading(Reading):
    """`digitize_plot` (3.8 Flash, figure crop + caption): key points, never a dense trace."""

    image_metadata: ImageMetadata
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


class DrawingKind(StrEnum):
    SCHEMATIC = "schematic"
    MECHANICAL = "mechanical"
    FLOWCHART = "flowchart"


class SchematicReading(Reading):
    """`read_schematic` (3.8 Flash, figure crop): components and connections. v3 (2026-10-26, plan step D2):
    the drawing's kind first; a flowchart is its steps and the arrows between them (labelled yes or no)."""

    image_metadata: ImageMetadata
    drawing_kind: DrawingKind = DrawingKind.SCHEMATIC
    components: list[SchematicComponent] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
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


class PhotoKind(StrEnum):
    INSPECTION = "inspection"
    ASSEMBLY = "assembly"
    SETUP = "setup"
    AS_RECEIVED = "as_received"
    INSTRUMENT_READING = "instrument_reading"
    MATERIAL_SAMPLE = "material_sample"
    PRODUCT_IMAGE = "product_image"
    OTHER = "other"


class HardwarePhotoReading(Reading):
    """`inspect_hardware_photo` (3.8 Flash, medium resolution, photo and its context), no people. v2
    (2026-10-26, plan step D2): what the photo is for first; damage only when it is visible, never on a
    product image; values on gauges and screens in ``readings``."""

    image_metadata: ImageMetadata
    photo_kind: PhotoKind = PhotoKind.INSPECTION
    components_visible: list[str] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    readings: list[str] = Field(default_factory=list)
    visible_text: list[str] = Field(default_factory=list)
    test_stage_hint: TestStage
    description: str


class SlideReading(Reading):
    """`describe_slide` (3.8 Flash, slide image + extracted text)."""

    image_metadata: ImageMetadata
    summary: str
    diagram_description: str | None = None
    key_numbers: list[str] = Field(default_factory=list)


class VideoEvent(Reading):
    t_s: float = Field(ge=0.0)
    type: str
    description: str


class RecordingKind(StrEnum):
    FIRING = "firing"
    COLD_FLOW = "cold_flow"
    LEAK_CHECK = "leak_check"
    INSPECTION = "inspection"
    ASSEMBLY = "assembly"
    SETUP = "setup"
    SCREEN = "screen"
    OTHER = "other"


class VideoTimeline(Reading):
    """`video_timeline` (3.8 Flash, timestamped frames of a short clip). v3 (2026-10-26, plan step D): the
    model first says what kind of recording it is; ignition and shutdown belong to a firing only."""

    image_metadata: ImageMetadata
    recording_kind: RecordingKind
    summary: str
    events: list[VideoEvent] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
