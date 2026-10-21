"""Engine tools on real rows. Needs DCL_TEST_DATABASE_URL (an empty ParadeDB 0.26.2 database)."""

import math
import os
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.indexing.anchors import content_hash
from backend.indexing.identifiers import content_codes
from backend.indexing.retrieval import SearchFilters
from backend.llm_engine.engine.tools import Provenance
from backend.llm_engine.engine.tools.code_diagrams import CodeDiagramArgs, inspect_code_and_diagrams
from backend.llm_engine.engine.tools.documents import (
    CatalogArgs,
    GetDocumentArgs,
    catalog_lookup,
    get_document,
)
from backend.llm_engine.engine.tools.search import SearchDocumentsArgs, search_documents
from backend.llm_engine.local_models import rank_scores
from backend.postgres.enums import DocumentStatus, NodeSource, NodeType
from backend.postgres.models import Document, DocumentNode, Entity, EntityAlias, ReviewFlag
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[4] / "postgres" / "alembic.ini"
TOPICS = ["pressure", "peroxide", "code", "valve", "other"]


def vec(topic):
    v = [0.0] * 768
    v[TOPICS.index(topic)] = 1.0
    v[767] = 0.2
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def embed_query(q):
    q = q.lower()
    return vec("peroxide" if "peroxide" in q or "htp" in q else "pressure" if "pressure" in q else "other")


def rerank(q, passages):
    words = set(q.lower().split())
    return rank_scores([float(len(words & set(p.lower().split()))) for p in passages])


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


@pytest.fixture(scope="module")
def ids(engine):
    out = {}
    with Session(engine) as s:

        def doc(title, kind="test_report", status=DocumentStatus.ACTIVE, **kw):
            d = Document(
                route="A1",
                status=status,
                title=title,
                doc_kind=kind,
                staged_payload_uri="s3://dcl-cir/x/staged.json" if status == DocumentStatus.HALTED else None,
                **kw,
            )
            s.add(d)
            s.flush()
            out[title] = d.doc_id
            return d

        def node(d, content, topic="other", node_type=NodeType.CHILD, parent=None, ordinal=0, page=1, **kw):
            n = DocumentNode(
                doc_id=d.doc_id,
                parent_node_id=parent.node_id if parent else None,
                node_type=node_type,
                ordinal=ordinal,
                breadcrumb=kw.pop("breadcrumb", f"{d.title} › 3 Results"),
                content=content,
                content_codes=content_codes(content),
                content_sha256=content_hash(content),
                embedding=vec(topic),
                page_no=page,
                source=NodeSource.PRINTED,
                doc_kind=d.doc_kind,
                test_plan_id=d.test_plan_id,
                source_origin=d.source_origin,
                trust_tier=2,
                doc_status=d.status,
                **kw,
            )
            s.add(n)
            s.flush()
            return n

        tr = doc("Test Report 37", test_plan_id="TP37", doc_date=date(2024, 5, 2))
        p1 = node(
            tr,
            "Hot fire results. The chamber pressure reached 12.4 bar.",
            "pressure",
            NodeType.PARENT,
            ordinal=0,
            page=8,
        )
        node(
            tr,
            "The chamber pressure reached 12.4 bar in hot fire 3.",
            "pressure",
            parent=p1,
            ordinal=1,
            page=8,
        )
        p2 = node(
            tr,
            "Calibration of transducer PT-104 against the reference gauge.",
            "other",
            NodeType.PARENT,
            ordinal=2,
            page=9,
            breadcrumb="Test Report 37 › 4 Calibration",
        )
        node(
            tr,
            "Transducer PT-104 was calibrated.",
            "other",
            parent=p2,
            ordinal=3,
            page=9,
            breadcrumb="Test Report 37 › 4 Calibration",
        )
        lib = doc("Peroxide handling note", kind="datasheet", source_origin="external_kept")
        lp = node(
            lib, "Wasserstoffperoxid muss kühl gelagert werden.", "other", NodeType.PARENT, language="de"
        )
        node(
            lib, "Wasserstoffperoxid muss kühl gelagert werden.", "other", parent=lp, ordinal=1, language="de"
        )
        htp = Entity(type="propellant", canonical_name="HTP", canonical_key="htp", created_by="seed")
        s.add(htp)
        s.flush()
        out["HTP"] = htp.entity_id
        s.add(
            EntityAlias(
                type="propellant",
                alias_key="wasserstoffperoxid",
                alias="Wasserstoffperoxid",
                entity_id=htp.entity_id,
                created_by="seed",
            )
        )
        for rev, status in (("C", DocumentStatus.ACTIVE), ("B", DocumentStatus.SUPERSEDED)):
            doc(f"ECSS-E-ST-35{rev}", kind="standard", status=status, standard_id=f"ECSS-E-ST-35{rev}")
        halted = doc("TP07 run sheet", status=DocumentStatus.HALTED, test_plan_id="TP07")
        s.add(
            ReviewFlag(
                case_key=f"{halted.doc_id}:1",
                doc_id=halted.doc_id,
                page_or_sheet="1",
                fingerprint="f" * 64,
                flag_type="LOW_CONFIDENCE_EXTRACTION",
                severity="HARD",
                status="OPEN",
            )
        )
        code = doc("nozzle_calc.py", kind="code")
        node(
            code,
            "import math\nMAX_CHAMBER_PSI = 300",
            "code",
            NodeType.MODULE_HEADER,
            line_start=1,
            line_end=3,
            page=None,
        )
        node(
            code,
            "def compute_expansion_ratio(self, gamma, mach): ...",
            "code",
            NodeType.CODE_SYMBOL,
            ordinal=1,
            line_start=88,
            line_end=142,
            page=None,
            metadata_={
                "qualname": "NozzleSizer.compute_expansion_ratio",
                "symbol": "compute_expansion_ratio",
                "calls": ["isentropic.area_ratio_from_mach"],
            },
        )
        node(
            code,
            "def size(self): return self.compute_expansion_ratio(1.2, 3)",
            "code",
            NodeType.CODE_SYMBOL,
            ordinal=2,
            line_start=150,
            line_end=160,
            page=None,
            metadata_={"qualname": "NozzleSizer.size", "calls": ["NozzleSizer.compute_expansion_ratio"]},
        )
        diagram = doc(
            "Thruster Config Rev C",
            kind="diagram",
            catalog={
                "nodes": [
                    {"id": "1", "tag": "TK-1"},
                    {"id": "2", "tag": "F-101"},
                    {"id": "3", "tag": "SV-1"},
                    {"id": "4", "tag": "INJ-14"},
                ],
                "edges": [
                    {"source": "1", "target": "2"},
                    {"source": "2", "target": "3"},
                    {"source": "3", "target": "4"},
                ],
            },
        )
        out["diagram"] = diagram.doc_id
        s.commit()
    return out


