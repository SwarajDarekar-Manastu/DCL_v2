"""S1: review cases, flags and rules (file 08 §4.4, file 06 §5–§8). Thin router over backend/review/cases.py.

Reviewer role. ``GET /review/cases`` lists open cases by default (``status`` selects another), sorted by
impact (halted files in the same folder), age or severity, with an offset cursor. Resolving a telemetry
``set_unit`` writes an operator ``channel_map`` rule (the request's, else one scoped to this file) and
starts ``dcl.process.resume_for_rule``. Dry run and undo answer 501 until they are built.
"""

import logging
import uuid
from typing import Annotated

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
    RejectRequest,
    ResolveRequest,
    ResolveResponse,
    RuleDraft,
    RuleList,
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
    )


@router.post("/cases/{case_key}/reject")
def reject_case(user: Reviewer, session: Db, case_key: str, body: RejectRequest) -> CaseSummary:
    try:
        case = cases.reject_case(session, case_key, body, _actor(user))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    session.commit()
    return cases.summary_of(session, case)


@router.post("/cases/{case_key}/undo")
def undo_case(user: Reviewer, case_key: str) -> UndoResponse:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "undo is not built yet")


@router.post("/dry-run")
def dry_run(user: Reviewer, body: DryRunRequest) -> DryRunResponse:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "dry run is not built yet")


@router.get("/rules")
def list_rules(user: Reviewer, session: Db, active: bool | None = None) -> RuleList:
    return RuleList(items=cases.list_rules(session, active))


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(user: Reviewer, session: Db, body: RuleDraft) -> RuleView:
    try:
        rule = cases.create_rule(session, body, _actor(user))
    except (cases.InvalidAction, ValueError) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    if rule.rule_type == "channel_map":
        start_resume(rule.rule_id)
    return cases.rule_view(session, rule)


@router.post("/rules/{rule_id}/simulate")
def simulate_rule(user: Reviewer, rule_id: uuid.UUID) -> RuleSimulation:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "simulate is not built yet")


@router.post("/rules/{rule_id}/deactivate")
def deactivate_rule(user: Reviewer, session: Db, rule_id: uuid.UUID) -> RuleView:
    try:
        rule = cases.deactivate_rule(session, rule_id, _actor(user))
    except cases.CaseNotFound as exc:
        raise _not_found(exc) from exc
    session.commit()
    return cases.rule_view(session, rule)
