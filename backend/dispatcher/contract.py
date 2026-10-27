"""The output contract every route returns (file 03 §1.4), and the stable anchor (file 04 §4.4).

A route turns one landed blob into a ``ProcessedDocument``. The common tail (validation gate,
enrichment, chunking, embedding, index commit) reads only this contract. The same model,
dumped to JSON, is the staged payload of a halted document (``dcl-cir/{sha256}/staged.json``,
file 06 §7), so it must round-trip through JSON unchanged.

Nodes, assets and mentions reference each other by ``ref``: a string the route chooses, unique
within the document (for example ``p3/s2`` or ``sym:NozzleSizer.solve``). Database ids are
assigned at commit and never appear here.

Boxes are normalized to 0..1 of the page with the origin at the top left, one ``PageBox`` per
box (the Console viewer scales them onto any render). Routes convert from their parser's units.
"""

import hashlib
import json
import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from backend.postgres.enums import (
    AmbientCondition,
    AssetKind,
    BlobDerivationKind,
    DocKind,
    FlagSeverity,
    FlagType,
    GaugeOrAbs,
    MentionSource,
    NodeSource,
    NodeType,
    Route,
    RunStatus,
    SourceOrigin,
    TelemetrySourceFormat,
)

SHA256_HEX = re.compile(r"[0-9a-f]{64}")
ANCHOR_HASH = re.compile(r"[0-9a-f]{16,64}")
A1_RANGE = re.compile(r"[A-Z]{1,3}[1-9][0-9]*(:[A-Z]{1,3}[1-9][0-9]*)?")
BBOX_FINGERPRINT_DIGITS = 4


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- geometry


