"""A route task that raised (defects found by the D route run, 2026-10-24): a transient error retries while
retries are left and leaves the document FAILED after the last one (file 02 §7), a gateway error the client
marks retryable counts as transient, and anything else fails at once.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT.
"""

from types import SimpleNamespace

import pytest

from backend.celery_redis import tasks_process
from backend.llm_engine.gemini_types import GatewayError
from backend.tests.unit.dispatcher.test_runner_flags_and_fields import _document


class Retry(Exception):
    pass


def _task(retries: int, max_retries: int = 2):
    calls = []

    def retry(exc, countdown):
        calls.append(countdown)
        return Retry()

    request = SimpleNamespace(retries=retries, called_directly=False)
    return SimpleNamespace(request=request, max_retries=max_retries, retry=retry, calls=calls)


@pytest.fixture
def processing(session, minio):
    document = _document(session, minio)
    document.status = "PROCESSING"
    session.commit()
    return document


def _status(session, document) -> str:
    session.expire_all()
    return session.get(type(document), document.doc_id).status


def test_an_unreachable_gateway_retries_while_retries_are_left(session, processing, monkeypatch):
    task = _task(retries=0)
    monkeypatch.setattr(tasks_process, "current_task", task)
    unreachable = GatewayError("gateway unreachable: ConnectError", retryable=True)
    with pytest.raises(Retry):
        tasks_process._settle(session, processing.doc_id, unreachable)
    assert (task.calls, _status(session, processing)) == ([30], "PROCESSING")


def test_after_the_last_retry_the_document_is_failed_with_the_error(session, processing, monkeypatch):
    task = _task(retries=2)
    monkeypatch.setattr(tasks_process, "current_task", task)
    tasks_process._settle(session, processing.doc_id, GatewayError("gateway unreachable", retryable=True))
    assert (task.calls, _status(session, processing)) == ([], "FAILED")
    session.expire_all()
    assert processing.metadata_sources["error"] == "GatewayError: gateway unreachable"


def test_a_non_retryable_error_fails_at_once(session, processing, monkeypatch):
    task = _task(retries=0)
    monkeypatch.setattr(tasks_process, "current_task", task)
    tasks_process._settle(session, processing.doc_id, GatewayError("bad request", status_code=400))
    assert (task.calls, _status(session, processing)) == ([], "FAILED")


def test_a_route_specific_wait_is_retried_not_failed(session, processing, monkeypatch):
    from backend.dispatcher.media_run import RepresentativePending

    task = _task(retries=1)
    monkeypatch.setattr(tasks_process, "current_task", task)
    with pytest.raises(Retry):
        tasks_process._settle(
            session,
            processing.doc_id,
            RepresentativePending("not read yet"),
            tasks_process._media_retryable(),
        )
    assert (task.calls, _status(session, processing)) == ([60], "PROCESSING")


def test_a_route_that_keeps_its_progress_is_sent_again_at_its_time_limit(
    session, minio, processing, monkeypatch
):
    from celery.exceptions import SoftTimeLimitExceeded

    monkeypatch.setattr(tasks_process, "_engine", lambda: session.get_bind())
    monkeypatch.setattr(tasks_process, "client_from_settings", lambda settings: minio)
    monkeypatch.setattr(tasks_process, "_indexer", lambda m: None)
    sent = []

    def long_recording(*args):
        raise SoftTimeLimitExceeded()

    result = tasks_process._run(
        str(processing.doc_id), long_recording, checkpoint=lambda: sent.append("again")
    )
    assert (result["status"], sent, _status(session, processing)) == ("continued", ["again"], "PROCESSING")
