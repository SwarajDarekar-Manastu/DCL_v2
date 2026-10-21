"""Hybrid retrieval on real document_nodes rows; needs DCL_TEST_DATABASE_URL (empty ParadeDB 0.26.2).

The BM25 DDL is the one sent to S1 for the pinned migration (bm25_ddl_sent_to_s1.sql); once that migration is
on main the fixture stops creating it.
"""

import math
import os
import uuid
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.indexing import retrieval
from backend.indexing.anchors import content_hash
from backend.indexing.identifiers import content_codes
from backend.indexing.retrieval import Scope, SearchFilters, search
from backend.llm_engine.local_models import ModelServerUnavailable, rank_scores
from backend.postgres.enums import DocumentStatus, NodeSource, NodeType
from backend.postgres.models import Document, DocumentNode, DocumentRelation
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
BM25_DDL = Path(__file__).with_name("bm25_ddl_sent_to_s1.sql").read_text()
TOPICS = ["pressure", "temperature", "valve", "catalyst", "calibration", "nozzle"]


def topic_vector(topic: str) -> list[float]:
    vector = [0.0] * 768
    vector[TOPICS.index(topic)] = 1.0
    vector[767] = 0.2  # every vector shares a little, so distances are finite and ordered
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


def embed_query(query: str) -> list[float]:
    for topic in TOPICS:
        if topic in query.lower() or (topic == "pressure" and "druck" in query.lower()):
            return topic_vector(topic)
    return topic_vector("nozzle")


def rerank(query: str, passages: list[str]):
    words = set(query.lower().split())
    return rank_scores([float(len(words & set(p.lower().split()))) for p in passages])


def rerank_down(query, passages):
    raise ModelServerUnavailable("models role unreachable")


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
        with eng.begin() as conn:
            # Migration 0004 (on main) creates the BM25 indexes; apply the local DDL only if a bare schema lacks them.
            present = conn.execute(
                text("select count(*) from pg_indexes where indexname in ('bm25_document_nodes', 'bm25_documents')")
            ).scalar()
            if not present:
                conn.execute(text(BM25_DDL))
        yield eng
        with eng.begin() as conn:
            conn.execute(
                text("DROP INDEX IF EXISTS bm25_document_nodes; DROP INDEX IF EXISTS bm25_documents")
            )
        eng.dispose()
        command.downgrade(config, "base")


@pytest.fixture(scope="module")
def corpus(engine):
    """Documents and nodes as S1's commit would write them (denormalized filter columns included)."""
    ids = {}
    with Session(engine) as session:

        def doc(
            name, status=DocumentStatus.ACTIVE, test_plan_id=None, doc_date=None, origin="internal", **kw
        ):
            d = Document(
                route="A1",
                status=status,
                title=name,
                test_plan_id=test_plan_id,
                doc_date=doc_date,
                source_origin=origin,
                staged_payload_uri="s3://dcl-cir/x/staged.json" if status == DocumentStatus.HALTED else None,
                **kw,
            )
            session.add(d)
            session.flush()
            ids[name] = d.doc_id
            return d

        def node(
            d, content, topic, node_type=NodeType.CHILD, parent=None, page=1, language="en", content_en=None
        ):
            n = DocumentNode(
                doc_id=d.doc_id,
                parent_node_id=parent.node_id if parent else None,
                node_type=node_type,
                ordinal=page,
                breadcrumb=f"{d.title} › Results",
                language=language,
                content=content,
                content_en=content_en,
                content_codes=content_codes(content),
                content_sha256=content_hash(content),
                embedding=topic_vector(topic),
                page_no=page,
                source=NodeSource.PRINTED,
                doc_kind="test_report",
                test_plan_id=d.test_plan_id,
                source_origin=d.source_origin,
                trust_tier=2,
                doc_status=d.status,
            )
            session.add(n)
            session.flush()
            return n

        tp37 = doc("Test Report 37", test_plan_id="TP37", doc_date=date(2024, 5, 2))
        for p in range(1, 13):
            parent = node(
                tp37, f"Section {p} of the TP37 hot fire results.", "pressure", NodeType.PARENT, page=p
            )
            node(
                tp37,
                f"TP37 run {p}: chamber pressure rose to {p}.4 bar during hot fire.",
                "pressure",
                parent=parent,
                page=p,
            )
            node(tp37, f"TP37 run {p}: the catalyst bed stayed nominal.", "catalyst", parent=parent, page=p)
        cal = doc("Calibration sheet")
        cal_parent = node(cal, "Transducer calibration records.", "calibration", NodeType.PARENT)
        node(
            cal,
            "Transducer PT-104 was calibrated against the reference gauge.",
            "calibration",
            parent=cal_parent,
        )
        de = doc("Heizelement Datenblatt", origin="external_kept")
        de_parent = node(de, "Technische Daten.", "temperature", NodeType.PARENT, language="de")
        node(
            de,
            "Der Kammerdruck des Prüfstands betrug 12,4 bar.",
            "pressure",
            parent=de_parent,
            language="de",
            content_en="The chamber pressure of the test stand was 12.4 bar.",
        )
        old = doc("Valve report v1", doc_date=date(2023, 1, 1))
        new = doc("Valve report v2", doc_date=date(2024, 1, 1))
        for d in (old, new):
            vp = node(d, "Valve section.", "valve", NodeType.PARENT)
            node(d, "The solenoid valve SV-1 opened in 12 ms.", "valve", parent=vp)
        a, b = sorted([old.doc_id, new.doc_id])
        session.add(DocumentRelation(doc_id_a=a, doc_id_b=b, relation="NEAR_DUPLICATE", score=0.97))
        sup = doc("Old standard", status=DocumentStatus.SUPERSEDED)
        node(sup, "Superseded nozzle requirement text.", "nozzle", NodeType.CHILD)
        halted = doc("Halted report", status=DocumentStatus.HALTED)
        node(halted, "Halted nozzle measurement text.", "nozzle", NodeType.CHILD)
        session.commit()
    return ids


