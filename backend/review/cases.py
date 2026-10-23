"""Review cases over ``review_flags`` (file 06 §5–§8, file 08 §4): queue, detail, resolve, reject, assign.

A case is the group of flags sharing ``case_key``; its status is derived from its flags (file 08 §4.3).
Every human action writes ``audit_events``. A telemetry ``set_unit`` always ends in an operator
``channel_map`` rule (file 06 §6): the reviewer's rule when given, else one scoped to this file; the
caller then starts ``dcl.process.resume_for_rule`` so this document and every HALTED sibling the rule
matches re-run from their staged data. Dry run and undo are not here yet (the router answers 501).
"""

import json
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import SetUnit
from backend.postgres.enums import (
    AuditEntityType,
    CaseStatus,
    DocumentSourceRole,
    DocumentStatus,
    DriveItemStatus,
    FlagSeverity,
    FlagStatus,
    FlagType,
    Quantity,
    Route,
    RuleOrigin,
    RuleType,
)
from backend.postgres.models import AuditEvent, Document, DocumentSource, DriveItem, ReviewFlag, Rule
from backend.review.api_models import (
    AppliedUnit,
    CaseDetail,
    CaseFilters,
    CaseList,
    CaseLocation,
    CaseSummary,
    EditRequest,
    FlagView,
    RejectRequest,
    ResolveRequest,
    RuleDraft,
    RuleView,
    allowed_actions_for,
    check_actions,
)
from backend.review.proposals import refresh as refresh_proposals
from backend.review.proposals import target_of as _target_of
from backend.review.rules import RULE_BODIES, ChannelMapBody, RuleScope, UnitMappingBody

log = logging.getLogger(__name__)
OPEN = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)
# Closed flags: by a person, or by the pipeline once a rule answered them (the old flow, no person involved).
DECIDED = (FlagStatus.RESOLVED, FlagStatus.REJECTED_FILE, FlagStatus.AUTO_RESOLVED)
SEVERITY_RANK = {FlagSeverity.HARD: 0, FlagSeverity.SOFT: 1}


def _route(value: str | None, where: str) -> Route | None:
    """A stored route value, or None (logged) when a row carries one that is not a route."""
    if value is None:
        return None
    try:
        return Route(value)
    except ValueError:
        log.warning("unexpected route %r on %s; shown without a route", value, where)
        return None


class CaseNotFound(LookupError):
    pass


class InvalidAction(ValueError):
    pass


@dataclass
class _Case:
    key: str
    flags: list[ReviewFlag] = field(default_factory=list)

    @property
    def open_flags(self) -> list[ReviewFlag]:
        return [f for f in self.flags if f.status in OPEN]

    @property
    def status(self) -> CaseStatus:
        statuses = {f.status for f in self.flags}
        if FlagStatus.REOPENED in statuses:
            return CaseStatus.REOPENED
        if statuses & {FlagStatus.OPEN, FlagStatus.IN_PROGRESS}:
            busy = FlagStatus.IN_PROGRESS in statuses or any(f.assigned_to for f in self.open_flags)
            return CaseStatus.IN_PROGRESS if busy else CaseStatus.OPEN
        if statuses == {FlagStatus.REJECTED_FILE}:
            return CaseStatus.REJECTED_FILE
        return CaseStatus.RESOLVED

    @property
    def counted(self) -> list[ReviewFlag]:
        return self.open_flags or self.flags


def _audit(
    session: Session, actor: str, entity_type: AuditEntityType, entity_id: str, action: str, before, after
):
    session.add(
        AuditEvent(
            actor=actor,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
        )
    )


# ---------------------------------------------------------------- reading


@dataclass
class _Context:
    documents: dict[uuid.UUID, Document]
    items_by_doc: dict[uuid.UUID, DriveItem]
    items_by_id: dict[uuid.UUID, DriveItem]
    halted_by_folder: Counter


def _context(session: Session, cases: list[_Case]) -> _Context:
    doc_ids = {f.doc_id for c in cases for f in c.flags if f.doc_id}
    location_ids = {f.location_id for c in cases for f in c.flags if f.location_id and not f.doc_id}
    documents = {d.doc_id: d for d in session.scalars(select(Document).where(Document.doc_id.in_(doc_ids)))}
    items_by_doc: dict[uuid.UUID, DriveItem] = {}
    for doc_id, item in session.execute(
        select(DocumentSource.doc_id, DriveItem)
        .join(DriveItem, DriveItem.blob_sha256 == DocumentSource.blob_sha256)
        .where(
            DocumentSource.doc_id.in_(doc_ids),
            DocumentSource.role == DocumentSourceRole.PRIMARY,
            DriveItem.status != DriveItemStatus.DELETED,
        )
        .order_by(DriveItem.path_cached)
    ).all():
        items_by_doc.setdefault(doc_id, item)
    items_by_id = {
        i.location_id: i
        for i in session.scalars(select(DriveItem).where(DriveItem.location_id.in_(location_ids)))
    }
    halted = Counter(
        parent
        for parent, _ in session.execute(
            select(DriveItem.parent_item_id, Document.doc_id)
            .join(DocumentSource, DocumentSource.blob_sha256 == DriveItem.blob_sha256)
            .join(Document, Document.doc_id == DocumentSource.doc_id)
            .where(
                Document.status == DocumentStatus.HALTED, DocumentSource.role == DocumentSourceRole.PRIMARY
            )
            .distinct()
        ).all()
    )
    return _Context(documents, items_by_doc, items_by_id, halted)


def _summary(case: _Case, ctx: _Context) -> CaseSummary:
    first = case.flags[0]
    document = ctx.documents.get(first.doc_id) if first.doc_id else None
    item = ctx.items_by_doc.get(first.doc_id) if first.doc_id else ctx.items_by_id.get(first.location_id)
    counted = case.counted
    max_severity = min((FlagSeverity(f.severity) for f in counted), key=SEVERITY_RANK.__getitem__)
    hard_open = any(f.severity == FlagSeverity.HARD for f in case.open_flags)
    return CaseSummary(
        case_key=case.key,
        doc_id=first.doc_id,
        location_id=first.location_id,
        page_or_sheet=first.page_or_sheet,
        title=(document.title if document and document.title else None) or (item.name if item else case.key),
        path=item.path_cached if item else None,
        root_name=item.root_name if item else None,
        route=_route(document.route, f"document {document.doc_id}")
        if document and document.route
        else _route(first.route, f"flag {first.flag_id}"),
        status=case.status,
        max_severity=max_severity,
        flag_counts=dict(Counter(FlagType(f.flag_type) for f in counted)),
        assignee=next((f.assigned_to for f in case.open_flags if f.assigned_to), None),
        oldest_created_at=min(f.created_at for f in case.flags),
        has_suggestion=any(f.suggested_resolution for f in counted),
        has_rule_proposal=any(f.proposed_by_rule_id for f in case.open_flags),
        files_unblocked=(ctx.halted_by_folder.get(item.parent_item_id, 0) or None)
        if item and hard_open
        else None,
        preview_asset_id=None,
    )