class BBox(_Model):
    """A box in 0..1 page coordinates, origin top-left."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox needs x0 <= x1 and y0 <= y1")
        return self


class PageBox(BBox):
    page_no: int = Field(ge=1)


# ---------------------------------------------------------------- stable anchor


class AnchorError(ValueError):
    pass


class Anchor(_Model):
    """How durable records (citations, flags, benchmark gold, deep links) point at content.

    Exactly one locator: ``page_no``, ``line_start``, ``t_start_ms``, or ``sheet_name`` +
    ``cell_range``. ``content_sha256`` is the normalized-content hash (16–64 lowercase hex) that
    lets the resolver find the current node; ``backend/indexing/anchors.py`` computes it.
    """

    doc_id: uuid.UUID
    page_no: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    t_start_ms: int | None = Field(default=None, ge=0)
    sheet_name: str | None = None
    cell_range: str | None = None
    content_sha256: str | None = None
    breadcrumb: str | None = None

    @field_validator("content_sha256")
    @classmethod
    def _hash_format(cls, value: str | None) -> str | None:
        if value is not None and not ANCHOR_HASH.fullmatch(value):
            raise ValueError("content_sha256 must be 16 to 64 lowercase hex characters")
        return value

    @model_validator(mode="after")
    def _one_locator(self) -> Self:
        cells = self.sheet_name is not None or self.cell_range is not None
        if cells and (not self.sheet_name or not self.cell_range or not A1_RANGE.fullmatch(self.cell_range)):
            raise ValueError("a cells anchor needs sheet_name and an A1 cell_range")
        locators = [self.page_no is not None, self.line_start is not None, self.t_start_ms is not None, cells]
        if sum(locators) != 1:
            raise ValueError(
                "an anchor needs exactly one of page_no, line_start, t_start_ms, sheet_name+cell_range"
            )
        return self

    def locator_fields(self) -> dict[str, Any]:
        """The locator and hash as a dict keyed by field name (what ``parse_anchor`` returns)."""
        return self.model_dump(exclude={"doc_id", "breadcrumb"}, exclude_none=True)

    def serialize(self) -> str:
        """``<kind>:<value>:<content_sha256>`` (file 04 §4.4); the trailing colon is always written."""
        return format_anchor(self.locator_fields())

    @classmethod
    def parse(cls, doc_id: uuid.UUID | str, text: str) -> "Anchor":
        return cls(doc_id=doc_id, **parse_anchor(text))


def parse_anchor(text: str) -> dict[str, Any]:
    """Parse ``<kind>:<value>:<hash>`` with kind ``page``, ``line``, ``t`` or ``cells`` (``sheet!A1:D20``)."""
    kind, sep, rest = text.partition(":")
    if not sep:
        raise AnchorError("anchor must look like <kind>:<value>:<hash>")
    value, sep, content_hash = rest.rpartition(":")
    if not sep:
        value, content_hash = rest, ""
    if content_hash and not ANCHOR_HASH.fullmatch(content_hash):
        raise AnchorError("hash must be 16 to 64 lowercase hex characters")
    fields: dict[str, Any] = {"content_sha256": content_hash} if content_hash else {}
    if kind == "page":
        fields["page_no"] = _positive_int(value, "page", 1)
    elif kind == "line":
        fields["line_start"] = _positive_int(value, "line", 1)
    elif kind == "t":
        fields["t_start_ms"] = _positive_int(value, "t", 0)
    elif kind == "cells":
        sheet, bang, cell_range = value.rpartition("!")
        if not bang or not sheet or not A1_RANGE.fullmatch(cell_range):
            raise AnchorError("cells must look like <sheet>!<A1 range>")
        fields["sheet_name"], fields["cell_range"] = sheet, cell_range
    else:
        raise AnchorError(f"unknown anchor kind {kind!r} (page, line, t, cells)")
    return fields


def format_anchor(fields: dict[str, Any]) -> str:
    content_hash = fields.get("content_sha256") or ""
    if fields.get("page_no") is not None:
        kind, value = "page", str(fields["page_no"])
    elif fields.get("line_start") is not None:
        kind, value = "line", str(fields["line_start"])
    elif fields.get("t_start_ms") is not None:
        kind, value = "t", str(fields["t_start_ms"])
    elif fields.get("sheet_name") and fields.get("cell_range"):
        kind, value = "cells", f"{fields['sheet_name']}!{fields['cell_range']}"
    else:
        raise AnchorError("anchor needs page_no, line_start, t_start_ms or sheet_name + cell_range")
    text = f"{kind}:{value}:{content_hash}"
    parse_anchor(text)  # never emit a form the parser rejects
    return text


def _positive_int(value: str, name: str, minimum: int) -> int:
    if not value.isdigit() or int(value) < minimum:
        raise AnchorError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


# ---------------------------------------------------------------- resolutions (file 06 §6)


class SetUnit(_Model):
    """UNIT_AMBIGUITY on a telemetry channel: unit + gauge/abs + ambient, or a custom expression."""

    action: Literal["set_unit"] = "set_unit"
    channel: str
    unit: str = Field(min_length=1, description="pint-parsable unit, e.g. psig, bar(a), kPa, mV")
    quantity: str
    gauge_or_abs: GaugeOrAbs
    ambient_condition: AmbientCondition | None = None
    ambient_pressure_bar_abs: float | None = None
    expression: str | None = Field(
        default=None, description="custom conversion, e.g. val * 0.0689476 + 1.01325"
    )
    canonical_name: str | None = Field(
        default=None,
        description="what the rest of the system calls the channel; the file's own column name when absent "
        "(a rule's proposal carries the name its author chose)",
    )


class SetFactUnit(_Model):
    """UNIT_AMBIGUITY on a number in prose or a table: a unit, or "no unit needed" (kept as text)."""

    action: Literal["set_fact_unit"] = "set_fact_unit"
    unit: str | None = Field(
        default=None, description="null = no unit needed: not a measurement (ID, date, count, rating, ratio)"
    )


class ColumnMapping(_Model):
    index: int = Field(ge=0)
    canonical_name: str
    unit: str | None = None
    quantity: str | None = None
    is_time: bool = False


class MapColumns(_Model):
    """SCHEMA_UNKNOWN on an array or headerless table."""

    action: Literal["map_columns"] = "map_columns"
    columns: list[ColumnMapping] = Field(min_length=1)


class MapJsonKeys(_Model):
    """SCHEMA_UNKNOWN on a JSON file: key → section title, optionally saved as a new report schema."""

    action: Literal["map_json_keys"] = "map_json_keys"
    key_to_section: dict[str, str] = Field(min_length=1)
    save_as_schema: str | None = None


ILLEGIBLE = "[illegible]"  # how a page reading writes an entry nobody can read (prompt transcribe_page.v3)


class SetValue(_Model):
    """LOW_CONFIDENCE_EXTRACTION on a handwritten or OCR value."""

    action: Literal["set_value"] = "set_value"
    value: str | None = Field(default=None, description="null together with illegible = true")
    unit: str | None = None
    illegible: bool = False


class ChooseTable(_Model):
    """LOW_CONFIDENCE_EXTRACTION on a table: version A (TableFormer) or B (VLM), or edited cells."""

    action: Literal["choose_table"] = "choose_table"
    choice: Literal["A", "B", "edited"]
    cells: list[list[str]] | None = None


class ChooseSource(_Model):
    """CONFLICT: pick the authoritative value or document."""

    action: Literal["choose_source"] = "choose_source"
    choice: Literal["A", "B"]


class MarkSuperseded(_Model):
    action: Literal["mark_superseded"] = "mark_superseded"
    superseded_doc_id: uuid.UUID


class AcceptBoth(_Model):
    action: Literal["accept_both"] = "accept_both"


class Ignore(_Model):
    action: Literal["ignore"] = "ignore"


class UseReplacement(_Model):
    """PARSE_FAILURE: a readable copy uploaded through the Console (stored as a derived blob)."""

    action: Literal["use_replacement"] = "use_replacement"
    replacement_blob_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RedactionRegion(_Model):
    page: int | None = Field(default=None, ge=1)
    bbox: BBox | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)


class Redact(_Model):
    """SENSITIVE_CONTENT: process a redacted derived copy; the original stays restricted."""

    action: Literal["redact"] = "redact"
    regions: list[RedactionRegion] = Field(min_length=1)


class ApproveInternal(_Model):
    """SENSITIVE_CONTENT: index as-is for internal use (admin only)."""

    action: Literal["approve_internal"] = "approve_internal"


class ApproveDownload(_Model):
    """HELD_LARGE_FILE."""

    action: Literal["approve_download"] = "approve_download"


class Watch(_Model):
    """UNSUPPORTED_FORMAT: re-dispatch automatically when an adapter exists."""

    action: Literal["watch"] = "watch"


class Skip(_Model):
    action: Literal["skip"] = "skip"


class MarkJunk(_Model):
    action: Literal["mark_junk"] = "mark_junk"


class Exclude(_Model):
    action: Literal["exclude"] = "exclude"


Resolution = Annotated[
    SetUnit
    | SetFactUnit
    | MapColumns
    | MapJsonKeys
    | SetValue
    | ChooseTable
    | ChooseSource
    | MarkSuperseded
    | AcceptBoth
    | Ignore
    | UseReplacement
    | Redact
    | ApproveInternal
    | ApproveDownload
    | Watch
    | Skip
    | MarkJunk
    | Exclude,
    Field(discriminator="action"),
]

ALLOWED_ACTIONS: dict[FlagType, frozenset[str]] = {
    FlagType.UNIT_AMBIGUITY: frozenset({"set_unit", "set_fact_unit"}),
    FlagType.SCHEMA_UNKNOWN: frozenset({"map_columns", "map_json_keys", "mark_junk"}),
    FlagType.LOW_CONFIDENCE_EXTRACTION: frozenset({"set_value", "choose_table", "ignore", "mark_junk"}),
    FlagType.PARSE_FAILURE: frozenset({"use_replacement", "skip", "mark_junk"}),
    FlagType.UNSUPPORTED_FORMAT: frozenset({"skip", "mark_junk", "watch"}),
    FlagType.CONFLICT: frozenset({"choose_source", "mark_superseded", "accept_both", "ignore"}),
    FlagType.SENSITIVE_CONTENT: frozenset({"redact", "approve_internal", "exclude"}),
    FlagType.HELD_LARGE_FILE: frozenset({"approve_download", "skip"}),
    FlagType.CLOUD_RESTRICTED: frozenset({"ignore"}),
}
ADMIN_ONLY_ACTIONS = frozenset({"approve_internal"})

FlagSubject = Literal["file", "page", "object", "value"]
FILE_FLAGS = frozenset(
    {FlagType.PARSE_FAILURE, FlagType.UNSUPPORTED_FORMAT, FlagType.HELD_LARGE_FILE, FlagType.SCHEMA_UNKNOWN}
)


def flag_subject(flag_type: FlagType, anchor: dict[str, Any] | None) -> FlagSubject:
    """What a flag is about, which decides where skip and junk act (file 06 §6): only a file flag can take
    the file out of search. A LOW_CONFIDENCE_EXTRACTION is about one page (anchored by page alone), one figure
    or table (page and box) or one value (a handwritten entry: page and key); every other flag is a value."""
    anchor = anchor or {}
    if flag_type in FILE_FLAGS:
        return "file"
    if flag_type != FlagType.LOW_CONFIDENCE_EXTRACTION or anchor.get("page") is None:
        return "value"
    if anchor.get("bbox"):
        return "object"
    return "value" if anchor.get("content_sha256") else "page"


def allowed_actions(
    flag_type: FlagType, anchor: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None
) -> frozenset[str]:
    """ALLOWED_ACTIONS narrowed to what the flag is about: a page or a figure is kept as read or junked, a
    table is chosen or junked, a handwritten entry is typed, and a LOW_CONFIDENCE_EXTRACTION about nothing
    on a page (the formula cap) is only acknowledged."""
    if flag_type != FlagType.LOW_CONFIDENCE_EXTRACTION:
        return ALLOWED_ACTIONS[flag_type]
    subject = flag_subject(flag_type, anchor)
    if subject == "page":
        return frozenset({"ignore", "mark_junk"})
    if subject == "object":
        is_table = bool((evidence or {}).get("table_a_html"))
        return frozenset({"choose_table" if is_table else "ignore", "mark_junk"})
    if (anchor or {}).get("page") is not None:
        return frozenset({"set_value"})
    return frozenset({"ignore"})


# ---------------------------------------------------------------- evidence (file 06 §3, §5)
# What the route saw, so the reviewer confirms instead of investigating. Provisional shapes:
# routes may add keys only by extending these models. Images are referenced by their
# deterministic ``minio_uri`` in ``dcl-assets`` (the API presigns them).


class ChannelStats(_Model):
    n: int | None = Field(default=None, ge=0)
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    p50: float | None = None
    p99: float | None = None
    std: float | None = None


class CandidateUnit(_Model):
    unit: str
    gauge_or_abs: GaugeOrAbs = GaugeOrAbs.NOT_APPLICABLE
    score: float = Field(ge=0, le=1)
    reason: str = ""


class SiblingUnit(_Model):
    file_name: str
    channel: str
    unit: str
    source: str = Field(description="cfg | header | rule | config_json | tdms_props")


class SanityBounds(_Model):
    quantity: str
    unit: str
    min: float
    max: float


class UnitTelemetryEvidence(_Model):
    """UNIT_AMBIGUITY on a time-series channel (Route C)."""

    kind: Literal["unit_telemetry"] = "unit_telemetry"
    channel: str
    raw_unit: str | None = None
    quantity_guess: str | None = None
    header_lines: list[str] = []
    scaling_equation: str | None = Field(
        default=None, description="the channel's equation in the folder .cfg"
    )
    scaling_source: str | None = Field(default=None, description="file the scaling equation came from")
    note: str = Field(default="", description="why the channel cannot be used as mapped, when it is mapped")
    stats: ChannelStats = ChannelStats()
    sparkline_uri: str | None = None
    candidate_units: list[CandidateUnit] = []
    sibling_units: list[SiblingUnit] = []
    sanity: SanityBounds | None = None
    columns: list[str] = Field(default=[], description="column names of sample_rows, time column first")
    column_index: int | None = Field(default=None, ge=0, description="this channel's position in columns")
    sample_rows: list[list[float | str | None]] = Field(default=[], description="first 20 data rows, parsed")
    time_column: str | None = None
    series: list[tuple[float, float | None]] = Field(
        default=[], description="about 200 [t_rel_s, value] points, downsampled from raw.parquet"
    )


class UnitFactEvidence(_Model):
    """UNIT_AMBIGUITY on a number in prose or a table."""

    kind: Literal["unit_fact"] = "unit_fact"
    value_raw: str
    context: str = ""
    candidate_units: list[CandidateUnit] = []


class ColumnStats(ChannelStats):
    index: int = Field(ge=0)
    dtype: str | None = None
    sparkline_uri: str | None = None


class ArraySchemaEvidence(_Model):
    """SCHEMA_UNKNOWN on an array, headerless table, HDF5 or pickle (never unpickled)."""

    kind: Literal["array_schema"] = "array_schema"
    shape: list[int]
    dtype: str | None = None
    columns: list[ColumnStats] = []
    first_rows: list[list[float | str | None]] = []
    pickle_classes: list[str] = Field(default=[], description="from pickletools.dis, without executing")
    siblings: list[str] = []
    recommendation: str = ""


class JsonSchemaEvidence(_Model):
    """SCHEMA_UNKNOWN on a JSON file."""

    kind: Literal["json_schema"] = "json_schema"
    top_level_keys: list[str]
    flattened_sample: list[str] = []
    closest_schema: str | None = None
    missing_keys: list[str] = []


class ConflictSide(_Model):
    label: str
    value: str
    provenance: str = Field(description="file, header line, page or rule the value came from")
    doc_id: uuid.UUID | None = None
    date: str | None = None


ConflictRelation = Literal["sources_disagree", "check_failed", "note"]


class ConflictEvidence(_Model):
    """CONFLICT: what the route found, and how the reviewer should read the sides.

    ``sources_disagree``: ``a`` and ``b`` are two sources that state different values.
    ``check_failed``: ``a`` is what was found, ``b`` what the check expected (a limit or a rule).
    ``note``: ``a`` is a finding the system wants a person to confirm; there is no second side.
    """

    kind: Literal["conflict"] = "conflict"
    subject: str
    relation: ConflictRelation = "sources_disagree"
    a: ConflictSide
    b: ConflictSide | None = None

    @model_validator(mode="after")
    def _second_side_unless_note(self) -> Self:
        if (self.relation == "note") != (self.b is None):
            raise ValueError("a note has no second side; the other relations need one")
        return self


class ParseFailureEvidence(_Model):
    """PARSE_FAILURE (and the 'what is this?' preview of UNSUPPORTED_FORMAT)."""

    kind: Literal["parse_failure"] = "parse_failure"
    error: str
    magic_bytes_hex: str = ""
    size_bytes: int | None = Field(default=None, ge=0)
    detected_mime: str | None = None
    extension: str | None = None
    first_kb_preview: str = ""
    partial_output: str | None = None


class ExtractionCrop(_Model):
    crop_uri: str
    model_value: str | None = None
    alternatives: list[str] = []
    confidence: float | None = Field(default=None, ge=0, le=1)
    printed_label: str | None = None
    ocr_text: str | None = Field(
        default=None, description="the OCR engine's text of this crop (viewer text toggle)"
    )


class LowConfidenceEvidence(_Model):
    """LOW_CONFIDENCE_EXTRACTION: crops with the model's reading, or two table versions."""

    kind: Literal["low_confidence"] = "low_confidence"
    crops: list[ExtractionCrop] = []
    table_a_html: str | None = None
    table_b_html: str | None = None
    page_ocr_text: str | None = Field(
        default=None, description="the page's OCR text, shown by the PageViewer's text toggle (file 08 §4.2)"
    )


