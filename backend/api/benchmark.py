"""Benchmark API routes (file 08 §5.5): thin wrappers over backend/benchmark/catalog.py. Owner: S3."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.api.engine import Identity as PipeCaller
from backend.benchmark.catalog import (
    BenchmarkCaseList,
    CaseContent,
    CaseCreate,
    CaseView,
    DraftFromChat,
    ImportCounts,
    Problem,
    RunComparison,
    RunRequest,
    RunResults,
    RunView,
    SuiteExport,
    SuiteImport,
    SuiteSummary,
    add_version,
    cancel_run,
    case_history,
    compare_runs,
    create_case,
    draft_from_chat,
    export_suite,
    import_suite,
    list_cases,
    list_runs,
    list_suites,
    run_results,
    set_status,
    start_run,
)
from backend.postgres.enums import BenchmarkCaseStatus, BenchmarkCategory
from backend.postgres.session import get_session

# ---------------------------------------------------------------- routes

router = APIRouter(prefix="/benchmark", tags=["benchmark"])
Viewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.VIEWER))]
Reviewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.REVIEWER))]
DB = Annotated[Session, Depends(get_session)]


def _http(exc: Problem) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


@router.get("/suites")
def get_suites(user: Viewer, session: DB) -> list[SuiteSummary]:
    return list_suites(session)


@router.get("/suites/{suite}/export")
def get_suite_export(suite: str, user: Viewer, session: DB) -> SuiteExport:
    return export_suite(session, suite)


@router.post("/suites/{suite}/import")
def post_suite_import(suite: str, body: SuiteImport, user: Reviewer, session: DB) -> ImportCounts:
    try:
        counts = import_suite(session, suite, body, user.email)
    except Problem as exc:
        session.rollback()
        raise _http(exc) from exc
    session.commit()
    return counts


@router.get("/cases")
def get_cases(
    user: Viewer,
    session: DB,
    suite: str | None = None,
    case_status: Annotated[BenchmarkCaseStatus | None, Query(alias="status")] = None,
    category: BenchmarkCategory | None = None,
) -> BenchmarkCaseList:
    return list_cases(session, suite, case_status, category)


@router.get("/cases/{case_id}")
def get_case(case_id: str, user: Viewer, session: DB) -> list[CaseView]:
    try:
        return case_history(session, case_id)
    except Problem as exc:
        raise _http(exc) from exc


def _write(session: Session, action):
    try:
        result = action()
    except Problem as exc:
        session.rollback()
        raise _http(exc) from exc
    session.commit()
    return result


@router.post("/cases", status_code=status.HTTP_201_CREATED)
def post_case(body: CaseCreate, user: Reviewer, session: DB) -> CaseView:
    return _write(session, lambda: create_case(session, body, user.email))


@router.post("/cases/{case_id}/versions", status_code=status.HTTP_201_CREATED)
def post_case_version(case_id: str, body: CaseContent, user: Reviewer, session: DB) -> CaseView:
    return _write(session, lambda: add_version(session, case_id, body, user.email))


@router.post("/cases/{case_id}/approve")
def post_approve(case_id: str, user: Reviewer, session: DB) -> CaseView:
    return _write(
        session,
        lambda: set_status(
            session, case_id, BenchmarkCaseStatus.ACTIVE, user.email, BenchmarkCaseStatus.DRAFT
        ),
    )


@router.post("/cases/{case_id}/retire")
def post_retire(case_id: str, user: Reviewer, session: DB) -> CaseView:
    return _write(
        session, lambda: set_status(session, case_id, BenchmarkCaseStatus.RETIRED, user.email, None)
    )


@router.post("/drafts", status_code=status.HTTP_201_CREATED)
def post_draft(body: DraftFromChat, caller: PipeCaller, session: DB) -> CaseView:
    """For the Add-to-benchmark action: signed Pipe identity, never a Console token."""
    return _write(session, lambda: draft_from_chat(session, body, caller.email or caller.user_id))


@router.get("/runs")
def get_runs(
    user: Viewer, session: DB, suite: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[RunView]:
    return list_runs(session, suite, limit)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def post_run(body: RunRequest, user: Reviewer, session: DB) -> RunView:
    return _write(session, lambda: start_run(session, body, user.email))


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, user: Viewer, session: DB) -> RunResults:
    try:
        return run_results(session, run_id)
    except Problem as exc:
        raise _http(exc) from exc


@router.post("/runs/{run_id}/cancel")
def post_cancel(run_id: uuid.UUID, user: Reviewer, session: DB) -> RunView:
    return _write(session, lambda: cancel_run(session, run_id))


@router.get("/compare")
def get_compare(base: uuid.UUID, head: uuid.UUID, user: Viewer, session: DB) -> RunComparison:
    try:
        return compare_runs(session, base, head)
    except Problem as exc:
        raise _http(exc) from exc