def _flag_order(flag: ReviewFlag) -> tuple:
    return (flag.created_at, json.dumps(flag.anchor or {}, sort_keys=True), flag.flag_type, str(flag.flag_id))


def _cases(session: Session) -> list[_Case]:
    grouped: dict[str, _Case] = {}
    for flag in sorted(session.scalars(select(ReviewFlag)), key=_flag_order):
        grouped.setdefault(flag.case_key, _Case(flag.case_key)).flags.append(flag)
    return list(grouped.values())


def _keep(summary: CaseSummary, case: _Case, ctx: _Context, filters: CaseFilters, now: datetime) -> bool:
    if filters.status:
        wanted = {filters.status}
    elif filters.decided:
        wanted = set(CaseStatus)
    else:
        wanted = {CaseStatus.OPEN, CaseStatus.IN_PROGRESS, CaseStatus.REOPENED}
    if summary.status not in wanted:
        return False
    if filters.decided is not None:
        has_decision = any(f.status in DECIDED for f in case.flags)
        if has_decision != filters.decided:
            return False
    counted = case.counted
    if filters.severity and not any(f.severity == filters.severity for f in counted):
        return False
    if filters.flag_type and not any(f.flag_type == filters.flag_type for f in counted):
        return False
    if filters.route and summary.route != filters.route:
        return False
    if filters.root_name and summary.root_name != filters.root_name:
        return False
    if filters.test_plan_id:
        document = ctx.documents.get(summary.doc_id) if summary.doc_id else None
        if not document or (document.test_plan_id or "").casefold() != filters.test_plan_id.casefold():
            return False
    if filters.assignee and summary.assignee != filters.assignee:
        return False
    if filters.has_suggestion is not None and summary.has_suggestion != filters.has_suggestion:
        return False
    if filters.proposed_by_rule_id and not any(
        f.proposed_by_rule_id == filters.proposed_by_rule_id for f in case.open_flags
    ):
        return False
    if filters.q:
        haystack = f"{summary.title} {summary.path or ''}".casefold()
        if not all(word in haystack for word in filters.q.casefold().split()):
            return False
    if filters.older_than_days is not None:
        if summary.oldest_created_at > now - timedelta(days=filters.older_than_days):
            return False
    return True


def _sort_key(sort: str):
    if sort == "age":
        return lambda s: (s.oldest_created_at, s.title, s.case_key)
    if sort == "severity":
        return lambda s: (SEVERITY_RANK[s.max_severity], s.oldest_created_at, s.title, s.case_key)
    return lambda s: (
        -(s.files_unblocked or 0),
        SEVERITY_RANK[s.max_severity],
        s.oldest_created_at,
        s.title,
        s.case_key,
    )


def list_cases(session: Session, filters: CaseFilters, now: datetime | None = None) -> CaseList:
    now = now or datetime.now(UTC)
    cases = _cases(session)
    ctx = _context(session, cases)
    rows = [(s, c) for c in cases if _keep(s := _summary(c, ctx), c, ctx, filters, now)]
    summaries = sorted((s for s, _ in rows), key=_sort_key(filters.sort))
    start = int(filters.cursor or 0)
    page = summaries[start : start + filters.limit]
    open_flags = [f for c in cases for f in c.open_flags]
    return CaseList(
        items=page,
        next_cursor=str(start + filters.limit) if start + filters.limit < len(summaries) else None,
        open_hard=sum(f.severity == FlagSeverity.HARD for f in open_flags),
        open_soft=sum(f.severity == FlagSeverity.SOFT for f in open_flags),
    )


def _case(session: Session, case_key: str) -> _Case:
    flags = sorted(
        session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == case_key)), key=_flag_order
    )
    if not flags:
        raise CaseNotFound(case_key)
    return _Case(case_key, flags)


def flag_view(flag: ReviewFlag, is_admin: bool) -> FlagView:
    return FlagView.model_validate(
        {
            **{c: getattr(flag, c) for c in FlagView.model_fields if c not in ("allowed_actions", "route")},
            "route": _route(flag.route, f"flag {flag.flag_id}"),
            "allowed_actions": allowed_actions_for(FlagType(flag.flag_type), is_admin),
        }
    )


def _applied_unit_of(rule: Rule, flag: ReviewFlag) -> SetUnit | None:
    """The unit a channel_map rule gave a channel, as the decision a person would have made."""
    channel = (flag.anchor or {}).get("channel")
    entry = (rule.body or {}).get("channels", {}).get(channel) if channel else None
    if not entry:
        return None
    return SetUnit(
        channel=channel,
        unit=entry["unit"],
        quantity=str(entry["physical_quantity"]),
        gauge_or_abs=entry.get("gauge_or_abs", "n/a"),
        ambient_condition=rule.body.get("ambient_condition"),
        ambient_pressure_bar_abs=rule.body.get("ambient_pressure_bar_abs"),
        expression=entry.get("expression"),
        canonical_name=entry.get("canonical_name"),
    )


def _applied_units(session: Session, case: _Case) -> list[AppliedUnit]:
    from backend.postgres.models import TelemetryRun

    auto = [
        f
        for f in case.flags
        if f.status == FlagStatus.AUTO_RESOLVED
        and f.flag_type == FlagType.UNIT_AMBIGUITY
        and f.doc_id
        and (f.anchor or {}).get("channel")
    ]
    if not auto:
        return []
    rule_ids = {
        rid
        for rid in session.scalars(
            select(TelemetryRun.channel_map_rule_id).where(TelemetryRun.doc_id.in_({f.doc_id for f in auto}))
        )
        if rid
    }
    rules = {r.rule_id: r for r in session.scalars(select(Rule).where(Rule.rule_id.in_(rule_ids)))}
    found = []
    for flag in auto:
        for rule in rules.values():
            unit = _applied_unit_of(rule, flag)
            if unit is not None:
                found.append(
                    AppliedUnit(
                        flag_id=flag.flag_id,
                        channel=unit.channel,
                        unit=unit.unit,
                        quantity=unit.quantity,
                        gauge_or_abs=str(unit.gauge_or_abs),
                        canonical_name=unit.canonical_name,
                        ambient_condition=str(unit.ambient_condition) if unit.ambient_condition else None,
                        rule_id=rule.rule_id,
                        rule_created_by=rule.created_by,
                        rule_created_at=rule.created_at,
                        rule_active=rule.active,
                    )
                )
                break
    return found


