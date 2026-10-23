"""New entities from enrichment are written with created_by = system (file 05 entities CHECK)."""

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from backend.indexing.commit import _entity_ids
from backend.llm_engine.enrichment.entities import EntityDecisions, NewEntity
from backend.postgres.models import Document, Entity
from backend.tests.unit.sync.conftest import engine, session  # noqa: F401


def test_new_entities_are_created_by_system(session):  # noqa: F811
    doc = Document(route="A1", status="PROCESSING", title="ariane")
    session.add(doc)
    session.flush()
    new = NewEntity(
        type="organization", canonical_name="ArianeGroup", canonical_key="arianegroup", first_seen_doc_id=None
    )
    plan = SimpleNamespace(doc_id=doc.doc_id, entities=EntityDecisions(new_entities=[new]))
    ids, created = _entity_ids(session, plan)
    session.flush()
    row = session.scalars(select(Entity)).one()
    assert (created, row.created_by, row.first_seen_doc_id, ids[new.ref]) == (
        1,
        "system",
        doc.doc_id,
        row.entity_id,
    )
    assert isinstance(row.entity_id, uuid.UUID)
