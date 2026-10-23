"""Re-embed impact count for a models.embedding change. Needs DCL_TEST_DATABASE_URL."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.indexing.anchors import content_hash
from backend.indexing.index_document import ReembedImpact, reembed_impact
from backend.postgres.enums import DocumentStatus, NodeSource, NodeType
from backend.postgres.models import Document, DocumentNode
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
VEC = [1.0] + [0.0] * 767


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


def test_counts_the_nodes_another_model_embedded(engine):
    with Session(engine) as s:
        docs = [Document(route="A1", status=DocumentStatus.ACTIVE, title=f"d{i}") for i in range(3)]
        s.add_all(docs)
        s.flush()

        def node(doc, i, model, *, text=True, image=False):
            content = f"{doc.title} node {i}"
            s.add(
                DocumentNode(
                    doc_id=doc.doc_id,
                    node_type=NodeType.CHILD,
                    ordinal=i,
                    content=content,
                    content_sha256=content_hash(content),
                    source=NodeSource.PRINTED,
                    embedding=VEC if text else None,
                    image_embedding=VEC if image else None,
                    embedding_model=model,
                    doc_status=doc.status,
                )
            )

        node(docs[0], 0, "old@768")
        node(docs[0], 1, "old@768", image=True)
        node(docs[1], 0, "new@768")
        node(docs[2], 0, None, text=False)  # never embedded: not counted
        s.commit()
        assert reembed_impact(s, "new@768") == ReembedImpact(text_nodes=2, image_nodes=1, documents=1)
        assert reembed_impact(s, "other@512").nodes == 4
