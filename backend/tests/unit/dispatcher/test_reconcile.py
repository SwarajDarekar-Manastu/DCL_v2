"""Decided files that did not move on are sent again (dispatcher/reconcile.py); a failed resume is seen.
Needs DCL_TEST_DATABASE_URL."""

import uuid
from datetime import UTC, datetime, timedelta

from minio.error import S3Error

from backend.celery_redis import tasks_process
from backend.dispatcher.contract import Flag
from backend.dispatcher.reconcile import MAX_RERUNS, stalled
from backend.postgres.models import Document
from backend.review.flags import upsert_document_flag

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
FULL = S3Error(
    None, "XMinioStorageFull", "Storage backend has reached its minimum free drive threshold", "k", "r", "h"
)


def _doc(session, route, status, **meta):
    document = Document(
        route=route,
        status=status,
        title=f"{route}-{uuid.uuid4().hex[:6]}",
        metadata_sources=meta,
        staged_payload_uri="s3://dcl-cir/x/staged.json" if status == "HALTED" else None,
    )
    session.add(document)
    session.flush()
    return document


def test_an_answered_halted_file_resumes_on_its_route_once_per_two_hours(session):
    telemetry = _doc(session, "C", "HALTED")
    report = _doc(session, "A1", "HALTED")
    waiting = _doc(session, "C", "HALTED")
    upsert_document_flag(session, waiting.doc_id, Flag(flag_type="UNIT_AMBIGUITY", severity="HARD"), "C")
    sent = {r.doc_id: (r.task, r.queue) for r in stalled(session, NOW)}
    assert sent == {
        telemetry.doc_id: ("dcl.process.resume_route_c", "telemetry_stream"),
        report.doc_id: ("dcl.process.resume_staged", "cpu_parse"),
    }
    assert (telemetry.metadata_sources["reruns"], telemetry.status) == (1, "HALTED")
    assert stalled(session, NOW + timedelta(hours=1)) == []  # a stopped worker gets one waiting message
    assert {r.doc_id for r in stalled(session, NOW + timedelta(hours=2))} == {telemetry.doc_id, report.doc_id}


def test_a_file_failed_by_a_passing_error_runs_again_and_a_real_failure_waits_for_a_person(session):
    passing = _doc(session, "C", "FAILED", error="S3Error: XMinioStorageFull", error_transient=True)
    broken = _doc(session, "C", "FAILED", error="ValueError: bad header", error_transient=False)
    (release,) = stalled(session, NOW)
    assert (release.doc_id, release.task, release.queue) == (
        passing.doc_id,
        "dcl.process.route_c",
        "telemetry_stream",
    )
    assert (passing.status, broken.status) == ("PROCESSING", "FAILED")


def test_resends_stop_after_the_cap_and_a_file_that_moved_on_loses_its_marks(session):
    tired = _doc(session, "C", "HALTED", reruns=MAX_RERUNS)
    recovered = _doc(
        session, "C", "ACTIVE", reruns=2, resent_at=NOW.isoformat(), error="old", error_transient=True
    )
    assert stalled(session, NOW) == []
    assert tired.metadata_sources["reruns"] == MAX_RERUNS
    assert recovered.metadata_sources == {"error": "old"}


def test_a_resume_that_fails_keeps_its_staged_payload_and_says_why(session):
    document = _doc(session, "C", "HALTED")
    session.commit()
    tasks_process._fail(session, document.doc_id, FULL, transient=True)
    session.refresh(document)
    assert (document.status, document.staged_payload_uri) == ("HALTED", "s3://dcl-cir/x/staged.json")
    assert document.metadata_sources["error_transient"] is True
    assert "XMinioStorageFull" in document.metadata_sources["error"]
    assert [r.doc_id for r in stalled(session, NOW)] == [document.doc_id]  # and is resumed again


def test_a_run_that_fails_is_failed_with_its_error(session):
    document = _doc(session, "A1", "PROCESSING")
    session.commit()
    tasks_process._fail(session, document.doc_id, ValueError("bad page tree"))
    session.refresh(document)
    assert (document.status, document.metadata_sources["error"]) == ("FAILED", "ValueError: bad page tree")


def test_a_file_stuck_in_processing_is_run_again_once_per_two_hours(session):
    from sqlalchemy import update

    stuck = _doc(session, "A1", "PROCESSING")
    fresh = _doc(session, "A1", "PROCESSING")
    session.execute(
        update(Document).where(Document.doc_id == stuck.doc_id).values(updated_at=NOW - timedelta(hours=3))
    )
    session.execute(update(Document).where(Document.doc_id == fresh.doc_id).values(updated_at=NOW))
    session.expire_all()
    (release,) = stalled(session, NOW)
    assert (release.doc_id, release.task, release.queue) == (
        stuck.doc_id,
        "dcl.process.route_a1",
        "cpu_parse",
    )
