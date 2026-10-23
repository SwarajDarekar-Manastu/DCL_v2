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

log = logging.getLogger(__name__)
OPEN = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)
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
            **{c: getattr(flag, c) for c in FlagView.model_fields if c not in ("allowed_actions", "route")},
            "route": _route(flag.route, f"flag {flag.flag_id}"),
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


# ---------------------------------------------------------------- simulate, dry run, undo

UNDO_WINDOW = timedelta(days=30)
SAMPLE = 20


def _target_of(session: Session, document: Document):
    """The rule target of a document's primary file (derived blobs use their parent's location)."""
    from backend.dispatcher.location import primary_location
    from backend.review.rules import RuleTarget

    sha = session.scalar(
        select(DocumentSource.blob_sha256).where(
            DocumentSource.doc_id == document.doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY
        )
    )
    where = primary_location(session, sha) if sha else None
    if where is None:
        return None, None
    folders: list[str] = []
    parent = where.parent_item_id
    from backend.postgres.models import DriveFolder

    while parent and len(folders) < 64:
        folders.append(parent)
        parent = session.scalar(select(DriveFolder.parent_item_id).where(DriveFolder.item_id == parent))
    return RuleTarget(where.root_name, folders, where.name, where.extension), where


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
    routes = {RuleType.CHANNEL_MAP: ["C"], RuleType.UNIT_MAPPING: ["C"], RuleType.SCHEMA_MAPPING: ["C"]}
    stmt = select(Document).where(Document.status.not_in(["SUPERSEDED", "DELETED", "QUARANTINED"]))
    if rule_type in routes:
        stmt = stmt.where(Document.route.in_(routes[rule_type]))
    found = []
    for document in session.scalars(stmt.order_by(Document.title)):
        target, where = _target_of(session, document)
        if target is not None and matches(record, target):
            found.append((document, where))
    return found


def simulate(session: Session, scope: RuleScope, rule_type: RuleType):
    """What a rule would touch: HALTED documents it resumes, committed ones it re-processes."""
    from backend.review.api_models import AffectedDocument, RuleSimulation

    found = _matching_documents(session, scope, rule_type)
    resume = [d for d, _ in found if d.status == DocumentStatus.HALTED]
    reprocess = [
        d for d, _ in found if d.status in (DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS)
    ]
    return RuleSimulation(
        matched_documents=len(found),
        would_resume=len(resume),
        would_reprocess=len(reprocess),
        sample=[
            AffectedDocument(
                doc_id=d.doc_id, title=d.title or "", path=w.path_cached if w else None, status=d.status
            )
            for d, w in found[:SAMPLE]
        ],
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
    junk_ids = {f.flag_id for f in batch if (f.resolution or {}).get("action") == "mark_junk"}
    rule_ids = {f.resolution_rule_id for f in batch if f.resolution_rule_id}
    for flag in batch:
        before = {"status": flag.status, "resolution": flag.resolution}
        flag.status, flag.resolution, flag.resolution_rule_id = FlagStatus.REOPENED, None, None
        flag.resolved_by = flag.resolved_at = None
        _audit(
            session, actor, AuditEntityType.FLAG, str(flag.flag_id), "undo", before, {"status": flag.status}
        )
    deactivated = None
    for rule_id in rule_ids:
        still_used = session.scalar(
            select(ReviewFlag.flag_id).where(ReviewFlag.resolution_rule_id == rule_id).limit(1)
        )
        if still_used is None:
            deactivate_rule(session, rule_id, actor)
            deactivated = rule_id
    first = case.flags[0]
    junked = [f for f in batch if f.flag_id in junk_ids]
    if junked:
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
        "undo",
        None,
        {
            "flags": [str(f.flag_id) for f in batch],
            "rebuild_doc_id": str(rebuild) if rebuild else None,
        },
    )
    session.flush()
    return UndoOutcome(batch, rebuild, deactivated)
