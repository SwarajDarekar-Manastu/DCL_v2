from types import SimpleNamespace

import pytest

from backend.dispatcher.contract import DocumentFields, PageBox, ProcessedDocument, ProcessedNode
from backend.postgres.enums import DocKind, NodeSource, NodeType, SourceOrigin
from backend.tests.unit.sync.conftest import engine, minio, session  # noqa: F401  (DB tests of this folder)

SHA = "a" * 64
DOC_ID = "6f1c2a3e-0000-4000-8000-000000000001"


def word_count(texts):
    return [len(t.split()) for t in texts]


def node(ref, content, ordinal, node_type=NodeType.PARENT, breadcrumb="Test Report 37 › 3 Results", **kw):
    return ProcessedNode(
        ref=ref,
        node_type=node_type,
        ordinal=ordinal,
        breadcrumb=breadcrumb,
        content=content,
        source=kw.pop("source", NodeSource.PRINTED),
        language=kw.pop("language", "en"),
        **kw,
    )


def document(*nodes):
    return ProcessedDocument(
        blob_sha256=SHA,
        route="A1",
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{SHA}/A1/v1/docling.json",
        document=DocumentFields(
            title="Test Report 37",
            doc_kind=DocKind.TEST_REPORT,
            source_origin=SourceOrigin.INTERNAL,
            test_plan_id="TP37",
        ),
        nodes=list(nodes),
    )


def box(page, y0=0.1, y1=0.2):
    return PageBox(page_no=page, x0=0.1, y0=y0, x1=0.9, y1=y1)


@pytest.fixture
def kit():
    return SimpleNamespace(node=node, document=document, box=box, words=word_count, doc_id=DOC_ID)
