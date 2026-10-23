"""POST /v1/translate on real rows: a page's leaf passages, cloud permission from the document's root."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.api import auth
from backend.api import engine as engine_api
from backend.indexing.anchors import content_hash
from backend.postgres.enums import DocumentStatus, NodeSource, NodeType
from backend.postgres.models import Blob, Document, DocumentNode, DocumentSource, DriveItem, SyncRoot
from backend.postgres.session import normalize_url
from backend.tests.unit.llm_engine.enrichment.test_translate import Cache, Client

ALEMBIC_INI = Path(__file__).resolve().parents[4] / "postgres" / "alembic.ini"
USER = auth.ConsoleUser(oid="o", name="n", email="e@x", roles=[auth.ConsoleRole.VIEWER])


@pytest.fixture(scope="module")
def db():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    url = normalize_url(url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        config = Config(str(ALEMBIC_INI))
        command.upgrade(config, "head")
        eng = create_engine(url)
        yield eng
        eng.dispose()
        command.downgrade(config, "base")


def seed(db, cloud: bool) -> uuid.UUID:
    sha = uuid.uuid4().hex * 2
    with Session(db) as s:
        root = f"root-{sha[:6]}"
        s.add(SyncRoot(root_name=root, remote_drive_id="d", remote_item_id=root, cloud_allowed=cloud))
        s.add(Blob(sha256=sha, size_bytes=1, minio_uri=f"s3://dcl-raw/{sha}"))
        doc = Document(route="A1", status=DocumentStatus.ACTIVE, title="Datenblatt", language="de")
        s.add(doc)
        s.flush()
        s.add(DocumentSource(doc_id=doc.doc_id, blob_sha256=sha, role="primary"))
        s.add(
            DriveItem(drive_id="d", item_id=sha[:8], root_name=root, name="Datenblatt.pdf", blob_sha256=sha)
        )
        parent = DocumentNode(
            doc_id=doc.doc_id,
            node_type=NodeType.PARENT,
            ordinal=0,
            content="Technische Daten",
            content_sha256=content_hash("Technische Daten"),
            page_no=1,
            source=NodeSource.PRINTED,
            language="de",
        )
        s.add(parent)
        s.flush()
        for i, text in enumerate(["Der Kammerdruck betrug 12,4 bar.", "Nennschub 10 N."], start=1):
            s.add(
                DocumentNode(
                    doc_id=doc.doc_id,
                    parent_node_id=parent.node_id,
                    node_type=NodeType.CHILD,
                    ordinal=i,
                    content=text,
                    content_sha256=content_hash(text),
                    page_no=1,
                    source=NodeSource.PRINTED,
                    language="de",
                )
            )
        s.commit()
        return doc.doc_id


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(engine_api.router)
    cache, gemini = Cache(), Client()
    app.dependency_overrides[auth.current_user] = lambda: USER

    def session():
        with Session(db) as s:
            yield s

    app.dependency_overrides[engine_api.db_session] = session
    app.dependency_overrides[engine_api.translation_cache] = lambda: cache
    app.dependency_overrides[engine_api.translation_client] = lambda: gemini
    return TestClient(app), gemini


def test_a_page_is_translated_from_its_leaf_passages(db, client):
    http, gemini = client
    doc_id = seed(db, cloud=True)
    body = http.post("/v1/translate", json={"doc_id": str(doc_id), "page_no": 1}).json()
    assert body["source_language"] == "de" and body["page_no"] == 1
    assert [p["original"] for p in body["passages"]] == [
        "Der Kammerdruck betrug 12,4 bar.",
        "Nennschub 10 N.",
    ]
    assert body["translated_text"] == "EN 1\n\nEN 2" and len(gemini.calls) == 1
    again = http.post("/v1/translate", json={"doc_id": str(doc_id), "page_no": 1}).json()
    assert all(p["cached"] for p in again["passages"]) and len(gemini.calls) == 1


def test_no_cloud_permission_is_403_and_an_empty_page_404(db, client):
    http, gemini = client
    doc_id = seed(db, cloud=False)
    assert http.post("/v1/translate", json={"doc_id": str(doc_id), "page_no": 1}).status_code == 403
    assert http.post("/v1/translate", json={"doc_id": str(doc_id), "page_no": 9}).status_code == 404
    assert gemini.calls == []