class SensitiveEvidence(_Model):
    """SENSITIVE_CONTENT: the matched pattern with a redacted preview (never the secret)."""

    kind: Literal["sensitive"] = "sensitive"
    pattern: str
    redacted_preview: str
    line: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)


class FileFactsEvidence(_Model):
    """HELD_LARGE_FILE and CLOUD_RESTRICTED: facts about the file only."""

    kind: Literal["file_facts"] = "file_facts"
    size_bytes: int | None = Field(default=None, ge=0)
    extension: str | None = None
    folder: str | None = None
    note: str = ""


Evidence = Annotated[
    UnitTelemetryEvidence
    | UnitFactEvidence
    | ArraySchemaEvidence
    | JsonSchemaEvidence
    | ConflictEvidence
    | ParseFailureEvidence
    | LowConfidenceEvidence
    | SensitiveEvidence
    | FileFactsEvidence,
    Field(discriminator="kind"),
]


class Suggestion(_Model):
    """A proposed resolution (file 06 §5): deterministic heuristics first, else one Gemini proposal.
    Applied automatically only when ``confidence >= 0.9`` and a matching rule exists."""

    resolution: Resolution | None = Field(
        default=None, description="None: no proposal; the rationale says why (an explicit 'no suggestion')"
    )
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""
    proposed_by: Literal["heuristic", "rule", "llm"] = "heuristic"


