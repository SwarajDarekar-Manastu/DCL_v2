"""S1: review cases, flags and rules (file 08 §4.4, file 06 §5–§8). Thin router over backend/review/cases.py.

Reviewer role. ``GET /review/cases`` lists open cases by default (``status`` selects another), sorted by
impact (halted files in the same folder), age or severity, with an offset cursor. Rules propose and people
approve (DECISIONS 2026-10-24): resolving a telemetry ``set_unit`` writes the file's own ``channel_map``
approval (Route C's only answer) and resumes that file; ``rule_scope`` also saves a ``channel_proposal`` that
fills in the other waiting files, which stay open. ``POST /rules`` saves a proposal and resumes nothing.
Undo re-opens the last resolution (30 days); ``reopen`` and ``edit`` change any decision later, with a
written reason (the Audit page); dry run previews a unit decision against the sanity ranges.
"""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.postgres.session import get_session
from backend.review import cases
from backend.review.api_models import (
    AssignRequest,
    CaseDetail,
    CaseFilters,
    CaseList,
    CaseSummary,
    DryRunRequest,
    DryRunResponse,
    EditRequest,
    EditResponse,
    FolderList,
    RejectRequest,
    ReopenRequest,
    ReopenResponse,
    ResolveRequest,
    ResolveResponse,
    RuleCreated,
    RuleDraft,
    RuleList,
    RulePreview,
    RulePreviewRequest,
    RuleSimulation,
    RuleView,
    UndoResponse,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/review", tags=["review"])

Reviewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]
Db = Annotated[Session, Depends(get_session)]


def start_resume(rule_id: uuid.UUID) -> bool:
    """Best effort: a missed start leaves the documents HALTED with resolved flags; re-run resume_for_rule."""
    try:
        from backend.celery_redis.app import app

        app.send_task("dcl.process.resume_for_rule", args=[str(rule_id)], queue="io_light")
        return True
    except Exception:
        log.warning("could not start resume_for_rule for %s", rule_id, exc_info=True)
        return False


def _actor(user: ConsoleUser) -> str:
    return user.email or user.oid


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{exc} not found")


@router.get("/cases")
def list_cases(user: Reviewer, session: Db, filters: Annotated[CaseFilters, Query()]) -> CaseList:
    return cases.list_cases(session, filters)


@router.get("/cases/{case_key}")
def get_case(user: Reviewer, session: Db, case_key: str) -> CaseDetail:
    try:
        return cases.case_detail(session, case_key, user.has(ConsoleRole.ADMIN))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/cases/{case_key}/assign")
def assign_case(user: Reviewer, session: Db, case_key: str, body: AssignRequest) -> CaseSummary:
    try:
        case = cases.assign_case(session, case_key, body.assignee, _actor(user))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    session.commit()
    return cases.summary_of(session, case)


@router.post("/cases/{case_key}/resolve")
def resolve_case(user: Reviewer, session: Db, case_key: str, body: ResolveRequest) -> ResolveResponse:
    admin = user.has(ConsoleRole.ADMIN)
    try:
        outcome = cases.resolve_case(session, case_key, body, _actor(user), admin)
    except cases.CaseNotFound as exc:
        session.rollback()
        raise _not_found(exc) from exc
    except (cases.InvalidAction, ValueError) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    resumed: list[uuid.UUID] = []
    if outcome.resume_rule_id is not None:
        from backend.routes.c_telemetry.pipeline import halted_documents_for_rule

        resumed = halted_documents_for_rule(session, outcome.resume_rule_id)
        if resumed:
            start_resume(outcome.resume_rule_id)
    return ResolveResponse(
        case_key=case_key,
        flags=[cases.flag_view(f, admin) for f in outcome.flags],
        rule=cases.rule_view(session, outcome.rule) if outcome.rule else None,
        resumed_doc_ids=resumed,
        proposed_files=outcome.proposed_files,
    )


@router.post("/cases/{case_key}/reject")
def reject_case(user: Reviewer, session: Db, case_key: str, body: RejectRequest) -> CaseSummary:
    try:
        case = cases.reject_case(session, case_key, body, _actor(user))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    session.commit()
    return cases.summary_of(session, case)


def start_rebuild(doc_id: uuid.UUID, route: str | None) -> bool:
    """Best effort: the document is PROCESSING; a missed start is picked up by a re-dispatch."""
    from backend.dispatcher.adapters import task_for_route
    from backend.postgres.enums import Route

    found = task_for_route(Route(route)) if route else None
    if found is None:
        return False
    try:
        from backend.celery_redis.app import app

        app.send_task(found[0], args=[str(doc_id)], queue=str(found[1]))
        return True
    except Exception:
        log.warning("could not start the rebuild of %s", doc_id, exc_info=True)
        return False


