"""Entity curation: search with counts, merge (aliases, mentions, documents.entity_ids, old name kept as an
alias), split (aliases and their mentions to a new entity), audit rows."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api import entities as entities_api
from backend.api.auth import ConsoleRole, ConsoleUser
from backend.postgres.models import (
    AuditEvent,
    Document,
    DocumentNode,
    Entity,
    EntityAlias,
    EntityMention,
)
from backend.postgres.session import get_session

USER = ConsoleUser(oid="o", name="Ravi", email="ravi@manastu.space", roles=[ConsoleRole.REVIEWER])


def _client(session):
    app = FastAPI()
    app.include_router(entities_api.router)
    app.dependency_overrides[entities_api.Reviewer.__metadata__[0].dependency] = lambda: USER
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def _seed(session):
    doc = Document(route="A1", status="ACTIVE", title="TP7 report")
    session.add(doc)
    session.flush()
    node = DocumentNode(
        doc_id=doc.doc_id, node_type="child", ordinal=0, content="HTP and H2O2 98%", source="printed"
    )
    session.add(node)
    htp = Entity(
        type="propellant",
        canonical_name="High-test peroxide",
        canonical_key="high-test peroxide",
        created_by="system",
    )
    h2o2 = Entity(
        type="propellant",
        canonical_name="Hydrogen peroxide",
        canonical_key="hydrogen peroxide",
        created_by="system",
    )
    session.add_all([htp, h2o2])
    session.flush()
    session.add_all(
        [
            EntityAlias(
                type="propellant",
                alias_key="htp",
                entity_id=htp.entity_id,
                alias="HTP",
                created_by="system_exact",
            ),
            EntityAlias(
                type="propellant",
                alias_key="h2o2",
                entity_id=h2o2.entity_id,
                alias="H2O2",
                created_by="system_exact",
            ),
            EntityAlias(
                type="propellant",
                alias_key="h2o2 98%",
                entity_id=h2o2.entity_id,
                alias="H2O2 98%",
                created_by="system_exact",
            ),
            EntityMention(
                node_id=node.node_id, doc_id=doc.doc_id, entity_id=htp.entity_id, surface="HTP", source="llm"
            ),
            EntityMention(
                node_id=node.node_id,
                doc_id=doc.doc_id,
                entity_id=h2o2.entity_id,
                surface="H2O2 98%",
                source="llm",
            ),
        ]
    )
    doc.entity_ids = [htp.entity_id, h2o2.entity_id]
    session.commit()
    return doc, htp, h2o2


def test_search_finds_by_alias_with_counts(session):
    _, htp, _ = _seed(session)
    page = _client(session).get("/entities", params={"query": "htp"}).json()
    assert page["total"] == 1
    (item,) = page["items"]
    assert (
        item["canonical_name"],
        item["mentions"],
        item["documents"],
        [a["alias"] for a in item["aliases"]],
    ) == ("High-test peroxide", 1, 1, ["HTP"])


def test_merge_folds_the_source_into_the_target(session):
    doc, htp, h2o2 = _seed(session)
    client = _client(session)
    view = client.post(
        "/entities/merge",
        json={"target_entity_id": str(h2o2.entity_id), "source_entity_ids": [str(htp.entity_id)]},
    ).json()
    assert (view["mentions"], view["documents"]) == (2, 1)
    assert sorted(a["alias"] for a in view["aliases"]) == ["H2O2", "H2O2 98%", "HTP", "High-test peroxide"]
    assert session.get(Entity, htp.entity_id) is None
    assert session.get(Document, doc.doc_id).entity_ids == [h2o2.entity_id]
    assert session.scalars(select(AuditEvent.action)).all() == ["merge"]
    assert (
        client.post(
            "/entities/merge",
            json={"target_entity_id": str(h2o2.entity_id), "source_entity_ids": [str(h2o2.entity_id)]},
        ).status_code
        == 422
    )


def test_split_moves_aliases_and_their_mentions(session):
    doc, htp, h2o2 = _seed(session)
    client = _client(session)
    view = client.post(
        "/entities/split",
        json={"entity_id": str(h2o2.entity_id), "alias_keys": ["h2o2 98%"], "canonical_name": "H2O2 98 %"},
    ).json()
    assert ([a["alias_key"] for a in view["aliases"]], view["mentions"], view["created_by"]) == (
        ["h2o2 98%"],
        1,
        "operator",
    )
    assert (
        session.scalars(select(EntityMention.entity_id).where(EntityMention.surface == "H2O2 98%")).one()
        != h2o2.entity_id
    )
    ids = session.get(Document, doc.doc_id).entity_ids
    assert h2o2.entity_id not in ids and len(ids) == 2  # the old entity is no longer mentioned there
    assert (
        client.post(
            "/entities/split",
            json={"entity_id": str(h2o2.entity_id), "alias_keys": ["nope"], "canonical_name": "x"},
        ).status_code
        == 422
    )
