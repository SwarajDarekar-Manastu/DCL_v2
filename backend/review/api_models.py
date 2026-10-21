"""Request and response models of the Review API (file 08 §4.4), shared by the router and the Console.

A case is the group of flags sharing ``case_key`` = ``{doc_id or location_id}:{page_or_sheet}``
(file 06 §5); it is identified by that key in URLs (percent-encoded). A resolution is one of the
file 06 §6 actions, picked by its ``action`` field; ``ALLOWED_ACTIONS`` says which actions a flag
type accepts and ``check_actions`` enforces it on the server.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.dispatcher.contract import BBox, FlagAnchor
from backend.postgres.enums import (
    AmbientCondition,
    CaseStatus,
    FlagSeverity,
    FlagStatus,
    FlagType,
    GaugeOrAbs,
    Route,
    RuleOrigin,
    RuleType,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- queue


class CaseFilters(_Model):
    """Query of ``GET /review/cases`` (file 06 §9 filters)."""

    severity: FlagSeverity | None = None
    flag_type: FlagType | None = None
    route: Route | None = None
    root_name: str | None = None
    test_plan_id: str | None = None
    assignee: str | None = None
    status: CaseStatus | None = None
    has_suggestion: bool | None = None
    older_than_days: int | None = Field(default=None, ge=0)
    sort: Literal["impact", "age", "severity"] = "impact"
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class CaseSummary(_Model):
    """One row of ``v_review_cases``."""

    case_key: str
    doc_id: uuid.UUID | None
    location_id: uuid.UUID | None
    page_or_sheet: str
    title: str
    path: str | None
    root_name: str | None
    route: Route | None
    status: CaseStatus
    max_severity: FlagSeverity
    flag_counts: dict[FlagType, int]
    assignee: str | None
    oldest_created_at: datetime
    has_suggestion: bool
    files_unblocked: int | None = Field(description="files the likely rule would resume (impact sort key)")
    preview_asset_id: uuid.UUID | None


class CaseList(_Model):
    items: list[CaseSummary]
    next_cursor: str | None
    open_hard: int
    open_soft: int


# ---------------------------------------------------------------- case detail


class FlagView(_Model):
    flag_id: uuid.UUID
    fingerprint: str
    flag_type: FlagType
    severity: FlagSeverity
    status: FlagStatus
    route: Route | None
    anchor: FlagAnchor
    evidence: dict[str, Any]
    suggested_resolution: dict[str, Any] | None
    resolution: dict[str, Any] | None
    resolution_rule_id: uuid.UUID | None
    assigned_to: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    due_at: datetime | None
    created_at: datetime


class CaseLocation(_Model):
    root_name: str
    path: str
    web_url: str | None


class CaseDetail(_Model):
    summary: CaseSummary
    flags: list[FlagView]
    document_status: str | None
    locations: list[CaseLocation]
    siblings: list[str] = Field(default=[], description="file names in the same folder")


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


class SetFactUnit(_Model):
    """UNIT_AMBIGUITY on a number in prose or a table: a unit, or keep it as text."""

    action: Literal["set_fact_unit"] = "set_fact_unit"
    unit: str | None = Field(default=None, description="null = leave as text")


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
    FlagType.LOW_CONFIDENCE_EXTRACTION: frozenset({"set_value", "choose_table"}),
    FlagType.PARSE_FAILURE: frozenset({"use_replacement", "skip", "mark_junk"}),
    FlagType.UNSUPPORTED_FORMAT: frozenset({"skip", "mark_junk", "watch"}),
    FlagType.CONFLICT: frozenset({"choose_source", "mark_superseded", "accept_both", "ignore"}),
    FlagType.SENSITIVE_CONTENT: frozenset({"redact", "approve_internal", "exclude"}),
    FlagType.HELD_LARGE_FILE: frozenset({"approve_download", "skip"}),
    FlagType.CLOUD_RESTRICTED: frozenset({"ignore"}),
}
ADMIN_ONLY_ACTIONS = frozenset({"approve_internal"})


class FlagResolution(_Model):
    flag_id: uuid.UUID
    resolution: Resolution


def check_actions(resolutions: list[FlagResolution], flag_types: dict[uuid.UUID, FlagType]) -> None:
    """Raise ``ValueError`` for an unknown flag or an action its flag type does not allow."""
    for item in resolutions:
        flag_type = flag_types.get(item.flag_id)
        if flag_type is None:
            raise ValueError(f"flag {item.flag_id} is not part of this case")
        if item.resolution.action not in ALLOWED_ACTIONS[flag_type]:
            raise ValueError(f"action {item.resolution.action!r} is not allowed for {flag_type}")


# ---------------------------------------------------------------- rules (file 06 §8)


class RuleScope(_Model):
    """The four scope columns; the most specific matching rule wins. All null = global."""

    scope_root: str | None = None
    scope_folder_id: str | None = None
    scope_filename_glob: str | None = None
    scope_extension: str | None = None


class RuleDraft(_Model):
    """An operator rule to create (operator rules are immutable; a change supersedes)."""

    rule_type: RuleType
    scope: RuleScope
    body: dict[str, Any] = Field(
        description="the mapping; schema per rule_type (channel_map: publish-first item 4)"
    )
    precedence: int = 0
    supersedes_rule_id: uuid.UUID | None = None


class RuleView(_Model):
    rule_id: uuid.UUID
    rule_type: RuleType
    origin: RuleOrigin
    scope: RuleScope
    body: dict[str, Any]
    precedence: int
    source_blob_sha256: str | None
    supersedes_rule_id: uuid.UUID | None
    active: bool
    created_by: str
    created_at: datetime
    flags_resolved: int = Field(description="derived from review_flags.resolution_rule_id (v_rule_usage)")
    runs_mapped: int = Field(description="derived from telemetry_runs.channel_map_rule_id (v_rule_usage)")


class RuleList(_Model):
    items: list[RuleView]


class AffectedDocument(_Model):
    doc_id: uuid.UUID
    title: str
    path: str | None
    status: str


class RuleSimulation(_Model):
    """What a rule would touch before it is confirmed ("this will re-process 116 runs")."""

    matched_documents: int
    would_resume: int
    would_reprocess: int
    sample: list[AffectedDocument]


# ---------------------------------------------------------------- case actions


class AssignRequest(_Model):
    assignee: str | None = Field(description="null unassigns")


class ResolveRequest(_Model):
    resolutions: list[FlagResolution] = Field(min_length=1)
    rule: RuleDraft | None = None
    comment: str | None = None


class ResolveResponse(_Model):
    case_key: str
    flags: list[FlagView]
    rule: RuleView | None
    resumed_doc_ids: list[uuid.UUID] = Field(
        description="this document and every halted sibling matched by the rule"
    )


class RejectRequest(_Model):
    action: Literal["skip", "mark_junk"]
    comment: str | None = None


class UndoResponse(_Model):
    case_key: str
    reopened_flag_ids: list[uuid.UUID]
    rebuild_doc_id: uuid.UUID | None


# ---------------------------------------------------------------- dry run


class DryRunRequest(_Model):
    case_key: str
    resolution: FlagResolution
    rule: RuleDraft | None = None


class ChannelPreview(_Model):
    canonical_name: str
    unit_si: str
    stat_min: float | None
    stat_max: float | None
    stat_mean: float | None
    stat_p99: float | None
    sanity_min: float | None
    sanity_max: float | None
    within_sanity: bool | None


class DryRunResponse(_Model):
    """The resolution applied to the staged payload, nothing committed."""

    channels: list[ChannelPreview] = []
    preview: dict[str, Any] = Field(
        default={}, description="type-specific preview (table cells, mapped keys)"
    )
    new_flags: list[FlagView] = Field(
        default=[], description="flags the validation gate would raise afterwards"
    )
    affected_documents: int
    messages: list[str] = []
