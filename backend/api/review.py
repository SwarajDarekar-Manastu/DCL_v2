"""S1: review cases, flags and rules (file 08 §4.4). Thin router over backend/review.

The routes and their models are published so the Console can be built against the OpenAPI
schema. They answer 501 until the review tables exist (M2); then each handler calls one
function in backend/review.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
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

router = APIRouter(prefix="/review", tags=["review"])

Reviewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]
Admin = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.ADMIN))]
NOT_YET = "review tables arrive in M2 (backend/review-backend)"


def _not_implemented() -> HTTPException:
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_YET)


@router.get("/cases")
def list_cases(user: Reviewer, filters: Annotated[CaseFilters, Query()]) -> CaseList:
    raise _not_implemented()


@router.get("/cases/{case_key}")
def get_case(user: Reviewer, case_key: str) -> CaseDetail:
    raise _not_implemented()


@router.post("/cases/{case_key}/assign")
def assign_case(user: Reviewer, case_key: str, body: AssignRequest) -> CaseSummary:
    raise _not_implemented()


@router.post("/cases/{case_key}/resolve")
def resolve_case(user: Reviewer, case_key: str, body: ResolveRequest) -> ResolveResponse:
    raise _not_implemented()


@router.post("/cases/{case_key}/reject")
def reject_case(user: Reviewer, case_key: str, body: RejectRequest) -> CaseSummary:
    raise _not_implemented()


@router.post("/cases/{case_key}/undo")
def undo_case(user: Reviewer, case_key: str) -> UndoResponse:
    raise _not_implemented()


@router.post("/dry-run")
def dry_run(user: Reviewer, body: DryRunRequest) -> DryRunResponse:
    raise _not_implemented()


@router.get("/rules")
def list_rules(user: Reviewer, active: bool | None = None) -> RuleList:
    raise _not_implemented()


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(user: Reviewer, body: RuleDraft) -> RuleView:
    raise _not_implemented()


@router.post("/rules/{rule_id}/simulate")
def simulate_rule(user: Reviewer, rule_id: uuid.UUID) -> RuleSimulation:
    raise _not_implemented()


@router.post("/rules/{rule_id}/deactivate")
def deactivate_rule(user: Admin, rule_id: uuid.UUID) -> RuleView:
    raise _not_implemented()