def case_detail(session: Session, case_key: str, is_admin: bool) -> CaseDetail:
    case = _case(session, case_key)
    ctx = _context(session, [case])
    summary = _summary(case, ctx)
    first = case.flags[0]
    document = ctx.documents.get(first.doc_id) if first.doc_id else None
    if first.doc_id:
        items = session.scalars(
            select(DriveItem)
            .join(DocumentSource, DocumentSource.blob_sha256 == DriveItem.blob_sha256)
            .where(
                DocumentSource.doc_id == first.doc_id,
                DocumentSource.role == DocumentSourceRole.PRIMARY,
                DriveItem.status != DriveItemStatus.DELETED,
            )
            .order_by(DriveItem.path_cached)
        ).all()
    else:
        items = [i for i in [ctx.items_by_id.get(first.location_id)] if i]
    siblings: list[str] = []
    if items and items[0].parent_item_id:
        siblings = list(
            session.scalars(
                select(DriveItem.name)
                .where(
                    DriveItem.parent_item_id == items[0].parent_item_id,
                    DriveItem.status != DriveItemStatus.DELETED,
                    DriveItem.location_id != items[0].location_id,
                )
                .order_by(DriveItem.name)
                .limit(200)
            )
        )
    return CaseDetail(
        summary=summary,
        flags=[flag_view(f, is_admin) for f in case.flags],
        document_status=document.status if document else None,
        locations=[
            CaseLocation(
                root_name=i.root_name,
                path=i.path_cached or i.name,
                web_url=i.web_url,
                folder_id=i.parent_item_id,
                file_name=i.name,
                extension=i.extension,
            )
            for i in items
        ],
        siblings=siblings,
        applied_units=_applied_units(session, case),
    )


# ---------------------------------------------------------------- rules


def rule_view(session: Session, rule: Rule) -> RuleView:
    from sqlalchemy import func

    from backend.postgres.models import TelemetryRun

    def count(*where) -> int:
        return session.scalar(select(func.count()).where(*where)) or 0

    from backend.postgres.models import DriveFolder

    proposed = ReviewFlag.proposed_by_rule_id == rule.rule_id
    folder_path = (
        session.scalar(select(DriveFolder.path_cached).where(DriveFolder.item_id == rule.scope_folder_id))
        if rule.scope_folder_id
        else None
    )
    return RuleView(
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        origin=rule.origin,
        scope=RuleScope(
            scope_root=rule.scope_root,
            scope_folder_id=rule.scope_folder_id,
            scope_filename_glob=rule.scope_filename_glob,
            scope_extension=rule.scope_extension,
        ),
        body=rule.body,
        precedence=rule.precedence,
        source_blob_sha256=rule.source_blob_sha256,
        supersedes_rule_id=rule.supersedes_rule_id,
        active=rule.active,
        created_by=rule.created_by,
        created_at=rule.created_at,
        flags_resolved=count(ReviewFlag.resolution_rule_id == rule.rule_id),
        runs_mapped=count(TelemetryRun.channel_map_rule_id == rule.rule_id),
        scope_folder_path=folder_path,
        flags_proposed=count(proposed),
        flags_decided=count(proposed, ReviewFlag.status.in_([FlagStatus.RESOLVED, FlagStatus.REJECTED_FILE])),
        files_waiting=session.scalar(
            select(func.count(func.distinct(ReviewFlag.doc_id))).where(proposed, ReviewFlag.status.in_(OPEN))
        )
        or 0,
    )


def list_rules(
    session: Session, active: bool | None, kind: Literal["rules", "decisions"] | None = None
) -> list[RuleView]:
    """``rules``: what a person writes (proposals and the kinds nothing reads yet); ``decisions``: a person's
    approval of one file's columns (``channel_map``), which the Audit page shows."""
    stmt = select(Rule).order_by(Rule.created_at.desc())
    if active is not None:
        stmt = stmt.where(Rule.active.is_(active))
    if kind == "rules":
        stmt = stmt.where(Rule.rule_type != RuleType.CHANNEL_MAP)
    elif kind == "decisions":
        stmt = stmt.where(Rule.rule_type == RuleType.CHANNEL_MAP)
    return [rule_view(session, r) for r in session.scalars(stmt)]


# Rules propose, people approve (DECISIONS 2026-10-24). These kinds fill in the units of the files they match;
# nothing but a person's approval of a file writes the ``channel_map`` that Route C reads as an answer.
PROPOSING_RULE_TYPES = frozenset({RuleType.CHANNEL_PROPOSAL, RuleType.UNIT_MAPPING})


def _channel_entry(
    channel: str,
    quantity: str,
    unit: str,
    gauge_or_abs: str,
    expression: str | None,
    canonical_name: str | None = None,
) -> dict[str, Any]:
    try:
        known = Quantity(quantity)
    except ValueError as exc:
        raise InvalidAction(f"quantity {quantity!r} is not one of {[q.value for q in Quantity]}") from exc
    entry: dict[str, Any] = {
        "canonical_name": canonical_name or _slug(channel),
        "physical_quantity": known,
        "unit": unit,
        "gauge_or_abs": gauge_or_abs,
    }
    if expression:
        entry["expression"] = expression
    return entry


def _as_proposal(draft: RuleDraft) -> RuleDraft:
    """A ``unit_mapping`` (one channel's unit) is a proposal like any other unit rule."""
    if draft.rule_type != RuleType.UNIT_MAPPING:
        return draft
    unit = UnitMappingBody.model_validate(draft.body)
    body: dict[str, Any] = {
        "channels": {
            unit.channel: _channel_entry(
                unit.channel, unit.quantity, unit.unit, unit.gauge_or_abs, unit.expression
            )
        }
    }
    if unit.ambient_condition:
        body["ambient_condition"] = unit.ambient_condition
    if unit.ambient_pressure_bar_abs is not None:
        body["ambient_pressure_bar_abs"] = unit.ambient_pressure_bar_abs
    return draft.model_copy(update={"rule_type": RuleType.CHANNEL_PROPOSAL, "body": body})