# ---------------------------------------------------------------- flags


class FlagAnchor(_Model):
    """Where in the CIR a flag points (file 05 §4.5 ``review_flags.anchor``); never a node id."""

    page: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    bbox: BBox | None = None
    content_sha256: str | None = None
    channel: str | None = None
    column: str | None = None
    line: int | None = Field(default=None, ge=1)

    def canonical(self) -> str:
        data = self.model_dump(exclude_none=True)
        if "bbox" in data:
            data["bbox"] = {k: round(v, BBOX_FINGERPRINT_DIGITS) for k, v in data["bbox"].items()}
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Flag(_Model):
    """A structured question to a human (file 06 §5). Severity is the route's default for the type;
    ``flags.severity_overrides`` and ``flags.strict_mode`` are applied by the validation gate."""

    flag_type: FlagType
    severity: FlagSeverity
    anchor: FlagAnchor = FlagAnchor()
    evidence: Evidence | None = None
    suggested_resolution: Suggestion | None = None

    @model_validator(mode="before")
    @classmethod
    def _drop_computed(cls, data: Any) -> Any:
        """Accept a dumped flag (staged payload): computed keys are dropped, a stale fingerprint refused."""
        if not isinstance(data, dict) or not ({"fingerprint", "page_or_sheet"} & data.keys()):
            return data
        data = dict(data)
        stated = data.pop("fingerprint", None)
        data.pop("page_or_sheet", None)
        if stated is not None and cls.model_validate(data).fingerprint != stated:
            raise ValueError("fingerprint does not match flag_type and anchor")
        return data

    @computed_field
    @property
    def fingerprint(self) -> str:
        """``flag_type`` + canonical anchor, hashed: re-indexing upserts the same flag."""
        return hashlib.sha256(f"{self.flag_type}|{self.anchor.canonical()}".encode()).hexdigest()

    @computed_field
    @property
    def page_or_sheet(self) -> str:
        """Second half of the case key `{doc_id or location_id}:{page_or_sheet}`; empty at document level."""
        if self.anchor.page is not None:
            return str(self.anchor.page)
        return self.anchor.sheet or ""