@router.post("/cases/{case_key}/undo")
def undo_case(user: Reviewer, session: Db, case_key: str) -> UndoResponse:
    try:
        outcome = cases.undo_case(session, case_key, _actor(user))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    except cases.InvalidAction as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    session.commit()
    if outcome.rebuild_doc_id is not None:
        from backend.postgres.models import Document

        start_rebuild(outcome.rebuild_doc_id, session.get(Document, outcome.rebuild_doc_id).route)
    return UndoResponse(
        case_key=case_key,
        reopened_flag_ids=[f.flag_id for f in outcome.reopened],
        rebuild_doc_id=outcome.rebuild_doc_id,
    )


@router.post("/cases/{case_key}/reopen")
def reopen_case(user: Reviewer, session: Db, case_key: str, body: ReopenRequest) -> ReopenResponse:
    """Take back decisions of any flag type so the file is decided again; reason and actor are audited."""
    try:
        outcome = cases.reopen_flags(session, case_key, body.flag_ids, body.reason, _actor(user))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    except cases.InvalidAction as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    if outcome.rebuild_doc_id is not None:
        from backend.postgres.models import Document

        start_rebuild(outcome.rebuild_doc_id, session.get(Document, outcome.rebuild_doc_id).route)
    return ReopenResponse(
        case_key=case_key,
        reopened_flag_ids=[f.flag_id for f in outcome.reopened],
        rebuild_doc_id=outcome.rebuild_doc_id,
    )


@router.post("/cases/{case_key}/edit")
def edit_case(user: Reviewer, session: Db, case_key: str, body: EditRequest) -> EditResponse:
    """Change the unit of channels already decided; the file is rebuilt. The reason and actor are audited."""
    try:
        outcome = cases.edit_case(session, case_key, body, _actor(user))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    except (cases.InvalidAction, ValueError) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    resumed: list[uuid.UUID] = []
    if outcome.rebuild_doc_id is not None:
        from backend.postgres.models import Document

        start_rebuild(outcome.rebuild_doc_id, session.get(Document, outcome.rebuild_doc_id).route)
    elif outcome.resume_rule_id is not None:
        from backend.routes.c_telemetry.pipeline import halted_documents_for_rule

        resumed = halted_documents_for_rule(session, outcome.resume_rule_id)
        if resumed:
            start_resume(outcome.resume_rule_id)
    return EditResponse(
        case_key=case_key,
        flags=[cases.flag_view(f, user.has(ConsoleRole.ADMIN)) for f in outcome.flags],
        rebuild_doc_id=outcome.rebuild_doc_id,
        resumed_doc_ids=resumed,
    )


@router.post("/dry-run")
def dry_run(user: Reviewer, session: Db, body: DryRunRequest) -> DryRunResponse:
    try:
        return cases.dry_run(session, body)
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    except (cases.InvalidAction, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/rules")
def list_rules(
    user: Reviewer, session: Db, active: bool | None = None, kind: Literal["rules", "decisions"] | None = None
) -> RuleList:
    """``kind=rules``: proposals and kinds nothing reads yet; ``kind=decisions``: the approvals of files."""
    return RuleList(items=cases.list_rules(session, active, kind))


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(user: Reviewer, session: Db, body: RuleDraft) -> RuleCreated:
    """Save a rule. A unit rule is a proposal: the waiting files it matches show its units and stay open until
    a person approves each. A channel map is a file's approval and is never made by a rule."""
    if body.rule_type == "channel_map":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "a file's columns are approved on the file; a rule can only propose them",
        )
    try:
        rule = cases.create_rule(session, body, _actor(user))
        proposed = cases.propose_rule(session, rule)
    except (cases.InvalidAction, ValueError) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    return RuleCreated(**cases.rule_view(session, rule).model_dump(), proposed_files=proposed)


@router.post("/rules/preview")
def preview_rule(user: Reviewer, session: Db, body: RulePreviewRequest) -> RulePreview:
    """What a rule would do before it is saved: files matched, files that resume, the columns they wait on."""
    return cases.preview_rule(session, body)


@router.get("/folders")
def list_folders(
    user: Reviewer, session: Db, q: str = "", limit: Annotated[int, Query(ge=1, le=50)] = 25
) -> FolderList:
    """Folders to scope a rule to; without ``q`` the ones that hold halted telemetry files, most first."""
    return cases.list_folders(session, q, limit)


@router.post("/rules/{rule_id}/simulate")
def simulate_rule(user: Reviewer, session: Db, rule_id: uuid.UUID) -> RuleSimulation:
    try:
        return cases.simulate_rule(session, rule_id)
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/rules/{rule_id}/deactivate")
def deactivate_rule(user: Reviewer, session: Db, rule_id: uuid.UUID) -> RuleView:
    try:
        rule = cases.deactivate_rule(session, rule_id, _actor(user))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    session.commit()
    return cases.rule_view(session, rule)