def create_rule(session: Session, draft: RuleDraft, actor: str) -> Rule:
    """An operator rule (immutable; ``supersedes_rule_id`` deactivates the one it replaces)."""
    draft = _as_proposal(draft)
    body = draft.body
    if draft.rule_type in (RuleType.CHANNEL_MAP, RuleType.CHANNEL_PROPOSAL):
        body = ChannelMapBody.model_validate(body).model_dump(mode="json", exclude_none=True)
    rule = Rule(
        rule_type=draft.rule_type,
        origin=RuleOrigin.OPERATOR,
        **draft.scope.model_dump(),
        body=body,
        precedence=draft.precedence,
        supersedes_rule_id=draft.supersedes_rule_id,
        created_by=actor,
    )
    if draft.supersedes_rule_id:
        old = session.get(Rule, draft.supersedes_rule_id)
        if old is None:
            raise InvalidAction(f"rule {draft.supersedes_rule_id} does not exist")
        old.active = False
    session.add(rule)
    session.flush()
    _audit(
        session,
        actor,
        AuditEntityType.RULE,
        str(rule.rule_id),
        "create",
        None,
        {
            "rule_type": rule.rule_type,
            "scope": draft.scope.model_dump(),
            "body": body,
            "supersedes_rule_id": str(draft.supersedes_rule_id) if draft.supersedes_rule_id else None,
        },
    )
    return rule


def propose_rule(session: Session, rule: Rule) -> int:
    """Show a proposal on the waiting files it reaches; returns how many files carry it now. Nothing is
    approved: every file still waits for a person."""
    if rule.rule_type != RuleType.CHANNEL_PROPOSAL:
        return 0
    scope = RuleScope(
        scope_root=rule.scope_root,
        scope_folder_id=rule.scope_folder_id,
        scope_filename_glob=rule.scope_filename_glob,
        scope_extension=rule.scope_extension,
    )
    reached = refresh_proposals(
        session, [d.doc_id for d, _ in _matching_documents(session, scope, RuleType.CHANNEL_PROPOSAL)]
    )
    return len(reached.get(rule.rule_id, ()))


def deactivate_rule(session: Session, rule_id: uuid.UUID, actor: str) -> Rule:
    """Switch a rule off. A proposal stops being proposed (the files it reached get the pipeline's own hint
    back); decisions already made on files are never touched."""
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise CaseNotFound(f"rule {rule_id}")
    if rule.active:
        rule.active = False
        _audit(
            session,
            actor,
            AuditEntityType.RULE,
            str(rule_id),
            "deactivate",
            {"active": True},
            {"active": False},
        )
        if rule.rule_type == RuleType.CHANNEL_PROPOSAL:
            session.flush()
            carrying = {
                doc_id
                for doc_id in session.scalars(
                    select(ReviewFlag.doc_id).where(
                        ReviewFlag.proposed_by_rule_id == rule_id, ReviewFlag.status.in_(OPEN)
                    )
                )
                if doc_id
            }
            refresh_proposals(session, carrying)
    session.flush()
    return rule


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.casefold()).strip("_") or "channel"


def _channels_body(units: list[SetUnit]) -> dict[str, Any]:
    channels = {
        u.channel: _channel_entry(
            u.channel, u.quantity, u.unit, u.gauge_or_abs, u.expression, u.canonical_name
        )
        for u in units
    }
    body: dict[str, Any] = {"channels": channels}
    ambient = next((u for u in units if u.ambient_condition), None)
    if ambient:
        body["ambient_condition"] = ambient.ambient_condition
        if ambient.ambient_pressure_bar_abs is not None:
            body["ambient_pressure_bar_abs"] = ambient.ambient_pressure_bar_abs
    return ChannelMapBody.model_validate(body).model_dump(mode="json", exclude_none=True)


def _approval_draft(units: list[SetUnit], item: DriveItem) -> RuleDraft:
    """A person's approval of this file's columns: the channel_map Route C reads, for exactly this file."""
    return RuleDraft(
        rule_type=RuleType.CHANNEL_MAP,
        scope=RuleScope(
            scope_root=item.root_name, scope_folder_id=item.parent_item_id, scope_filename_glob=item.name
        ),
        body=_channels_body(units),
    )


def _proposal_draft(units: list[SetUnit], scope: RuleScope) -> RuleDraft:
    """The same units offered to other files: a proposal, which no route reads as an answer."""
    return RuleDraft(rule_type=RuleType.CHANNEL_PROPOSAL, scope=scope, body=_channels_body(units))


# ---------------------------------------------------------------- actions


@dataclass
class ResolveOutcome:
    flags: list[ReviewFlag]
    rule: Rule | None  # the proposal saved with this approval, if any
    resume_rule_id: uuid.UUID | None  # this file's approval: resumes this file only
    proposed_files: int = 0


def _settle_document(session: Session, doc_id: uuid.UUID | None) -> None:
    """ACTIVE_WITH_SOFT_FLAGS with no open flag left becomes ACTIVE (file 06 status invariant)."""
    if doc_id is None:
        return
    document = session.get(Document, doc_id)
    if document is None or document.status != DocumentStatus.ACTIVE_WITH_SOFT_FLAGS:
        return
    still_open = session.scalar(
        select(ReviewFlag.flag_id).where(ReviewFlag.doc_id == doc_id, ReviewFlag.status.in_(OPEN)).limit(1)
    )
    if still_open is None:
        document.status = DocumentStatus.ACTIVE


