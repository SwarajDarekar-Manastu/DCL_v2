"""Every lifecycle or kind column is ``text`` with a named CHECK built from one StrEnum.

File 05 marks these columns with ✓. No native PostgreSQL enum types are used.
Migrations hard-code the value lists they create; the schema tests compare the
CHECK in the database with the enums below, so an enum edit without a migration
fails CI.
"""

from enum import StrEnum

from sqlalchemy import CheckConstraint


def enum_check(column: str, enum: type[StrEnum]) -> CheckConstraint:
    """Named CHECK ``ck_<table>_<column>`` allowing exactly the enum's values (NULL passes)."""
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=column)


class SyncRootStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CRAWLING = "CRAWLING"
    RESYNCING = "RESYNCING"
    UNREACHABLE = "UNREACHABLE"
    PAUSED = "PAUSED"


class AuthStatus(StrEnum):
    OK = "OK"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"


class SourceOrigin(StrEnum):
    """Origin stored on registry rows and documents. ``web_live`` exists only at answer time."""

    INTERNAL = "internal"
    EXTERNAL_KEPT = "external_kept"


class DriveItemStatus(StrEnum):
    SEEN = "SEEN"
    SKIPPED_JUNK = "SKIPPED_JUNK"
    SKIPPED_EMPTY = "SKIPPED_EMPTY"
    SKIPPED_SHORTCUT = "SKIPPED_SHORTCUT"
    SKIPPED_UNSUPPORTED_PACKAGE = "SKIPPED_UNSUPPORTED_PACKAGE"
    QUARANTINED = "QUARANTINED"
    HELD_LARGE_FILE = "HELD_LARGE_FILE"
    HELD_BY_SCOPE = "HELD_BY_SCOPE"
    PENDING_DOWNLOAD = "PENDING_DOWNLOAD"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    LANDED = "LANDED"
    DELETED = "DELETED"


class BlobDerivationKind(StrEnum):
    ARCHIVE_MEMBER = "archive_member"
    PDF_ATTACHMENT = "pdf_attachment"
    EMBEDDED_OBJECT = "embedded_object"
    REDACTED_COPY = "redacted_copy"
    REPLACEMENT_UPLOAD = "replacement_upload"


class JobStage(StrEnum):
    DOWNLOAD = "download"
    DISPATCH = "dispatch"
    PARSE = "parse"
    ENRICH = "enrich"
    INDEX = "index"
    RESUME = "resume"
    REEMBED = "reembed"
    TRANSLATE = "translate"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ---------- documents, nodes, assets (file 05 §4.2) ----------


class Route(StrEnum):
    A1 = "A1"
    A2 = "A2"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


class DocKind(StrEnum):
    STANDARD = "standard"
    TEST_PLAN = "test_plan"
    TEST_REPORT = "test_report"
    FAILURE_REPORT = "failure_report"
    CALIBRATION = "calibration"
    RISK_ASSESSMENT = "risk_assessment"
    MATERIAL_SPEC = "material_spec"
    PROCEDURE = "procedure"
    WORKSHOP_SLIDES = "workshop_slides"
    CODE = "code"
    TOOLING_DOC = "tooling_doc"
    TELEMETRY_RUN = "telemetry_run"
    ENGINEERING_TABLE = "engineering_table"
    HARDWARE_PHOTO = "hardware_photo"
    PLOT_FIGURE = "plot_figure"
    DIAGRAM = "diagram"
    SCHEMA = "schema"
    VIDEO_TRANSCRIPT = "video_transcript"
    VIDEO_TIMELINE = "video_timeline"
    CAE_PACKAGE = "cae_package"
    CAD_REFERENCE = "cad_reference"
    CONFIG = "config"
    VENDOR_BROCHURE = "vendor_brochure"
    DATASHEET = "datasheet"
    ACADEMIC_PAPER = "academic_paper"
    ARTICLE = "article"
    BOOK_EXCERPT = "book_excerpt"
    CONFERENCE_PAPER = "conference_paper"
    UNKNOWN = "unknown"


class NodeType(StrEnum):
    PARENT = "parent"
    CHILD = "child"
    TABLE = "table"
    TABLE_ROW = "table_row"
    FIGURE = "figure"
    CODE_SYMBOL = "code_symbol"
    MODULE_HEADER = "module_header"
    SLIDE = "slide"
    TRANSCRIPT_WINDOW = "transcript_window"
    VIDEO_EVENT = "video_event"
    RUN_SUMMARY = "run_summary"
    PHOTO = "photo"
    DIAGRAM_SUMMARY = "diagram_summary"
    DIAGRAM_COMPONENT = "diagram_component"
    QUESTION_PROXY = "question_proxy"
    CONFIG = "config"


class NodeSource(StrEnum):
    PRINTED = "printed"
    OCR = "ocr"
    VLM = "vlm"
    SOURCE_CODE = "source_code"
    STRUCTURED = "structured"
    HUMAN = "human"


class AssetKind(StrEnum):
    PAGE_RENDER = "page_render"
    FIGURE_CROP = "figure_crop"
    HANDWRITING_CROP = "handwriting_crop"
    TABLE_CROP = "table_crop"
    PHOTO_WEB = "photo_web"
    PHOTO_THUMB = "photo_thumb"
    PHOTO_IN_DOC = "photo_in_doc"
    VIDEO_FRAME = "video_frame"
    DIAGRAM_RENDER = "diagram_render"
    SPARKLINE = "sparkline"


class MentionSource(StrEnum):
    REGEX = "regex"
    LLM = "llm"
    HUMAN = "human"


# ---------- review (file 05 §4.5, file 06 §3) ----------


class FlagType(StrEnum):
    UNIT_AMBIGUITY = "UNIT_AMBIGUITY"
    SCHEMA_UNKNOWN = "SCHEMA_UNKNOWN"
    LOW_CONFIDENCE_EXTRACTION = "LOW_CONFIDENCE_EXTRACTION"
    PARSE_FAILURE = "PARSE_FAILURE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    CONFLICT = "CONFLICT"
    SENSITIVE_CONTENT = "SENSITIVE_CONTENT"
    HELD_LARGE_FILE = "HELD_LARGE_FILE"
    CLOUD_RESTRICTED = "CLOUD_RESTRICTED"


class FlagSeverity(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


# ---------- telemetry (file 05 §4.4) ----------


class TelemetrySourceFormat(StrEnum):
    LABJACK_DAT = "labjack_dat"
    TDMS = "tdms"
    CSV = "csv"
    XLSX_SHEET = "xlsx_sheet"
    NPY_MAPPED = "npy_mapped"


class RunStatus(StrEnum):
    NOMINAL = "NOMINAL"
    FAILED_RUN = "FAILED_RUN"
    COLD_FLOW = "COLD_FLOW"
    PRE_HEAT = "PRE_HEAT"
    ABORTED = "ABORTED"
    UNKNOWN = "UNKNOWN"


class AmbientCondition(StrEnum):
    VACUUM_CHAMBER = "VACUUM_CHAMBER"
    SEA_LEVEL = "SEA_LEVEL"
    AMBIENT_RECORDED = "AMBIENT_RECORDED"
    UNKNOWN = "UNKNOWN"


class GaugeOrAbs(StrEnum):
    GAUGE = "gauge"
    ABSOLUTE = "absolute"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "n/a"
