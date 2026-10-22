"""Review cases over ``review_flags`` (file 06 §5–§8, file 08 §4): queue, detail, resolve, reject, assign.

A case is the group of flags sharing ``case_key``; its status is derived from its flags (file 08 §4.3).
Every human action writes ``audit_events``. A telemetry ``set_unit`` always ends in an operator
``channel_map`` rule (file 06 §6): the reviewer's rule when given, else one scoped to this file; the
caller then starts ``dcl.process.resume_for_rule`` so this document and every HALTED sibling the rule
matches re-run from their staged data. Dry run and undo are not here yet (the router answers 501).
"""

import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

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
    CaseDetail,
    CaseFilters,
    CaseList,
    CaseLocation,
    CaseSummary,
    FlagView,
    RejectRequest,
    ResolveRequest,
    RuleDraft,
    RuleView,
    allowed_actions_for,
    check_actions,
)
from backend.review.rules import ChannelMapBody, RuleScope

OPEN = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)
SEVERITY_RANK = {FlagSeverity.HARD: 0, FlagSeverity.SOFT: 1}


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
        route=Route(document.route)
        if document and document.route
        else (Route(first.route) if first.route else None),
        status=case.status,
        max_severity=max_severity,
        flag_counts=dict(Counter(FlagType(f.flag_type) for f in counted)),
        assignee=next((f.assigned_to for f in case.open_flags if f.assigned_to), None),
        oldest_created_at=min(f.created_at for f in case.flags),
        has_suggestion=any(f.suggested_resolution for f in counted),
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
    wanted = (
        {filters.status} if filters.status else {CaseStatus.OPEN, CaseStatus.IN_PROGRESS, CaseStatus.REOPENED}
    )
    if summary.status not in wanted:
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
            **{c: getattr(flag, c) for c in FlagView.model_fields if c != "allowed_actions"},
            "allowed_actions": allowed_actions_for(FlagType(flag.flag_type), is_admin),
        }
    )


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
    )


# ---------------------------------------------------------------- rules


def rule_view(session: Session, rule: Rule) -> RuleView:
    from sqlalchemy import func

    from backend.postgres.models import TelemetryRun

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
        flags_resolved=session.scalar(
            select(func.count()).where(ReviewFlag.resolution_rule_id == rule.rule_id)
        )
        or 0,
        runs_mapped=session.scalar(
            select(func.count()).where(TelemetryRun.channel_map_rule_id == rule.rule_id)
        )
        or 0,
    )


def list_rules(session: Session, active: bool | None) -> list[RuleView]:
    stmt = select(Rule).order_by(Rule.created_at.desc())
    if active is not None:
        stmt = stmt.where(Rule.active.is_(active))
    return [rule_view(session, r) for r in session.scalars(stmt)]


def create_rule(session: Session, draft: RuleDraft, actor: str) -> Rule:
    """An operator rule (immutable; ``supersedes_rule_id`` deactivates the one it replaces)."""
    body = draft.body
    if draft.rule_type == RuleType.CHANNEL_MAP:
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


def deactivate_rule(session: Session, rule_id: uuid.UUID, actor: str) -> Rule:
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
    session.flush()
    return rule


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", text.casefold()).strip("_") or "channel"


def _file_scoped_channel_map(units: list[SetUnit], item: DriveItem) -> RuleDraft:
    """The operator rule a 'this file' unit decision becomes: one channel_map for exactly this file."""
    channels: dict[str, Any] = {}
    for u in units:
        try:
            quantity = Quantity(u.quantity)
        except ValueError as exc:
            raise InvalidAction(
                f"quantity {u.quantity!r} is not one of {[q.value for q in Quantity]}"
            ) from exc
        entry: dict[str, Any] = {
            "canonical_name": _slug(u.channel),
            "physical_quantity": quantity,
            "unit": u.unit,
            "gauge_or_abs": u.gauge_or_abs,
        }
        if u.expression:
            entry["expression"] = u.expression
        channels[u.channel] = entry
    body: dict[str, Any] = {"channels": channels}
    ambient = next((u for u in units if u.ambient_condition), None)
    if ambient:
        body["ambient_condition"] = ambient.ambient_condition
        if ambient.ambient_pressure_bar_abs is not None:
            body["ambient_pressure_bar_abs"] = ambient.ambient_pressure_bar_abs
    return RuleDraft(
        rule_type=RuleType.CHANNEL_MAP,
        scope=RuleScope(
            scope_root=item.root_name, scope_folder_id=item.parent_item_id, scope_filename_glob=item.name
        ),
        body=ChannelMapBody.model_validate(body).model_dump(mode="json", exclude_none=True),
    )


# ---------------------------------------------------------------- actions


@dataclass
class ResolveOutcome:
    flags: list[ReviewFlag]
    rule: Rule | None
    resume_rule_id: uuid.UUID | None


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

    first = case.flags[0]
    telemetry_units = [
        r.resolution
        for r in request.resolutions
        if isinstance(r.resolution, SetUnit) and (by_id[r.flag_id].anchor or {}).get("channel")
    ]
    draft = request.rule
    if draft is None and telemetry_units:
        ctx = _context(session, [case])
        item = ctx.items_by_doc.get(first.doc_id) if first.doc_id else None
        if item is None:
            raise InvalidAction("the case's file has no live location to scope a rule to")
        draft = _file_scoped_channel_map(telemetry_units, item)
    rule = create_rule(session, draft, actor) if draft else None

    now = datetime.now(UTC)
    for item in request.resolutions:
        flag = by_id[item.flag_id]
        before = {"status": flag.status, "resolution": flag.resolution}
        flag.status = FlagStatus.RESOLVED
        flag.resolution = item.resolution.model_dump(mode="json", exclude_none=True)
        flag.resolution_rule_id = rule.rule_id if rule else None
        flag.resolved_by, flag.resolved_at = actor, now
        after = {"status": flag.status, "resolution": flag.resolution, "comment": request.comment}
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
            "rule_id": str(rule.rule_id) if rule else None,
        },
    )
    _settle_document(session, first.doc_id)
    session.flush()
    resume = rule.rule_id if rule is not None and rule.rule_type == RuleType.CHANNEL_MAP else None
    return ResolveOutcome(case.flags, rule, resume)


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