def resolve_case(
    session: Session, case_key: str, request: ResolveRequest, actor: str, is_admin: bool
) -> ResolveOutcome:
    case = _case(session, case_key)
    by_id = {f.flag_id: f for f in case.flags}
    try:
        check_actions(request.resolutions, {f.flag_id: FlagType(f.flag_type) for f in case.flags})
    except ValueError as exc:
        raise InvalidAction(str(exc)) from exc
    for item in request.resolutions:
        if not is_admin and item.resolution.action in {"approve_internal"}:
            raise InvalidAction(f"{item.resolution.action} needs the admin role")
        if by_id[item.flag_id].status not in OPEN:
            raise InvalidAction(f"flag {item.flag_id} is {by_id[item.flag_id].status}, not open")
    if request.rule is not None and request.rule.rule_type == RuleType.CHANNEL_MAP:
        raise InvalidAction("a file's columns are approved on the file, a rule can only propose them")

    first = case.flags[0]
    telemetry_units = [
        r.resolution
        for r in request.resolutions
        if isinstance(r.resolution, SetUnit) and (by_id[r.flag_id].anchor or {}).get("channel")
    ]
    approval = None
    if telemetry_units:
        ctx = _context(session, [case])
        item = ctx.items_by_doc.get(first.doc_id) if first.doc_id else None
        if item is None:
            raise InvalidAction("the case's file has no live location to scope an approval to")
        approval = create_rule(session, _approval_draft(telemetry_units, item), actor)
    proposal = None
    if request.rule is not None:
        proposal = create_rule(session, request.rule, actor)
    elif request.rule_scope is not None and telemetry_units:
        proposal = create_rule(session, _proposal_draft(telemetry_units, request.rule_scope), actor)
    recorded = approval or proposal

    now = datetime.now(UTC)
    for item in request.resolutions:
        flag = by_id[item.flag_id]
        before = {"status": flag.status, "resolution": flag.resolution}
        flag.status = FlagStatus.RESOLVED
        flag.resolution = item.resolution.model_dump(mode="json", exclude_none=True)
        flag.resolution_rule_id = recorded.rule_id if recorded else None
        flag.resolved_by, flag.resolved_at = actor, now
        after = {"status": flag.status, "resolution": flag.resolution, "comment": request.comment}
        if flag.proposed_by_rule_id:
            after["proposed_by_rule_id"] = str(flag.proposed_by_rule_id)
        _audit(session, actor, AuditEntityType.FLAG, str(flag.flag_id), "resolve", before, after)
    _audit(
        session,
        actor,
        AuditEntityType.CASE,
        case_key,
        "resolve",
        None,
        {
            "flags": [str(r.flag_id) for r in request.resolutions],
            "rule_id": str(approval.rule_id) if approval else None,
            "proposal_rule_id": str(proposal.rule_id) if proposal else None,
        },
    )
    _settle_document(session, first.doc_id)
    session.flush()
    proposed_files = propose_rule(session, proposal) if proposal is not None else 0
    return ResolveOutcome(case.flags, proposal, approval.rule_id if approval else None, proposed_files)


def reject_case(session: Session, case_key: str, request: RejectRequest, actor: str) -> _Case:
    """Skip or junk the file: every open flag REJECTED_FILE; the document leaves the index path
    (QUARANTINED, staged payload released); ``mark_junk`` also quarantines its OneDrive locations."""
    case = _case(session, case_key)
    now = datetime.now(UTC)
    for flag in case.open_flags:
        flag.status, flag.resolved_by, flag.resolved_at = FlagStatus.REJECTED_FILE, actor, now
        flag.resolution = {"action": request.action}
    first = case.flags[0]
    document = session.get(Document, first.doc_id) if first.doc_id else None
    before = {"document_status": document.status if document else None}
    if document is not None:
        document.status = DocumentStatus.QUARANTINED
        document.staged_payload_uri = None
    if request.action == "mark_junk":
        if first.doc_id:
            items = session.scalars(
                select(DriveItem)
                .join(DocumentSource, DocumentSource.blob_sha256 == DriveItem.blob_sha256)
                .where(
                    DocumentSource.doc_id == first.doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY
                )
            ).all()
        else:
            items = [i for i in [session.get(DriveItem, first.location_id)] if i]
        for item in items:
            if item.status != DriveItemStatus.DELETED:
                item.status, item.gate_reason = DriveItemStatus.QUARANTINED, "REVIEW:mark_junk"
    _audit(
        session,
        actor,
        AuditEntityType.CASE,
        case_key,
        request.action,
        before,
        {
            "document_status": document.status if document else None,
            "comment": request.comment,
        },
    )
    session.flush()
    return case


def assign_case(session: Session, case_key: str, assignee: str | None, actor: str) -> _Case:
    case = _case(session, case_key)
    before = next((f.assigned_to for f in case.open_flags if f.assigned_to), None)
    for flag in case.open_flags:
        flag.assigned_to = assignee
        if flag.status == FlagStatus.OPEN and assignee:
            flag.status = FlagStatus.IN_PROGRESS
        elif flag.status == FlagStatus.IN_PROGRESS and not assignee:
            flag.status = FlagStatus.OPEN
    _audit(
        session, actor, AuditEntityType.CASE, case_key, "assign", {"assignee": before}, {"assignee": assignee}
    )
    session.flush()
    return case


def summary_of(session: Session, case: _Case) -> CaseSummary:
    return _summary(case, _context(session, [case]))


# ---------------------------------------------------------------- simulate, dry run, undo

UNDO_WINDOW = timedelta(days=30)
SAMPLE = 20


def _matching_documents(
    session: Session, scope: RuleScope, rule_type: RuleType
) -> list[tuple[Document, Any]]:
    from backend.review.rules import RuleRecord, matches

    record = RuleRecord(
        rule_id=uuid.uuid4(),
        rule_type=rule_type,
        origin=RuleOrigin.OPERATOR,
        scope=scope,
        precedence=0,
        created_at=datetime.now(UTC),
    )
    routes = {
        RuleType.CHANNEL_MAP: ["C"],
        RuleType.CHANNEL_PROPOSAL: ["C"],
        RuleType.UNIT_MAPPING: ["C"],
        RuleType.SCHEMA_MAPPING: ["C"],
    }
    stmt = select(Document).where(Document.status.not_in(["SUPERSEDED", "DELETED", "QUARANTINED"]))
    if rule_type in routes:
        stmt = stmt.where(Document.route.in_(routes[rule_type]))
    found = []
    for document in session.scalars(stmt.order_by(Document.title)):
        target, where = _target_of(session, document)
        if target is not None and matches(record, target):
            found.append((document, where))
    return found


def _simulation_fields(found: list[tuple[Document, Any]]) -> dict[str, Any]:
    from backend.review.api_models import AffectedDocument

    waiting = [d for d, _ in found if d.status == DocumentStatus.HALTED]
    finished = [
        d for d, _ in found if d.status in (DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS)
    ]
    return {
        "matched_documents": len(found),
        "waiting_documents": len(waiting),
        "finished_documents": len(finished),
        "sample": [
            AffectedDocument(
                doc_id=d.doc_id, title=d.title or "", path=w.path_cached if w else None, status=d.status
            )
            for d, w in found[:SAMPLE]
        ],
    }


