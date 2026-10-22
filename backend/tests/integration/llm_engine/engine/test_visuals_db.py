"""T3 inspect_visuals on real rows. Needs DCL_TEST_DATABASE_URL (an empty ParadeDB 0.26.2 database)."""

import math
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.indexing.anchors import content_hash
from backend.indexing.identifiers import content_codes
from backend.llm_engine.engine.tools.visuals import InspectVisualsArgs, inspect_visuals
from backend.llm_engine.local_models import rank_scores
from backend.postgres.enums import AssetKind, DocumentStatus, NodeSource, NodeType
from backend.postgres.models import Asset, Blob, Document, DocumentNode
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[4] / "postgres" / "alembic.ini"
AXES = ["screen", "plot", "valve", "frame", "other"]


def vec(axis, tilt=0.0):
    v = [0.0] * 768
    v[AXES.index(axis)] = 1.0
    v[767] = 0.2 + tilt
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def embed_query(q):
    q = q.lower()
    axis = (
        "screen" if "screen" in q else "plot" if "pressure" in q else "frame" if "ignition" in q else "other"
    )
    return vec(axis)


def rerank(q, passages):
    words = set(q.lower().split())
    return rank_scores([float(len(words & set(p.lower().split()))) for p in passages])


def presign(uri):
    return "https://minio.test/signed/" + uri.removeprefix("s3://")


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

        def blob(sha):
            s.add(Blob(sha256=sha, size_bytes=1, minio_uri=f"s3://dcl-raw/{sha}"))
            s.flush()

        def asset(sha, kind, name):
            a = Asset(minio_uri=f"s3://dcl-assets/{name}", blob_sha256=sha, kind=kind)
            s.add(a)
            s.flush()
            return a.asset_id

        def doc(title, route, status=DocumentStatus.ACTIVE, plan="TP07"):
            d = Document(
                route=route,
                status=status,
                title=title,
                doc_kind="hardware_photo" if route == "D" else "test_report",
                test_plan_id=plan,
                staged_payload_uri="s3://dcl-cir/x/staged.json" if status == DocumentStatus.HALTED else None,
            )
            s.add(d)
            s.flush()
            return d

        def node(d, content, node_type, axis, *, asset_id=None, image_axis=None, tilt=0.0, ordinal=0):
            n = DocumentNode(
                doc_id=d.doc_id,
                node_type=node_type,
                ordinal=ordinal,
                breadcrumb=f"{d.title} › {content[:20]}",
                content=content,
                content_codes=content_codes(content),
                content_sha256=content_hash(content),
                embedding=vec(axis),
                image_embedding=vec(image_axis, tilt) if image_axis else None,
                page_no=1,
                source=NodeSource.VLM,
                doc_kind=d.doc_kind,
                test_plan_id=d.test_plan_id,
                source_origin="internal",
                trust_tier=2,
                doc_status=d.status,
                asset_id=asset_id,
            )
            s.add(n)
            s.flush()
            return n

        sha_a, sha_b, sha_c, sha_d = "a" * 64, "b" * 64, "c" * 64, "d" * 64
        for sha in (sha_a, sha_b, sha_c, sha_d):
            blob(sha)
        photos = doc("TP07 post-test photos", "D")
        web_a = asset(sha_a, AssetKind.PHOTO_WEB, "photos/a_web.jpg")
        asset(sha_a, AssetKind.PHOTO_THUMB, "photos/a_thumb.jpg")
        web_b = asset(sha_b, AssetKind.PHOTO_WEB, "photos/b_web.jpg")
        out["ref"] = web_a
        node(
            photos,
            "Catalyst screen deformed after T04, discoloured ring",
            NodeType.PHOTO,
            "screen",
            asset_id=web_a,
            image_axis="screen",
        )
        node(
            photos,
            "Catalyst screen intact before T01",
            NodeType.PHOTO,
            "screen",
            asset_id=web_b,
            image_axis="screen",
            tilt=0.3,
            ordinal=1,
        )
        report = doc("Test Report 41", "A1")
        fig = asset(sha_c, AssetKind.FIGURE_CROP, "figures/c.png")
        node(
            report,
            "Chamber pressure trace of T04, peak 12.4 bar",
            NodeType.FIGURE,
            "plot",
            asset_id=fig,
            image_axis="plot",
        )
        node(report, "The catalyst screen was inspected.", NodeType.CHILD, "screen", ordinal=1)
        other_plan = doc("TP08 photos", "D", plan="TP08")
        web_d = asset(sha_d, AssetKind.PHOTO_WEB, "photos/d_web.jpg")
        node(
            other_plan,
            "Catalyst screen of TP08 thruster",
            NodeType.PHOTO,
            "screen",
            asset_id=web_d,
            image_axis="screen",
            tilt=0.1,
        )
        halted = doc("TP07 halted photos", "D", status=DocumentStatus.HALTED)
        node(halted, "Catalyst screen cracked (halted)", NodeType.PHOTO, "screen", image_axis="screen")
        s.commit()
    return out


def run(engine, **args):
    with Session(engine) as s:
        return inspect_visuals(
            s, InspectVisualsArgs(**args), embed_query=embed_query, rerank=rerank, presign=presign
        )


def test_kinds_and_plan_filter_and_hidden_documents(engine, ids):
    result = run(engine, query="catalyst screen deformed", kinds=["hardware_photo"], test_plan_ids=["TP07"])
    visuals = result.result["visuals"]
    assert visuals and all(v["node_type"] in ("photo", "figure") for v in visuals)
    titles = {v["title"] for v in visuals}
    assert "TP08 photos" not in titles and "TP07 halted photos" not in titles
    assert visuals[0]["reading"].startswith("Catalyst screen deformed")
    assert all(v["node_type"] != "child" for v in visuals)
    plots = run(engine, query="chamber pressure trace", kinds=["plot_figure"])
    assert [v["node_type"] for v in plots.result["visuals"]] == ["figure"]


def test_urls_documents_and_no_node_ids(engine, ids):
    result = run(engine, query="catalyst screen deformed", kinds=["hardware_photo"], test_plan_ids=["TP07"])
    top = result.result["visuals"][0]
    assert top["url_web"] == "https://minio.test/signed/dcl-assets/photos/a_web.jpg"
    assert top["url_thumb"] == "https://minio.test/signed/dcl-assets/photos/a_thumb.jpg"
    assert top["asset_uri"] == "s3://dcl-assets/photos/a_web.jpg" and top["title"] == "TP07 post-test photos"
    assert result.provenance[0].doc_id and result.provenance[0].anchor.count(":") == 2
    assert "node_id" not in str(result.result)


def test_similar_images_rank_by_image_embedding_and_skip_the_reference(engine, ids):
    result = run(engine, similar_to_asset_id=ids["ref"], kinds=["hardware_photo"])
    readings = [v["reading"] for v in result.result["visuals"]]
    assert not any(r.startswith("Catalyst screen deformed") for r in readings)  # the reference itself
    assert readings[0] == "Catalyst screen of TP08 thruster"  # tilt 0.1 is closer than 0.3
    assert "Catalyst screen intact before T01" in readings
    assert all("halted" not in r for r in readings)
    assert result.result["visuals"][0]["similarity"] > 0.9