# ---------------------------------------------------------------- document, nodes, assets, mentions


class ExternalIds(_Model):
    doi: str | None = None
    arxiv: str | None = None
    isbn: str | None = None
    report_number: str | None = None


class DocumentFields(_Model):
    """The ``documents`` columns a route decides (file 05 §4.2). Status, folder context, enrichment,
    search text and timestamps are written by the dispatcher and the commit path, not by routes."""

    title: str
    doc_kind: DocKind = DocKind.UNKNOWN
    source_origin: SourceOrigin | None = None
    trust_tier: int | None = Field(default=None, ge=1, le=6)
    publisher: str | None = None
    external_ids: ExternalIds = ExternalIds()
    test_plan_id: str | None = None
    test_run_id: str | None = None
    hardware_item: str | None = None
    doc_date: date | None = None
    date_source: str | None = None
    standard_id: str | None = None
    standard_revision: str | None = None
    revision_marker: str | None = None
    classification_marking: str | None = None
    language: str | None = None
    languages_detected: list[str] = []
    number_locale: str | None = None
    page_count: int | None = Field(default=None, ge=0)
    unit_count: int | None = Field(default=None, ge=0)
    catalog: dict[str, Any] | None = None
    # the file's own one-paragraph summary as the route read it (a photo's VLM description, a plot's axes and
    # series notes, a run's first line); used when enrichment wrote none (file 04 §3.4 `doc_summary`)
    summary: str | None = None