def simulate(session: Session, scope: RuleScope, rule_type: RuleType):
    """What a rule reaches: HALTED files that wait for it, files already processed."""
    from backend.review.api_models import RuleSimulation

    return RuleSimulation(**_simulation_fields(_matching_documents(session, scope, rule_type)))


def preview_rule(session: Session, request) -> "Any":
    """A rule that is not saved yet: which files it reaches, which columns they wait on, and whether the body
    is acceptable. A unit rule is previewed as the proposal it will be stored as."""
    from backend.review.api_models import OpenChannel, RulePreview

    rule_type = RuleType(request.rule_type)
    problem = None
    if request.body is not None:
        try:
            RULE_BODIES[rule_type].model_validate(request.body)
        except ValueError as exc:
            problem = str(exc)
    proposes = rule_type in PROPOSING_RULE_TYPES
    found = _matching_documents(session, request.scope, RuleType.CHANNEL_PROPOSAL if proposes else rule_type)
    waiting = Counter()
    ids = [d.doc_id for d, _ in found]
    if ids:
        for anchor in session.scalars(
            select(ReviewFlag.anchor).where(
                ReviewFlag.doc_id.in_(ids),
                ReviewFlag.flag_type == FlagType.UNIT_AMBIGUITY,
                ReviewFlag.status.in_(OPEN),
            )
        ):
            if (anchor or {}).get("channel"):
                waiting[anchor["channel"]] += 1
    return RulePreview(
        **_simulation_fields(found),
        effect="proposes" if proposes else "stored",
        open_channels=[OpenChannel(channel=c, files=n) for c, n in sorted(waiting.items())],
        problem=problem,
    )


def list_folders(session: Session, query: str, limit: int = 25):
    """Folders to scope a rule to. Without a query: the folders that hold halted telemetry files, most first;
    with one: folders whose path contains it."""
    from sqlalchemy import func

    from backend.postgres.models import DriveFolder
    from backend.review.api_models import FolderChoice, FolderList

    halted = dict(
        session.execute(
            select(DriveItem.parent_item_id, func.count(func.distinct(Document.doc_id)))
            .join(DocumentSource, DocumentSource.blob_sha256 == DriveItem.blob_sha256)
            .join(Document, Document.doc_id == DocumentSource.doc_id)
            .where(
                Document.route == "C",
                Document.status == DocumentStatus.HALTED,
                DocumentSource.role == DocumentSourceRole.PRIMARY,
                DriveItem.status != DriveItemStatus.DELETED,
            )
            .group_by(DriveItem.parent_item_id)
        ).all()
    )
    text = query.strip()
    if text:
        pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        folders = list(
            session.scalars(
                select(DriveFolder)
                .where(DriveFolder.path_cached.ilike(pattern, escape="\\"))
                .order_by(DriveFolder.path_cached)
                .limit(limit)
            )
        )
    else:
        wanted = sorted(halted, key=lambda f: -halted[f])[:limit]
        by_id = {
            f.item_id: f for f in session.scalars(select(DriveFolder).where(DriveFolder.item_id.in_(wanted)))
        }
        folders = [by_id[f] for f in wanted if f in by_id]
    counts = dict(
        session.execute(
            select(DriveItem.parent_item_id, func.count())
            .where(
                DriveItem.parent_item_id.in_([f.item_id for f in folders]),
                DriveItem.status != DriveItemStatus.DELETED,
            )
            .group_by(DriveItem.parent_item_id)
        ).all()
    )
    return FolderList(
        items=[
            FolderChoice(
                folder_id=f.item_id,
                root_name=f.root_name,
                path=f.path_cached or f.name,
                files=counts.get(f.item_id, 0),
                waiting=halted.get(f.item_id, 0),
            )
            for f in folders
        ]
    )


def simulate_rule(session: Session, rule_id: uuid.UUID):
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise CaseNotFound(f"rule {rule_id}")
    scope = RuleScope(
        scope_root=rule.scope_root,
        scope_folder_id=rule.scope_folder_id,
        scope_filename_glob=rule.scope_filename_glob,
        scope_extension=rule.scope_extension,
    )
    return simulate(session, scope, RuleType(rule.rule_type))


def dry_run(session: Session, request) -> "Any":
    """Apply a candidate resolution to what the route staged, commit nothing: for a telemetry ``set_unit``
    the channel's recorded stats converted to SI and checked against S5's sanity range; for a rule, the
    number of documents it would touch. Other actions have no numeric preview yet."""
    from backend.dispatcher.contract import UnitTelemetryEvidence
    from backend.postgres import pipeline_config
    from backend.review.api_models import ChannelPreview, DryRunResponse
    from backend.review.rules import ChannelMapEntry
    from backend.routes.c_telemetry.normalize import (
        PlanProblem,
        matching_range,
        plan_channel,
        sanity_ranges_from,
    )

    case = _case(session, request.case_key)
    flag = next((f for f in case.flags if f.flag_id == request.resolution.flag_id), None)
    if flag is None:
        raise InvalidAction(f"flag {request.resolution.flag_id} is not part of this case")
    check_actions([request.resolution], {flag.flag_id: FlagType(flag.flag_type)})
    resolution = request.resolution.resolution
    channels, messages = [], []
    if isinstance(resolution, SetUnit) and (flag.anchor or {}).get("channel"):
        evidence = UnitTelemetryEvidence.model_validate(flag.evidence or {"channel": resolution.channel})
        try:
            quantity = Quantity(resolution.quantity)
        except ValueError as exc:
            raise InvalidAction(f"quantity {resolution.quantity!r} is not a known quantity") from exc
        entry = ChannelMapEntry(
            canonical_name=_slug(resolution.channel),
            physical_quantity=quantity,
            unit=resolution.unit,
            gauge_or_abs=resolution.gauge_or_abs,
            expression=resolution.expression,
        )
        plan = plan_channel(
            resolution.channel, entry, resolution.ambient_condition, resolution.ambient_pressure_bar_abs
        )
        if isinstance(plan, PlanProblem):
            messages.append(plan.reason)
        else:
            import numpy as np

            stats = evidence.stats
            raw = np.array(
                [v if v is not None else np.nan for v in (stats.min, stats.max, stats.mean, stats.p99)]
            )
            low, high, mean, p99 = (None if np.isnan(v) else float(v) for v in plan.convert(raw))
            ranges = sanity_ranges_from(
                pipeline_config.get(session, pipeline_config.SANITY_RANGES, default=None)
            )
            sanity = matching_range(ranges, quantity.value, entry.canonical_name)
            s_low = s_high = None
            within = None
            if sanity is not None:
                from backend.common.units import to_canonical

                s_low, s_high = (
                    to_canonical(sanity.min, sanity.unit)[0],
                    to_canonical(sanity.max, sanity.unit)[0],
                )
                within = all(v is None or s_low <= v <= s_high for v in (low, high))
            channels.append(
                ChannelPreview(
                    canonical_name=entry.canonical_name,
                    unit_si=plan.unit_si,
                    stat_min=low,
                    stat_max=high,
                    stat_mean=mean,
                    stat_p99=p99,
                    sanity_min=s_low,
                    sanity_max=s_high,
                    within_sanity=within,
                )
            )
            if stats.n is None:
                messages.append("the flag carries no recorded stats; the preview converts nothing")
    else:
        messages.append(f"no numeric preview for {resolution.action}")
    affected = 1
    if request.rule is not None:
        affected = simulate(session, request.rule.scope, request.rule.rule_type).matched_documents
    return DryRunResponse(channels=channels, affected_documents=affected, messages=messages)


