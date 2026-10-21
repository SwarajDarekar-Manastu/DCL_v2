"""Request and response models of the Review API (file 08 §4.4), shared by the router and the Console.

A case is the group of flags sharing ``case_key`` = ``{doc_id or location_id}:{page_or_sheet}``
(file 06 §5); it is identified by that key in URLs (percent-encoded). A resolution is one of the
file 06 §6 actions, picked by its ``action`` field; ``ALLOWED_ACTIONS`` says which actions a flag
type accepts and ``check_actions`` enforces it on the server.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.dispatcher.contract import (  # resolution actions live with the flags they resolve
    ADMIN_ONLY_ACTIONS,
    ALLOWED_ACTIONS,
    Evidence,
    FlagAnchor,
    Resolution,
    Suggestion,
)
from backend.postgres.enums import (
    CaseStatus,
    FlagSeverity,
    FlagStatus,
    FlagType,
    Route,
    RuleOrigin,
    RuleType,
)
from backend.review.rules import RuleScope, parse_body


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
    evidence: Evidence | None
    suggested_resolution: Suggestion | None
    resolution: Resolution | None
    resolution_rule_id: uuid.UUID | None
    assigned_to: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    due_at: datetime | None
    created_at: datetime
    allowed_actions: list[str] = Field(
        description="ALLOWED_ACTIONS for this flag type, minus ADMIN_ONLY_ACTIONS for non-admins"
    )


class CaseLocation(_Model):
    """One OneDrive location of the case's file, with the values the rule-scope selector needs."""

    root_name: str
    path: str
    web_url: str | None
    folder_id: str | None = Field(
        description="Graph item id of the parent folder (RuleScope.scope_folder_id)"
    )
    file_name: str
    extension: str | None


def allowed_actions_for(flag_type: FlagType, is_admin: bool) -> list[str]:
    actions = ALLOWED_ACTIONS[flag_type] if is_admin else ALLOWED_ACTIONS[flag_type] - ADMIN_ONLY_ACTIONS
    return sorted(actions)


class CaseDetail(_Model):
    summary: CaseSummary
    flags: list[FlagView]
    document_status: str | None
    locations: list[CaseLocation]
    siblings: list[str] = Field(default=[], description="file names in the same folder")


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


class RuleDraft(_Model):
    """An operator rule to create (operator rules are immutable; a change supersedes)."""

    rule_type: RuleType
    scope: RuleScope
    body: dict[str, Any] = Field(
        description="the mapping, validated by rule_type (backend/review/rules.py RULE_BODIES): "
        "channel_map → ChannelMapBody, unit_mapping → UnitMappingBody (the set_unit resolution "
        "without `action`), schema_mapping → SchemaMappingBody (map_columns without `action`), "
        "supersession, ignore_pattern, origin_override"
    )
    precedence: int = 0
    supersedes_rule_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _body_matches_type(self) -> "RuleDraft":
        parse_body(self.rule_type, self.body)
        return self


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
