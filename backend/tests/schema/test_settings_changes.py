"""Settings API on a real database: versions, audit, validation, conflicts, scope moves, previews."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api import settings
from backend.api.auth import ConsoleRole, ConsoleUser
from backend.postgres import pipeline_config as pc
from backend.postgres.models import (
    AuditEvent,
    Blob,
    Document,
    DocumentSource,
    DriveFolder,
    DriveItem,
    SyncRoot,
)
from backend.postgres.session import get_session

ADMIN = ConsoleUser(oid="o-1", name="Asha", email="asha@manastu", roles=[ConsoleRole.ADMIN])
FOLDER_A, FOLDER_B = "F-A", "F-B"


@pytest.fixture()
def session(migrated):
    with Session(migrated, expire_on_commit=False) as s:
        pc.seed_gate(s, pc.load_gate_yaml())
        s.add(SyncRoot(root_name="APU", remote_drive_id="D", remote_item_id="ROOT"))
        s.flush()
        for fid, name in ((FOLDER_A, "TP7"), (FOLDER_B, "TP9")):
            s.add(DriveFolder(drive_id="D", item_id=fid, parent_item_id="ROOT", root_name="APU", name=name))
        s.commit()
        yield s


@pytest.fixture()
def started(monkeypatch):
    names: list[str] = []
    monkeypatch.setattr(settings, "start_task", lambda name: names.append(name) or True)
    return names


@pytest.fixture()
def client(session, started):
    app = FastAPI()
    app.include_router(settings.router)
    app.dependency_overrides[settings.Admin.__metadata__[0].dependency] = lambda: ADMIN
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def _item(item_id, folder, name, status, size=10, blob=None, mime=None):
    return DriveItem(
        drive_id="D",
        item_id=item_id,
        root_name="APU",
        parent_item_id=folder,
        name=name,
        extension="." + name.rsplit(".", 1)[1],
        size_bytes=size,
        quick_xor_hash=f"q-{item_id}",
        path_cached=f"APU/{'TP7' if folder == FOLDER_A else 'TP9'}/{name}",
        status=status,
        blob_sha256=blob,
        detected_mime=mime,
    )


def test_put_appends_versions_audits_and_rolls_back(client, session):
    body = {
        "changes": [{"key": "flags.strict_mode", "value": True, "expected_version": 0}],
        "description": "M3",
    }
    response = client.put("/settings", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["applied"] == [
        {"key": "flags.strict_mode", "version": 1, "before": None, "after": True}
    ]
    client.put("/settings", json={"changes": [{"key": "flags.strict_mode", "value": False}]})

    history = client.get("/settings/flags.strict_mode/history").json()["items"]
    assert [(h["version"], h["value"], h["updated_by"]) for h in history] == [
        (2, False, "asha@manastu"),
        (1, True, "asha@manastu"),
    ]
    rolled = client.post("/settings/rollback", json={"versions": {"flags.strict_mode": 1}}).json()
    assert rolled["applied"] == [{"key": "flags.strict_mode", "version": 3, "before": False, "after": True}]
    assert pc.get(session, "flags.strict_mode") is True

    events = session.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == "flags.strict_mode").order_by(AuditEvent.event_id)
    ).all()
    assert [(e.entity_type, e.action, e.actor) for e in events] == [
        ("config", "update", "asha@manastu"),
        ("config", "update", "asha@manastu"),
        ("config", "rollback", "asha@manastu"),
    ]
    assert events[2].before == {"version": 2, "value": False}
    assert events[2].after == {"version": 3, "value": True}


def test_unchanged_value_writes_nothing(client, session):
    client.put("/settings", json={"changes": [{"key": "cloud.region", "value": "asia-south1"}]})
    again = client.put("/settings", json={"changes": [{"key": "cloud.region", "value": "asia-south1"}]})
    assert again.json()["applied"] == []
    assert len(pc.history(session, "cloud.region")) == 1


def test_invalid_batch_is_422_per_key_and_writes_nothing(client, session):
    response = client.put(
        "/settings",
        json={
            "changes": [
                {"key": "flags.strict_mode", "value": True},
                {"key": "translation.mode", "value": "everything"},
                {"key": "gate.max_download_bytes", "value": "lots"},
                {"key": "graph.client_secret", "value": "x"},
                {"key": "routes.Z.enabled", "value": True},
            ]
        },
    )
    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert set(errors) == {
        "translation.mode",
        "gate.max_download_bytes",
        "graph.client_secret",
        "routes.Z.enabled",
    }
    assert pc.get(session, "flags.strict_mode", default=None) is None
    assert session.scalars(select(AuditEvent)).all() == []


def test_stale_expected_version_is_409(client):
    client.put("/settings", json={"changes": [{"key": "sync.download_concurrency", "value": 4}]})
    stale = client.put(
        "/settings",
        json={"changes": [{"key": "sync.download_concurrency", "value": 8, "expected_version": 0}]},
    )
    assert stale.status_code == 409


def test_rollback_to_a_missing_version_is_404(client):
    assert client.post("/settings/rollback", json={"versions": {"cloud.region": 3}}).status_code == 404


def test_gate_change_is_validated_as_a_whole_and_previewed(client, session):
    session.add(Blob(sha256="a" * 64, size_bytes=10, minio_uri="s3://dcl-raw/a"))
    session.flush()
    session.add(_item("i1", FOLDER_A, "run.log2", "LANDED", blob="a" * 64, mime="text/plain"))
    session.add(_item("i2", FOLDER_A, "run.dat", "LANDED", blob="a" * 64, mime="text/plain"))
    session.commit()
    endings = pc.get(session, "gate.junk_extensions") + [".log2"]
    preview = client.post(
        "/settings/preview", json={"changes": [{"key": "gate.junk_extensions", "value": endings}]}
    )
    assert preview.status_code == 200, preview.text
    [impact] = preview.json()["impacts"]
    assert impact["counts"] == {"would_reject": 1, "T2:.log2": 1}


def test_widening_the_download_scope_releases_held_items(client, session, started):
    session.add(Blob(sha256="b" * 64, size_bytes=5, minio_uri="s3://dcl-raw/b", quick_xor_hash="q-i4"))
    session.flush()
    session.add_all(
        [
            _item("i3", FOLDER_B, "t.dat", "HELD_BY_SCOPE", size=100),
            _item("i4", FOLDER_B, "t.cfg", "HELD_BY_SCOPE", size=5, blob="b" * 64),
            _item("i5", FOLDER_A, "p.dat", "PENDING_DOWNLOAD"),
        ]
    )
    pc.set_value(session, pc.DOWNLOAD_SCOPE, [FOLDER_A], "seed")
    session.commit()

    new_scope = {"changes": [{"key": pc.DOWNLOAD_SCOPE, "value": [FOLDER_B]}]}
    [impact] = client.post("/settings/preview", json=new_scope).json()["impacts"]
    assert impact["counts"] == {"to_download": 2, "to_hold": 1}
    assert impact["bytes"] == 105

    applied = client.put("/settings", json=new_scope).json()
    assert (applied["released_downloads"], applied["held_downloads"]) == (2, 1)
    status = dict(session.execute(select(DriveItem.item_id, DriveItem.status)).all())
    assert status == {"i3": "PENDING_DOWNLOAD", "i4": "LANDED", "i5": "HELD_BY_SCOPE"}
    assert started == ["dcl.sync.enqueue_downloads"]


def test_processing_scope_and_route_previews_count_and_start_dispatch(client, session, started):
    for sha in ("c" * 64, "d" * 64):
        session.add(Blob(sha256=sha, size_bytes=7, minio_uri=f"s3://dcl-raw/{sha[0]}"))
    session.flush()
    session.add_all(
        [
            _item("i6", FOLDER_B, "x.pdf", "LANDED", size=7, blob="c" * 64, mime="application/pdf"),
            _item("i7", FOLDER_B, "y.drawio", "LANDED", size=7, blob="d" * 64, mime="text/xml"),
            Document(route="E", status="WAITING_FOR_ROUTE", title="y.drawio"),
        ]
    )
    session.flush()
    doc = session.scalars(select(Document)).one()
    session.add(DocumentSource(doc_id=doc.doc_id, blob_sha256="d" * 64, role="primary"))
    pc.set_value(session, pc.PROCESSING_SCOPE, [FOLDER_A], "seed")
    session.commit()

    batch = {
        "changes": [
            {"key": pc.PROCESSING_SCOPE, "value": [FOLDER_A, FOLDER_B]},
            {"key": "routes.E.enabled", "value": True},
        ]
    }
    impacts = {i["key"]: i for i in client.post("/settings/preview", json=batch).json()["impacts"]}
    assert impacts[pc.PROCESSING_SCOPE]["counts"] == {"to_process": 1, "no_longer_processed": 0}
    assert impacts[pc.PROCESSING_SCOPE]["by_extension"] == {".pdf": 1}
    assert impacts[pc.PROCESSING_SCOPE]["estimated_cost_usd"] is None
    assert impacts["routes.E.enabled"]["counts"] == {"waiting_for_route": 1}

    applied = client.put("/settings", json=batch).json()
    assert applied["dispatch_started"] is True
    assert started == ["dcl.process.dispatch"]


def test_list_filters_by_prefix(client):
    client.put("/settings", json={"changes": [{"key": "answer.proprietary_terms", "value": ["X"]}]})
    items = client.get("/settings", params={"prefix": "answer."}).json()["items"]
    assert [(i["key"], i["version"], i["value"]) for i in items] == [("answer.proprietary_terms", 1, ["X"])]


def test_model_prices_are_validated_and_feed_the_client(client, session):
    bad = client.put(
        "/settings", json={"changes": [{"key": "models.prices", "value": {"m": {"input_per_mtok": -1}}}]}
    )
    assert bad.status_code == 422 and set(bad.json()["detail"]["errors"]) == {"models.prices"}
    prices = {"gemini-3.8-flash": {"input_per_mtok": 0.3, "output_per_mtok": 2.5}}
    assert (
        client.put("/settings", json={"changes": [{"key": "models.prices", "value": prices}]}).status_code
        == 200
    )
    (price,) = pc.model_prices(session).values()
    assert (price.input_per_mtok, price.output_per_mtok, price.cached_per_mtok) == (0.3, 2.5, 0.0)


def test_processing_scope_preview_estimates_cost_from_the_ledger(client, session):
    import uuid

    from backend.postgres.models import LlmCall

    session.add(Blob(sha256="e" * 64, size_bytes=7, minio_uri="s3://dcl-raw/e"))
    session.flush()
    session.add(_item("i8", FOLDER_B, "z.pdf", "LANDED", size=7, blob="e" * 64, mime="application/pdf"))
    for _doc in range(5):  # five documents at $0.02, each in two calls
        doc = uuid.uuid4()
        for _ in range(2):
            session.add(
                LlmCall(model="m", purpose="triage_page", doc_id=doc, cost_estimate=0.01, status="ok")
            )
    pc.set_value(session, pc.PROCESSING_SCOPE, [FOLDER_A], "seed")
    session.commit()
    batch = {"changes": [{"key": pc.PROCESSING_SCOPE, "value": [FOLDER_A, FOLDER_B]}]}
    [impact] = client.post("/settings/preview", json=batch).json()["impacts"]
    assert (impact["estimated_cost_usd"], impact["cost_note"]) == (
        0.02,
        "mean $0.0200 per document over 5 documents",
    )


def test_an_embedding_model_change_counts_the_nodes_to_re_embed(client, session):
    from backend.postgres.models import Document, DocumentNode

    doc = Document(route="A1", status="ACTIVE", title="r")
    session.add(doc)
    session.flush()
    vector = [0.01] * 768
    session.add_all(
        [
            DocumentNode(
                doc_id=doc.doc_id,
                node_type="child",
                ordinal=i,
                content=f"c{i}",
                source="printed",
                embedding=vector,
                embed_text_hash=("a" if i < 2 else "b") * 64,
            )
            for i in range(3)
        ]
        + [
            DocumentNode(
                doc_id=doc.doc_id,
                node_type="photo",
                ordinal=3,
                content="p",
                source="vlm",
                image_embedding=vector,
            )
        ]
    )
    session.commit()
    batch = {
        "changes": [
            {"key": "models.embedding", "value": "embeddinggemma-3@768"},
            {"key": "models.reasoning", "value": "gemini-3.8-flash"},
        ]
    }
    impacts = {i["key"]: i for i in client.post("/settings/preview", json=batch).json()["impacts"]}
    assert impacts["models.embedding"]["counts"] == {
        "reembed_nodes": 4,
        "text_nodes": 3,
        "image_nodes": 1,
        "distinct_texts": 2,
    }
    assert impacts["models.reasoning"]["counts"] == {}