class ProcessedNode(_Model):
    """A structural unit the route found (section, table, row, figure, code symbol, slide, run summary…).
    The chunker (file 04 §4) builds the retrievable parent/child nodes from these."""

    ref: str = Field(min_length=1)
    parent_ref: str | None = None
    node_type: NodeType
    level: int = Field(default=0, ge=0)
    ordinal: int = Field(ge=0)
    breadcrumb: str = ""
    language: str | None = None
    content: str
    page_no: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    bboxes: list[PageBox] = []
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    t_start_ms: int | None = Field(default=None, ge=0)
    t_end_ms: int | None = Field(default=None, ge=0)
    sheet_name: str | None = None
    cell_range: str | None = None
    source: NodeSource
    confidence: float | None = Field(default=None, ge=0, le=1)
    asset_ref: str | None = None
    metadata: dict[str, Any] = {}


class ProcessedAsset(_Model):
    """A renderable artifact in ``dcl-assets`` (file 05 §1); ``minio_uri`` is deterministic per blob."""

    ref: str = Field(min_length=1)
    kind: AssetKind
    minio_uri: str = Field(pattern=r"^s3://dcl-assets/")
    page_no: int | None = Field(default=None, ge=1)
    bbox: BBox | None = None
    t_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    bytes: int | None = Field(default=None, ge=0)
    phash: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    exif: dict[str, Any] = {}


