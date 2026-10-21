"""resolve_anchor over real document_nodes rows. Needs DCL_TEST_DATABASE_URL (an empty ParadeDB database)."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from backend.dispatcher.contract import DocumentFields, PageBox, ProcessedDocument, ProcessedNode
from backend.indexing.anchors import ResolutionStatus, make_anchor, resolve_anchor
from backend.indexing.chunker import ChunkingConfig, chunk_document
from backend.postgres.enums import DocKind, DocumentStatus, NodeSource, NodeType
from backend.postgres.models import Document, DocumentNode
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
SHA = "b" * 64


def words(texts):
    return [len(t.split()) for t in texts]


@pytest.fixture(scope="module")
def engine():
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


def report() -> ProcessedDocument:
    nodes = [
        ProcessedNode(
            ref=f"para{p}",
            node_type=NodeType.PARENT,
            ordinal=p,
            breadcrumb="Test Report 37 › 3 Results",
            content=" ".join(f"Page {p} sentence {i} says the pressure was {p}.{i} bar." for i in range(40)),
            page_no=p,
            bboxes=[PageBox(page_no=p, x0=0.1, y0=0.2, x1=0.9, y1=0.4)],
            source=NodeSource.PRINTED,
        )
        for p in range(1, 7)
    ]
    return ProcessedDocument(
        blob_sha256=SHA,
        route="A1",
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{SHA}/A1/v1/docling.json",
        document=DocumentFields(title="Test Report 37", doc_kind=DocKind.TEST_REPORT),
        nodes=nodes,
    )


def store(session: Session, doc_id: uuid.UUID, config: ChunkingConfig) -> list:
    """What S1's commit does for nodes, reduced to the columns resolve_anchor reads."""
    session.execute(delete(DocumentNode).where(DocumentNode.doc_id == doc_id))
    nodes = chunk_document(report(), config, count_tokens=words)
    for node in nodes:
        session.add(
            DocumentNode(
                doc_id=doc_id,
                node_type=node.node_type,
                ordinal=node.ordinal,
                breadcrumb=node.breadcrumb,
                content=node.content,
                content_sha256=node.content_sha256,
                page_no=node.page_no,
                page_end=node.page_end,
                bbox=[box.model_dump() for box in node.bboxes],
                source=node.source,
            )
        )
    session.commit()
    return nodes


def test_anchors_resolve_exactly_then_by_page_after_a_chunk_size_change(engine):
    with Session(engine) as session:
        doc = Document(route="A1", status=DocumentStatus.ACTIVE, title="Test Report 37")
        session.add(doc)
        session.commit()
        before = store(session, doc.doc_id, ChunkingConfig())
        anchors = [make_anchor(doc.doc_id, n) for n in before if n.node_type is NodeType.CHILD]

        exact = [resolve_anchor(session, a) for a in anchors]
        assert {r.status for r in exact} == {ResolutionStatus.EXACT}
        assert all(r.boxes and r.boxes[0].page_no == a.page_no for r, a in zip(exact, anchors, strict=True))

        store(session, doc.doc_id, ChunkingConfig(child_max_tokens=150))
        after = [resolve_anchor(session, a) for a in anchors]
        assert ResolutionStatus.PAGE_FALLBACK in {r.status for r in after}
        assert ResolutionStatus.DOCUMENT_ONLY not in {r.status for r in after}
        assert all(r.page_no == a.page_no for r, a in zip(after, anchors, strict=True))

        gone = anchors[0].model_copy(update={"page_no": 99, "content_sha256": "0" * 64})
        assert resolve_anchor(session, gone).status is ResolutionStatus.DOCUMENT_ONLY
