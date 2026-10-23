"""Console routes for Settings › Sources and the Ops page: root status, device-code sign-in, process
everything, re-dispatch. Needs DCL_TEST_DATABASE_URL."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api import sync as sync_api
from backend.api.auth import ConsoleRole, ConsoleUser
from backend.postgres import pipeline_config
from backend.postgres.models import AuditEvent, Blob, Document, DocumentSource, DriveFolder, DriveItem
from backend.postgres.session import get_session

ADMIN = ConsoleUser(oid="o", name="Asha", email="asha@manastu.space", roles=[ConsoleRole.ADMIN])


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, ex=None, nx=False):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)


@pytest.fixture
def api(session, monkeypatch):
    redis, sent = FakeRedis(), []
    monkeypatch.setattr(sync_api, "_redis", lambda: redis)
    monkeypatch.setattr(
        sync_api, "_send", lambda name, args=None, queue="io_light": sent.append((name, args, queue)) or True
    )
    app = FastAPI()
    app.include_router(sync_api.router)
    app.dependency_overrides[sync_api.Admin.__metadata__[0].dependency] = lambda: ADMIN
    app.dependency_overrides[sync_api.Reviewer.__metadata__[0].dependency] = lambda: ADMIN
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), redis, sent


def _item(item_id, status, blob=None, error=None):
    return DriveItem(
        drive_id="D",
        item_id=item_id,
        root_name="APU Injector",
        name=f"{item_id}.pdf",
        extension=".pdf",
        parent_item_id="F1",
        path_cached=f"APU Injector/TP1/{item_id}.pdf",
        status=status,
        blob_sha256=blob,
        detected_mime="application/pdf" if blob else None,
        error_last=error,
    )


def test_roots_show_counts_waiting_files_and_errors(api, session):
    client, _, _ = api
    session.add(
        DriveFolder(
            drive_id="D",
            item_id="F1",
            root_name="APU Injector",
            name="TP1",
            parent_item_id="ROOT",
            path_cached="APU Injector/TP1",
        )
    )
    session.add(Blob(sha256="a" * 64, size_bytes=1, minio_uri="s3://dcl-raw/a"))
    session.flush()
    session.add_all(
        [
            _item("i1", "LANDED", "a" * 64),
            _item("i2", "HELD_BY_SCOPE"),
            _item("i3", "PENDING_DOWNLOAD"),
            _item("i4", "DOWNLOAD_FAILED", error="hash mismatch"),
        ]
    )
    session.commit()
    (root,) = client.get("/sync/roots").json()
    counts = root["counts"]
    assert (
        counts["items"],
        counts["held_by_scope"],
        counts["pending_download"],
        counts["download_failed"],
        counts["landed"],
        counts["waiting_dispatch"],
    ) == (4, 1, 1, 1, 1, 1)
    assert root["recent_errors"] == [{"path": "APU Injector/TP1/i4.pdf", "error": "hash mismatch"}]
    assert (root["kept_current_by"], root["crawl_in_progress"]) == ("poll", False)


def test_sign_in_starts_on_io_light_and_reports_its_state(api):
    client, redis, sent = api
    assert client.get("/sync/sign-in").json()["state"] == "idle"
    assert client.post("/sync/sign-in").json()["state"] == "starting"
    assert sent == [("dcl.sync.sign_in", None, "io_light")]
    redis.values["sync:sign_in"] = json.dumps(
        {
            "state": "pending",
            "user_code": "ABCD-1234",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_at": "2026-10-23T08:00:00+00:00",
            "detail": None,
        }
    )
    state = client.get("/sync/sign-in").json()
    assert (state["state"], state["user_code"]) == ("pending", "ABCD-1234")


def test_sign_in_task_publishes_the_code_then_the_outcome(monkeypatch):
    from backend.celery_redis import tasks_sync

    redis = FakeRedis()
    states = []

    class Provider:
        def sign_in(self, show, on_flow=None):
            on_flow(
                {
                    "user_code": "WXYZ-9876",
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "expires_in": 900,
                }
            )
            states.append(json.loads(redis.values["sync:sign_in"])["state"])
            return "dcl-svc@manastu.space"

    monkeypatch.setattr(tasks_sync, "_redis", lambda: redis)
    monkeypatch.setattr(tasks_sync.TokenProvider, "create", classmethod(lambda cls, config: Provider()))
    monkeypatch.setattr(tasks_sync.GraphAuthConfig, "from_settings", classmethod(lambda cls, settings: None))
    assert tasks_sync.sign_in() == "dcl-svc@manastu.space"
    final = json.loads(redis.values["sync:sign_in"])
    assert (states, final["state"], final["detail"]) == (["pending"], "signed_in", "dcl-svc@manastu.space")


def test_process_everything_empties_the_scope_through_the_settings_path(api, session, monkeypatch):
    from backend.api import settings

    client, _, _ = api
    monkeypatch.setattr(settings, "start_task", lambda name: True)
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F1"], "seed")
    session.commit()
    response = client.post("/sync/process-everything").json()
    assert response["applied"][0]["after"] == [] and response["dispatch_started"] is True
    assert pipeline_config.processing_scope(session) == []
    assert session.scalars(select(AuditEvent.entity_id)).all() == ["processing.scope"]


def test_redispatch_counts_then_reruns_committed_documents(api, session):
    client, _, sent = api
    session.add(Blob(sha256="b" * 64, size_bytes=1, minio_uri="s3://dcl-raw/b"))
    session.flush()
    doc = Document(route="C", status="ACTIVE", title="plan.xlsx")
    session.add_all(
        [doc, Document(route="C", status="HALTED", title="T01.dat", staged_payload_uri="s3://dcl-cir/x")]
    )
    session.flush()
    session.add(DocumentSource(doc_id=doc.doc_id, blob_sha256="b" * 64, role="primary"))
    session.commit()
    assert client.get("/sync/redispatch", params={"route": "C"}).json() == {
        "route": "C",
        "documents": 1,
        "sample": ["plan.xlsx"],
    }
    result = client.post("/sync/redispatch", params={"route": "C"}).json()
    assert (result["redispatched"], result["started"]) == (1, True)
    assert sent == [("dcl.process.route_c", [str(doc.doc_id)], "telemetry_stream")]
    assert session.get(Document, doc.doc_id).status == "PROCESSING"