class Mention(_Model):
    """A deterministic mention (regex-found ids, part numbers, standards, references, annotations).
    ``kind`` is free text until the entity types are fixed with the entities tables (M4, S2)."""

    node_ref: str
    kind: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    span_start: int | None = Field(default=None, ge=0)
    span_end: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: MentionSource = MentionSource.REGEX


class UnitHash(_Model):
    """L2 hash of one page, sheet, slide or code symbol (file 02 §5): which units changed."""

    unit: str = Field(pattern=r"^(page|sheet|slide|symbol)$")
    key: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_HEX.pattern)


# ---------------------------------------------------------------- telemetry catalog (Route C)


class SubRun(_Model):
    idx: int = Field(ge=0)
    t_start_ms: int = Field(ge=0)
    t_end_ms: int = Field(ge=0)
    label: str | None = None


class TelemetryChannelRecord(_Model):
    """One canonical channel of a run (file 05 §4.4 ``telemetry_channels``)."""

    canonical_name: str
    raw_name: str
    raw_unit: str | None = None
    quantity: str | None = None
    unit_si: str | None = None
    gauge_or_abs: GaugeOrAbs = GaugeOrAbs.NOT_APPLICABLE
    conversion: dict[str, Any] = {}
    sensor_tag: str | None = None
    range_min: float | None = None
    range_max: float | None = None
    stat_min: float | None = None
    stat_max: float | None = None
    stat_mean: float | None = None
    stat_p50: float | None = None
    stat_p99: float | None = None
    stat_std: float | None = None
    peak_raw: float | None = None
    peak_50ms: float | None = None
    steady_mean: float | None = None
    steady_window_ms: list[int] | None = None
    saturated: bool = False
    null_fraction: float | None = Field(default=None, ge=0, le=1)
    sparkline_asset_ref: str | None = None


class TelemetryRunRecord(_Model):
    """One run (file 05 §4.4 ``telemetry_runs``); Parquet files live in ``dcl-telemetry/{run_uuid}/``."""

    run_uuid: uuid.UUID
    run_label: str
    source_format: TelemetrySourceFormat
    run_status: RunStatus = RunStatus.UNKNOWN
    ambient_condition: AmbientCondition = AmbientCondition.UNKNOWN
    ambient_pressure_bar_abs: float | None = None
    sampling_rate_hz_nominal: float | None = None
    sampling_rate_hz_actual: float | None = None
    duration_s: float | None = None
    n_rows: int | None = Field(default=None, ge=0)
    n_gaps: int | None = Field(default=None, ge=0)
    n_duplicate_ts: int | None = Field(default=None, ge=0)
    t0_ignition_ms: int | None = None
    t0_method: str | None = None
    t0_confidence: float | None = Field(default=None, ge=0, le=1)
    sub_runs: list[SubRun] = []
    raw_parquet_uri: str | None = None
    normalized_parquet_uri: str | None = None
    schema_uri: str | None = None
    recorded_at: datetime | None = None
    channel_map_rule_id: uuid.UUID | None = None
    clock_offsets: dict[str, int] = {}
    channels: list[TelemetryChannelRecord] = []