def _restore_junked_locations(session: Session, first: ReviewFlag) -> None:
    """Undo of "mark junk": locations the review quarantined go back to LANDED."""
    if first.doc_id:
        items = session.scalars(
            select(DriveItem)
            .join(DocumentSource, DocumentSource.blob_sha256 == DriveItem.blob_sha256)
            .where(DocumentSource.doc_id == first.doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY)
        ).all()
    else:
        items = [i for i in [session.get(DriveItem, first.location_id)] if i]
    for item in items:
        if item.gate_reason == "REVIEW:mark_junk":
            item.status, item.gate_reason = DriveItemStatus.LANDED, None


@dataclass
class UndoOutcome:
    reopened: list[ReviewFlag]
    rebuild_doc_id: uuid.UUID | None
    deactivated_rule_id: uuid.UUID | None


def _release_rule(session: Session, rule_id: uuid.UUID, actor: str) -> uuid.UUID | None:
    """Flags just gave up their reliance on a file approval. If no flag relies on it any more it is switched
    off (returned); if some still do and it names channels they do not, a narrower approval of only theirs
    replaces it, so a reopened channel is asked again instead of being answered by the old approval."""
    old = session.get(Rule, rule_id)
    if old is None or not old.active:
        return None
    remaining = list(
        session.scalars(
            select(ReviewFlag).where(
                ReviewFlag.resolution_rule_id == rule_id, ReviewFlag.status == FlagStatus.RESOLVED
            )
        )
    )
    if not remaining:
        deactivate_rule(session, rule_id, actor)
        return rule_id
    if old.rule_type != RuleType.CHANNEL_MAP:
        return None
    keep = {(f.anchor or {}).get("channel") for f in remaining}
    channels = {c: e for c, e in old.body["channels"].items() if c in keep}
    if channels == old.body["channels"]:
        return None
    narrower = create_rule(
        session,
        RuleDraft(
            rule_type=RuleType.CHANNEL_MAP,
            scope=RuleScope(
                scope_root=old.scope_root,
                scope_folder_id=old.scope_folder_id,
                scope_filename_glob=old.scope_filename_glob,
                scope_extension=old.scope_extension,
            ),
            body={**old.body, "channels": channels},
            supersedes_rule_id=old.rule_id,
        ),
        actor,
    )
    for flag in remaining:
        flag.resolution_rule_id = narrower.rule_id
    return None


def _reopen(
    session: Session,
    case: _Case,
    case_key: str,
    batch: list[ReviewFlag],
    actor: str,
    action: str,
    reason: str | None,
) -> UndoOutcome:
    junk_ids = {f.flag_id for f in batch if (f.resolution or {}).get("action") == "mark_junk"}
    rule_ids = {f.resolution_rule_id for f in batch if f.resolution_rule_id}
    # A rule that answered these flags without a person (the old flow) and is still on would answer them
    # again at once when the file is rebuilt; taking the decision back switches it off.
    batch_ids = {f.flag_id for f in batch}
    still_applied = {
        u.rule_id for u in _applied_units(session, case) if u.flag_id in batch_ids and u.rule_active
    }
    why = {"reason": reason} if reason else {}
    for flag in batch:
        before = {"status": flag.status, "resolution": flag.resolution}
        flag.status, flag.resolution, flag.resolution_rule_id = FlagStatus.REOPENED, None, None
        flag.resolved_by = flag.resolved_at = None
        _audit(
            session,
            actor,
            AuditEntityType.FLAG,
            str(flag.flag_id),
            action,
            before,
            {"status": flag.status, **why},
        )
    session.flush()
    deactivated = None
    for rule_id in rule_ids:
        deactivated = _release_rule(session, rule_id, actor) or deactivated
    for rule_id in still_applied:
        deactivate_rule(session, rule_id, actor)
        deactivated = rule_id
    first = case.flags[0]
    if [f for f in batch if f.flag_id in junk_ids]:
        _restore_junked_locations(session, first)
    document = session.get(Document, first.doc_id) if first.doc_id else None
    rebuild = None
    if document is not None and document.status in (
        DocumentStatus.ACTIVE,
        DocumentStatus.ACTIVE_WITH_SOFT_FLAGS,
        DocumentStatus.QUARANTINED,
    ):
        document.status = DocumentStatus.PROCESSING
        rebuild = document.doc_id
    _audit(
        session,
        actor,
        AuditEntityType.CASE,
        case_key,
        action,
        None,
        {
            "flags": [str(f.flag_id) for f in batch],
            "rebuild_doc_id": str(rebuild) if rebuild else None,
            **why,
        },
    )
    session.flush()
    return UndoOutcome(batch, rebuild, deactivated)


def undo_case(session: Session, case_key: str, actor: str, now: datetime | None = None) -> UndoOutcome:
    """Re-open the flags of the case's last resolution (within 30 days, file 06 §6). A rule that only this
    resolution used is deactivated; a committed document is rebuilt at once without the overlay or rule."""
    now = now or datetime.now(UTC)
    case = _case(session, case_key)
    resolved = [
        f for f in case.flags if f.status in (FlagStatus.RESOLVED, FlagStatus.REJECTED_FILE) and f.resolved_at
    ]
    if not resolved:
        raise InvalidAction("nothing to undo: no resolved flag in this case")
    last = max(f.resolved_at for f in resolved)
    if now - last > UNDO_WINDOW:
        raise InvalidAction("the last resolution is older than 30 days")
    batch = [f for f in resolved if f.resolved_at == last]
    return _reopen(session, case, case_key, batch, actor, "undo", None)