def test_search_quotes_hits_with_provenance_and_anchors(engine, ids):
    with Session(engine) as s:
        out = search_documents(
            s,
            SearchDocumentsArgs(
                query="chamber pressure hot fire", filters=SearchFilters(test_plan_ids=["TP37"])
            ),
            embed_query=embed_query,
            rerank=rerank,
        )
    assert "12.4 bar" in out.display and "Test Report 37, p. 8" in out.display
    first = out.provenance[0]
    assert first.provenance is Provenance.INTERNAL_REPORT and first.anchor.startswith("page:8:")


def test_alias_expansion_reaches_the_german_surface(engine, ids):
    with Session(engine) as s:
        out = search_documents(
            s,
            SearchDocumentsArgs(
                query="HTP storage",
                entity_ids=[ids["HTP"]],
                filters=SearchFilters(source_origins=["external_kept"]),
            ),
            embed_query=lambda q: vec("pressure"),
            rerank=rerank,
        )
    assert out.provenance and out.provenance[0].provenance is Provenance.VENDOR_CLAIM
    assert "language de" in out.display
    assert "Wasserstoffperoxid" in out.result["alias_surfaces"]
    assert (
        out.result["leg_counts"]["lexical"] >= 1
    )  # the German surface matched lexically, not only by vector


def test_zero_hits_widen_in_order_and_say_so(engine, ids):
    with Session(engine) as s:
        out = search_documents(
            s,
            SearchDocumentsArgs(
                query="PT104 calibration",
                filters=SearchFilters(doc_kinds=["standard"], test_plan_ids=["TP99"]),
            ),
            embed_query=embed_query,
            rerank=rerank,
        )
    assert out.result["widened"][:2] == ["dropped doc_kinds", "dropped test_plan_ids"]
    assert any("widened" in w for w in out.warnings) and "PT-104" in out.display


def test_get_document_reads_parents_in_order_with_labels(engine, ids):
    with Session(engine) as s:
        out = get_document(s, GetDocumentArgs(title="Test Report 37"))
        section = get_document(s, GetDocumentArgs(doc_id=ids["Test Report 37"], section="4 Calibration"))
    assert out.result["parents_returned"] == 2 and out.display.index("12.4 bar") < out.display.index("PT-104")
    assert section.result["parents_returned"] == 1 and "PT-104" in section.display


def test_catalog_lists_halted_items_with_case_keys_and_standards_with_revisions(engine, ids):
    with Session(engine) as s:
        halted = catalog_lookup(s, CatalogArgs(kind="halted"))
        standards = catalog_lookup(s, CatalogArgs(kind="standards"))
        plan = catalog_lookup(s, CatalogArgs(test_plan_id="TP37"))
    assert halted.result[0]["case_keys"] == [f"{ids['TP07 run sheet']}:1"] and "review case" in halted.display
    assert {r["title"] for r in standards.result} == {
        "ECSS-E-ST-35C",
        "ECSS-E-ST-35B",
    } and "SUPERSEDED" in standards.display
    assert [r["title"] for r in plan.result] == ["Test Report 37"]


def test_code_symbol_lookup_with_callers(engine, ids):
    with Session(engine) as s:
        out = inspect_code_and_diagrams(
            s, CodeDiagramArgs(mode="callers_callees", symbol="compute_expansion_ratio")
        )
    entry = out.result[0]
    assert entry["qualname"] == "NozzleSizer.compute_expansion_ratio" and entry["lines"] == [88, 142]
    assert entry["callers"] == ["NozzleSizer.size"] and "MAX_CHAMBER_PSI" in entry["module_header"]
    assert out.provenance[0].anchor.startswith("line:88:")


def test_diagram_path_from_the_catalog(engine, ids):
    with Session(engine) as s:
        out = inspect_code_and_diagrams(
            s, CodeDiagramArgs(mode="diagram_path", diagram_title="Rev C", from_tag="TK-1", to_tag="INJ-14")
        )
    assert out.display == "Thruster Config Rev C: Path: TK-1 → F-101 → SV-1 → INJ-14"