# ---------------------------------------------------------------- derived blobs


DERIVED_KINDS = frozenset(
    {BlobDerivationKind.EMBEDDED_OBJECT, BlobDerivationKind.ARCHIVE_MEMBER, BlobDerivationKind.PDF_ATTACHMENT}
)


class DerivedBlob(_Model):
    """A file found inside the primary one (an Excel object in a Word file, an archive member, a PDF
    attachment). The commit path stores it in ``dcl-raw`` and ``blob_derivations``; the next dispatch
    makes it a document of its own. Give the bytes (base64 in JSON), or the sha256 of a blob a route
    already stored."""

    member_path: str = Field(min_length=1, description="path inside the parent, e.g. word/embeddings/x.xlsx")
    model_config = ConfigDict(extra="forbid", frozen=True, ser_json_bytes="base64", val_json_bytes="base64")

    data: bytes | None = None
    blob_sha256: str | None = Field(default=None, pattern=SHA256_HEX.pattern)
    kind: BlobDerivationKind = BlobDerivationKind.EMBEDDED_OBJECT

    @model_validator(mode="after")
    def _bytes_or_sha(self) -> Self:
        if (self.data is None) == (self.blob_sha256 is None):
            raise ValueError("a derived blob carries either data or blob_sha256")
        if self.kind not in DERIVED_KINDS:
            raise ValueError(f"kind {self.kind} is not a derived-file kind")
        if self.member_path.startswith("/") or ".." in self.member_path.split("/"):
            raise ValueError("member_path is relative and stays inside the parent")
        return self


# ---------------------------------------------------------------- the contract


class ProcessedDocument(_Model):
    """Everything one route produced for one primary blob."""

    blob_sha256: str = Field(pattern=SHA256_HEX.pattern)
    route: Route
    parser_version: int = Field(ge=1)
    cir_uri: str
    document: DocumentFields
    nodes: list[ProcessedNode] = []
    assets: list[ProcessedAsset] = []
    telemetry_runs: list[TelemetryRunRecord] = []
    mentions: list[Mention] = []
    flags: list[Flag] = []
    unit_hashes: list[UnitHash] = []
    derived_blobs: list[DerivedBlob] = []

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        prefix = f"s3://dcl-cir/{self.blob_sha256}/{self.route}/v{self.parser_version}/"
        if not self.cir_uri.startswith(prefix):
            raise ValueError(f"cir_uri must start with {prefix}")
        node_refs = _unique([node.ref for node in self.nodes], "node ref")
        asset_refs = _unique([asset.ref for asset in self.assets], "asset ref")
        _unique([flag.fingerprint for flag in self.flags], "flag fingerprint")
        _unique([blob.member_path for blob in self.derived_blobs], "derived member_path")
        for node in self.nodes:
            if node.parent_ref is not None and node.parent_ref not in node_refs:
                raise ValueError(f"node {node.ref!r}: parent_ref {node.parent_ref!r} is not a node")
            if node.asset_ref is not None and node.asset_ref not in asset_refs:
                raise ValueError(f"node {node.ref!r}: asset_ref {node.asset_ref!r} is not an asset")
        for mention in self.mentions:
            if mention.node_ref not in node_refs:
                raise ValueError(f"mention {mention.surface!r}: node_ref {mention.node_ref!r} is not a node")
        for run in self.telemetry_runs:
            for channel in run.channels:
                if channel.sparkline_asset_ref is not None and channel.sparkline_asset_ref not in asset_refs:
                    raise ValueError(f"channel {channel.canonical_name!r}: sparkline is not an asset")
        return self

    @property
    def has_hard_flags(self) -> bool:
        return any(flag.severity == FlagSeverity.HARD for flag in self.flags)


def _unique(values: list[str], what: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {what} {value!r}")
        seen.add(value)
    return seen