def reopen_flags(
    session: Session, case_key: str, flag_ids: list[uuid.UUID], reason: str, actor: str
) -> UndoOutcome:
    """Take back chosen decisions of any flag type, whenever they were made, so the file is decided again
    (the Audit page). Unlike undo it is not limited to the last resolution or to 30 days."""
    case = _case(session, case_key)
    by_id = {f.flag_id: f for f in case.flags}
    batch = []
    for flag_id in dict.fromkeys(flag_ids):
        flag = by_id.get(flag_id)
        if flag is None:
            raise InvalidAction(f"flag {flag_id} is not part of this case")
        if flag.status not in DECIDED:
            raise InvalidAction(f"flag {flag_id} is {flag.status}: only a decided flag can be reopened")
        batch.append(flag)
    return _reopen(session, case, case_key, batch, actor, "reopen", reason)


@dataclass
class EditOutcome:
    flags: list[ReviewFlag]
    rebuild_doc_id: uuid.UUID | None
    resume_rule_id: uuid.UUID | None


def edit_case(session: Session, case_key: str, request: EditRequest, actor: str) -> EditOutcome:
    """Change the unit of channels a person already decided (the Audit page). The file's approval is replaced
    by a new one (the old is kept, switched off), each edited flag records the actor and the written reason,
    and the file is rebuilt with the new units."""
    case = _case(session, case_key)
    by_id = {f.flag_id: f for f in case.flags}
    try:
        check_actions(request.resolutions, {f.flag_id: FlagType(f.flag_type) for f in case.flags})
    except ValueError as exc:
        raise InvalidAction(str(exc)) from exc
    edited: dict[uuid.UUID, SetUnit] = {}
    for item in request.resolutions:
        flag = by_id[item.flag_id]
        if flag.status not in (FlagStatus.RESOLVED, FlagStatus.AUTO_RESOLVED):
            raise InvalidAction(f"flag {flag.flag_id} is {flag.status}: only a decided flag is edited here")
        if not isinstance(item.resolution, SetUnit) or not (flag.anchor or {}).get("channel"):
            raise InvalidAction(
                "only the unit of a telemetry channel is edited in place; reopen any other flag"
            )
        edited[flag.flag_id] = item.resolution
    first = case.flags[0]
    ctx = _context(session, [case])
    location = ctx.items_by_doc.get(first.doc_id) if first.doc_id else None
    if location is None:
        raise InvalidAction("the case's file has no live location to scope an approval to")

    applied = {u.flag_id: u for u in _applied_units(session, case)}
    decided = [
        f
        for f in case.flags
        if f.flag_type == FlagType.UNIT_AMBIGUITY
        and (f.anchor or {}).get("channel")
        and (
            (f.status == FlagStatus.RESOLVED and (f.resolution or {}).get("action") == "set_unit")
            or (f.status == FlagStatus.AUTO_RESOLVED and f.flag_id in applied)
        )
    ]

    def current(flag: ReviewFlag) -> SetUnit:
        if flag.status == FlagStatus.RESOLVED:
            return SetUnit.model_validate(flag.resolution)
        a = applied[flag.flag_id]
        return SetUnit(
            channel=a.channel,
            unit=a.unit,
            quantity=a.quantity,
            gauge_or_abs=a.gauge_or_abs,
            ambient_condition=a.ambient_condition,
            canonical_name=a.canonical_name,
        )

    current_of = {f.flag_id: current(f) for f in decided}
    approved_by_rule = {fid: u.rule_id for fid, u in applied.items()}
    units = [edited.get(f.flag_id) or current_of[f.flag_id] for f in decided]
    old_rule_ids = [rid for rid in dict.fromkeys(f.resolution_rule_id for f in decided) if rid]
    draft = _approval_draft(units, location)
    if old_rule_ids:
        draft = draft.model_copy(update={"supersedes_rule_id": old_rule_ids[0]})
    approval = create_rule(session, draft, actor)
    for rule_id in old_rule_ids[1:]:
        deactivate_rule(session, rule_id, actor)

    now = datetime.now(UTC)
    for flag in decided:
        before = {
            "status": flag.status,
            "resolution": flag.resolution
            or current_of[flag.flag_id].model_dump(mode="json", exclude_none=True),
            "resolved_by": flag.resolved_by,
            "rule_id": str(flag.resolution_rule_id or approved_by_rule.get(flag.flag_id)),
        }
        if flag.flag_id in edited or flag.status == FlagStatus.AUTO_RESOLVED:
            # the editor now stands behind this unit, whether they changed it or confirmed what a rule applied
            flag.status = FlagStatus.RESOLVED
            flag.resolution = (edited.get(flag.flag_id) or current_of[flag.flag_id]).model_dump(
                mode="json", exclude_none=True
            )
            flag.resolved_by, flag.resolved_at = actor, now
            _audit(
                session,
                actor,
                AuditEntityType.FLAG,
                str(flag.flag_id),
                "edit",
                before,
                {
                    "resolution": flag.resolution,
                    "resolved_by": actor,
                    "rule_id": str(approval.rule_id),
                    "reason": request.reason,
                },
            )
        flag.resolution_rule_id = approval.rule_id
    document = session.get(Document, first.doc_id) if first.doc_id else None
    rebuild = resume = None
    if document is not None and document.status in (
        DocumentStatus.ACTIVE,
        DocumentStatus.ACTIVE_WITH_SOFT_FLAGS,
    ):
        document.status = DocumentStatus.PROCESSING
        rebuild = document.doc_id
    elif document is not None and document.status == DocumentStatus.HALTED:
        resume = approval.rule_id
    _audit(
        session,
        actor,
        AuditEntityType.CASE,
        case_key,
        "edit",
        {"rule_ids": [str(r) for r in old_rule_ids]},
        {
            "flags": [str(f) for f in edited],
            "rule_id": str(approval.rule_id),
            "rebuild_doc_id": str(rebuild) if rebuild else None,
            "reason": request.reason,
        },
    )
    session.flush()
    return EditOutcome(case.flags, rebuild, resume)
