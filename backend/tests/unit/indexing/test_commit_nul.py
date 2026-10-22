"""The commit strips NUL from everything it writes (PostgreSQL text and jsonb refuse it)."""

import uuid
from dataclasses import dataclass, field

from backend.dispatcher.contract import DocumentFields, ProcessedDocument, ProcessedNode
from backend.indexing.commit import strip_nul


@dataclass
class _Node:
    content: str
    embedding: list[float] | None = None


@dataclass
class _Plan:
    doc_id: uuid.UUID
    nodes: list[_Node]
    document: dict = field(default_factory=dict)


def test_pydantic_documents_lose_nul_at_any_depth():
    doc = ProcessedDocument(
        blob_sha256="a" * 64,
        route="A1",
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{'a' * 64}/A1/v1/",
        document=DocumentFields(title="Heat\x00 transfer"),
        nodes=[
            ProcessedNode(
                ref="n1",
                node_type="child",
                ordinal=0,
                content="q\x00 = h A",
                source="printed",
                metadata={"k\x00": ["v\x00", 1]},
            )
        ],
    )
    clean = strip_nul(doc)
    assert clean.document.title == "Heat transfer"
    assert clean.nodes[0].content == "q = h A"
    assert clean.nodes[0].metadata == {"k": ["v", 1]}
    assert doc.document.title == "Heat\x00 transfer"  # the input is not mutated


def test_dataclass_plans_keep_ids_and_vectors():
    doc_id = uuid.uuid4()
    plan = strip_nul(_Plan(doc_id, [_Node("a\x00b", [0.5, 0.25])], {"search_text": ("x\x00",)}))
    assert plan == _Plan(doc_id, [_Node("ab", [0.5, 0.25])], {"search_text": ("x",)})