def run(engine, query, **kw):
    with Session(engine) as session:
        return search(session, query, embed_query=embed_query, rerank=kw.pop("rerank", rerank), **kw)


def test_identifier_query_hits_lexically_without_dense_help(engine, corpus):
    result = run(engine, "PT104 nozzle")  # the dense vector points at the nozzle topic
    assert any("PT-104" in h.passage for h in result.hits)
    assert result.hits[0].doc_id == corpus["Calibration sheet"]


def test_one_test_plan_takes_the_exact_path_and_fills_k(engine, corpus):
    result = run(engine, "chamber pressure", filters=SearchFilters(test_plan_ids=["TP37"]), k=8)
    assert result.dense_path == "exact"
    assert len(result.hits) == 8
    assert {h.test_plan_id for h in result.hits} == {"TP37"}


def test_children_collapse_to_their_parent(engine, corpus):
    result = run(
        engine, "TP37 run 3 chamber pressure catalyst", filters=SearchFilters(test_plan_ids=["TP37"]), k=30
    )
    parents = [h.parent_text for h in result.hits]
    assert len(parents) == len(set(parents))
    hit = next(h for h in result.hits if h.page_no == 3)
    assert hit.parent_text == "Section 3 of the TP37 hot fire results."
    assert hit.anchor.startswith("page:3:")


def test_superseded_and_halted_documents_are_excluded_by_default(engine, corpus):
    default = run(engine, "nozzle requirement measurement text", k=30)
    assert corpus["Old standard"] not in {h.doc_id for h in default.hits}
    assert corpus["Halted report"] not in {h.doc_id for h in default.hits}
    widened = run(
        engine, "nozzle requirement measurement text", k=30, filters=SearchFilters(include_superseded=True)
    )
    assert corpus["Old standard"] in {h.doc_id for h in widened.hits}
    assert corpus["Halted report"] not in {h.doc_id for h in widened.hits}


def test_reranker_down_keeps_rrf_order_and_says_so(engine, corpus):
    result = run(
        engine, "chamber pressure", rerank=rerank_down, filters=SearchFilters(test_plan_ids=["TP37"])
    )
    assert result.warnings == ["reranker unavailable; results are in RRF order"]
    assert [h.rrf_score for h in result.hits] == sorted((h.rrf_score for h in result.hits), reverse=True)
    assert all(h.rerank_score is None for h in result.hits)


def test_english_query_finds_the_german_node_lexically_through_content_en(engine, corpus):
    result = run(engine, "test stand", filters=SearchFilters(source_origins=["external_kept"]))
    assert result.hits and result.hits[0].doc_id == corpus["Heizelement Datenblatt"]
    assert result.hits[0].language == "de"
    assert result.leg_counts["lexical"] >= 1


def test_german_query_uses_the_german_stem_field(engine, corpus):
    with Session(engine) as session:
        where = retrieval.build_where(SearchFilters(), Scope.CHILD)
        ids = retrieval.lexical_leg(session, "Kammerdrucks Prüfstand", [], ["de", "en"], where)
    assert len(ids) == 1


def test_near_duplicate_keeps_the_newer_document(engine, corpus):
    result = run(engine, "solenoid valve SV-1", k=10)
    doc_ids = [h.doc_id for h in result.hits]
    assert corpus["Valve report v2"] in doc_ids and corpus["Valve report v1"] not in doc_ids
    kept = next(h for h in result.hits if h.doc_id == corpus["Valve report v2"])
    assert kept.also_in == [corpus["Valve report v1"]]


def test_unfiltered_search_takes_the_hnsw_path_when_the_selection_is_large(engine, corpus, monkeypatch):
    monkeypatch.setattr(retrieval, "EXACT_PATH_MAX", 5)
    result = run(engine, "chamber pressure", k=5)
    assert result.dense_path == "hnsw"
    assert result.hits


def test_scope_tables_only_returns_nothing_without_tables(engine, corpus):
    assert run(engine, "chamber pressure", scope=Scope.TABLES_ONLY).hits == []


def test_node_ids_never_leave_the_request(engine, corpus):
    hit = run(engine, "chamber pressure", k=1).hits[0]
    assert "node_id" not in hit.model_dump()
    assert uuid.UUID(str(hit.doc_id))
