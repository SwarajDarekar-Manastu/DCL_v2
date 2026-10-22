"""Route C through dispatch on a migrated PostgreSQL + MinIO: release of parked documents, enqueueing,
processing, the validation gate (HALTED with a staged payload), and rules that clear the flags.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT.
"""

import hashlib
import io

from sqlalchemy import select

from backend.dispatcher.contract import DocumentFields, Flag, FlagAnchor, ProcessedDocument
from backend.dispatcher.routing import PROCESSED_MARK, dispatch
from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import Blob, Document, DriveFolder, DriveItem, ReviewFlag, Rule
from backend.review.staged import apply_severity_policy, load_staged
from backend.routes.c_telemetry.pipeline import process_document
from backend.storage.minio import CIR, RAW, BucketStore, raw_key
from backend.tests.unit.routes.c_telemetry.conftest import labjack_bytes

FOLDERS = [
    ("ROOT", "APU Injector", None, "APU Injector"),
    ("F-TP12", "Test Plan 12", "ROOT", "APU Injector/Test Plan 12"),
    ("F-RUN", "Pressure_Data_Files", "F-TP12", "APU Injector/Test Plan 12/Pressure_Data_Files"),
]


def _seed(session, minio, files: dict[str, bytes]) -> None:
    for item_id, name, parent, path in FOLDERS:
        session.add(
            DriveFolder(
                drive_id="D",
                item_id=item_id,
                root_name="APU Injector",
                name=name,
                parent_item_id=parent,
                path_cached=path,
            )
        )
    for name, data in files.items():
        sha = hashlib.sha256(data).hexdigest()
        minio.put_object(RAW, raw_key(sha), io.BytesIO(data), len(data))
        session.add(Blob(sha256=sha, size_bytes=len(data), minio_uri=f"s3://dcl-raw/{raw_key(sha)}"))
        session.flush()
        session.add(
            DriveItem(
                drive_id="D",
                item_id=name,
                root_name="APU Injector",
                name=name,
                extension="." + name.rsplit(".", 1)[-1],
                parent_item_id="F-RUN",
                path_cached=f"{FOLDERS[-1][3]}/{name}",
                status=DriveItemStatus.LANDED,
                blob_sha256=sha,
                detected_mime="text/plain",
                size_bytes=len(data),
            )
        )
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    session.commit()


def _files():
    run, _ = labjack_bytes(rows=600)
    other, _ = labjack_bytes(rows=400, gap_at=None)
    return {
        "TP12_T01.dat": run,
        "TP12_T02.dat_fail": other,
        "TP12_legacy.dat": b"time\tAIN0\n0.0\t1.2\n0.001\t1.3\n",
    }


def _docs(session):
    return {d.title: d for d in session.scalars(select(Document))}


def test_parked_documents_are_released_processed_and_halted(session, minio):
    _seed(session, minio, _files())
    first = dispatch(session, minio, section_file_sets=())
    assert (first.created, first.waiting, first.released, first.to_process) == (3, 3, 0, [])

    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    session.commit()
    queued = []
    second = dispatch(session, minio, section_file_sets=(), enqueue=queued.append)
    docs = _docs(session)
    assert (second.created, second.released) == (0, 2)
    assert {r.task for r in queued} == {"dcl.process.route_c"} and {r.queue for r in queued} == {
        "telemetry_stream"
    }
    assert {r.doc_id for r in queued} == {docs["TP12_T01"].doc_id, docs["TP12_T02"].doc_id}
    assert docs["TP12_legacy"].status == "WAITING_FOR_ROUTE"  # no adapter for this layout yet

    outcome = process_document(session, minio, docs["TP12_T01"].doc_id)
    session.commit()
    document = session.get(Document, docs["TP12_T01"].doc_id)
    assert (outcome.status, outcome.rows, outcome.channels, outcome.hard_flags) == ("HALTED", 600, 4, 2)
    assert (document.status, document.doc_kind, document.trust_tier, document.unit_count) == (
        "HALTED",
        "telemetry_run",
        1,
        4,
    )
    assert document.staged_payload_uri.endswith("/staged.json")
    flags = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == document.doc_id)).all()
    assert sorted((f.flag_type, f.severity, f.route, f.anchor["channel"]) for f in flags) == [
        ("UNIT_AMBIGUITY", "HARD", "C", "y0"),
        ("UNIT_AMBIGUITY", "HARD", "C", "y1"),
    ]
    staged = load_staged(BucketStore(minio, CIR), document)
    assert staged.telemetry_runs[0].n_rows == 600
    assert {f.fingerprint for f in staged.flags} == {f.fingerprint for f in flags}

    again = process_document(session, minio, document.doc_id)
    assert again.status == "HALTED" and again.rows is None  # not PROCESSING any more: left alone
    assert dispatch(session, minio, section_file_sets=(), enqueue=queued.append).released == 0


def test_a_rule_for_every_channel_clears_the_gate(session, minio):
    _seed(session, minio, {"TP12_T01.dat": labjack_bytes(rows=300)[0]})
    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    session.add(
        Rule(
            rule_type="channel_map",
            origin="operator",
            scope_folder_id="F-RUN",
            body={
                "channels": {
                    "y0": {
                        "canonical_name": "pt_101_bar_g",
                        "physical_quantity": "pressure",
                        "unit": "bar",
                        "gauge_or_abs": "gauge",
                    },
                    "y1": {"canonical_name": "tc_1_k", "physical_quantity": "temperature", "unit": "degC"},
                },
                "ambient_condition": "SEA_LEVEL",
            },
            created_by="test",
        )
    )
    session.commit()
    result = dispatch(session, minio, section_file_sets=())
    (release,) = result.to_process
    outcome = process_document(session, minio, release.doc_id)
    session.commit()
    document = session.get(Document, release.doc_id)
    assert (outcome.status, outcome.hard_flags, document.staged_payload_uri) == ("WAITING_FOR_ROUTE", 0, None)
    assert document.metadata_sources[PROCESSED_MARK]["uri"].endswith("/C/v1/processed.json")
    assert dispatch(session, minio, section_file_sets=()).released == 0  # waits for the commit path


def test_overrides_and_strict_mode_set_severity(session, minio):
    _seed(session, minio, {"TP12_T01.dat": labjack_bytes(rows=200)[0]})
    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    pipeline_config.set_value(session, "flags.severity_overrides", {"C": {"UNIT_AMBIGUITY": "SOFT"}}, "test")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    outcome = process_document(session, minio, release.doc_id)
    assert (outcome.status, outcome.hard_flags, outcome.soft_flags) == ("WAITING_FOR_ROUTE", 0, 2)

    pipeline_config.set_value(session, "flags.strict_mode", True, "test")
    payload = ProcessedDocument(
        blob_sha256="a" * 64,
        route="C",
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{'a' * 64}/C/v1/",
        document=DocumentFields(title="t"),
        flags=[Flag(flag_type="CONFLICT", severity="SOFT", anchor=FlagAnchor(content_sha256="ab"))],
    )
    assert [f.severity for f in apply_severity_policy(session, payload).flags] == ["HARD"]


def test_the_folder_cfg_reaches_the_flag_evidence(session, minio):
    cfg = (
        b"[Main]\r\nScanRate=1000.000000\r\nNumChan=2\r\nDisableScaling=FALSE\r\n"
        b"Scaling=y=a*24.943-12.385#!#y=b*50.044#!#\r\n"
    )
    _seed(session, minio, {"TP12_T01.dat": labjack_bytes(rows=200)[0], "LJStreamM.cfg": cfg})
    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process  # the .cfg itself stays parked
    process_document(session, minio, release.doc_id)
    session.commit()
    evidence = {
        f.anchor["channel"]: f.evidence
        for f in session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == release.doc_id))
    }
    assert evidence["y1"]["scaling_equation"] == "y=b*50.044"
    assert evidence["y1"]["scaling_source"] == "LJStreamM.cfg"


def _fake_indexer(session, doc, doc_id, cloud_allowed):
    """S2's real index_document with the models role and Gemini replaced (no enrichment, fixed vectors)."""
    from backend.indexing.index_document import index_document
    from backend.llm_engine.enrichment.entities import AliasIndex

    assert cloud_allowed is False  # sync_roots.cloud_allowed defaults to false
    return index_document(
        doc,
        doc_id=doc_id,
        gemini=None,
        embed_documents=lambda texts, titles: [[0.01] * 768 for _ in texts],
        embed_images=None,
        asset_bytes=None,
        alias_index=AliasIndex(),
        reuse_vectors=lambda hashes: {},
        cloud_allowed=False,
        count_tokens=lambda texts: [len(t.split()) for t in texts],
    )


def _all_mapped_rule(session):
    session.add(
        Rule(
            rule_type="channel_map",
            origin="operator",
            scope_folder_id="F-RUN",
            body={
                "channels": {
                    "y0": {
                        "canonical_name": "pt_101_chamber_bar_g",
                        "physical_quantity": "pressure",
                        "unit": "bar",
                        "gauge_or_abs": "gauge",
                    },
                    "y1": {"canonical_name": "tc_1_k", "physical_quantity": "temperature", "unit": "degC"},
                },
                "ambient_condition": "SEA_LEVEL",
            },
            created_by="test",
        )
    )


def test_a_clean_run_is_indexed_and_committed_with_its_catalog(session, minio):
    from backend.postgres.models import DocumentNode, TelemetryChannel, TelemetryRun

    _seed(session, minio, {"TP12_T01.dat": labjack_bytes(rows=500)[0]})
    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    _all_mapped_rule(session)
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    outcome = process_document(session, minio, release.doc_id, indexer=_fake_indexer)
    session.commit()

    document = session.get(Document, release.doc_id)
    assert outcome.status in ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS") and document.status == outcome.status
    assert document.staged_payload_uri is None and document.indexed_at is not None
    assert PROCESSED_MARK not in document.metadata_sources
    (run,) = session.scalars(select(TelemetryRun)).all()
    assert (run.run_label, run.doc_id, run.ambient_condition, run.n_rows) == (
        "TP12_T01",
        document.doc_id,
        "SEA_LEVEL",
        500,
    )
    assert run.normalized_parquet_uri.endswith("/normalized.parquet")
    names = set(session.scalars(select(TelemetryChannel.canonical_name)))
    assert names == {"v0_v", "v1_v", "pt_101_chamber_bar_g", "pt_101_chamber_bar_abs", "tc_1_k"}
    nodes = session.scalars(select(DocumentNode).where(DocumentNode.doc_id == document.doc_id)).all()
    assert nodes and all(n.doc_kind == "telemetry_run" and n.trust_tier == 1 for n in nodes)
    assert any("pt_101_chamber_bar_g" in n.content for n in nodes)
    assert any(n.embedding is not None for n in nodes)
    assert "TP12_T01" in document.search_text


def test_a_second_run_with_the_same_label_is_renamed_with_a_conflict(session, minio):
    from backend.postgres.models import TelemetryRun

    _seed(
        session,
        minio,
        {"TP12_T01.dat": labjack_bytes(rows=300)[0], "TP12_T01_repeat.dat": labjack_bytes(rows=310)[0]},
    )
    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    _all_mapped_rule(session)
    session.commit()
    releases = dispatch(session, minio, section_file_sets=()).to_process
    for release in releases:
        process_document(session, minio, release.doc_id, indexer=_fake_indexer)
        session.commit()
    labels = sorted(session.scalars(select(TelemetryRun.run_label)))
    assert labels == ["TP12_T01", "TP12_T01_2"]
    renamed = session.scalar(select(TelemetryRun).where(TelemetryRun.run_label == "TP12_T01_2"))
    conflict = session.scalars(
        select(ReviewFlag).where(ReviewFlag.doc_id == renamed.doc_id, ReviewFlag.flag_type == "CONFLICT")
    ).all()
    assert any(f.evidence["subject"] == "run label TP12_T01" for f in conflict)
    assert session.get(Document, renamed.doc_id).status == "ACTIVE_WITH_SOFT_FLAGS"


def test_a_rule_resumes_the_halted_run_from_its_raw_parquet(session, minio):
    from backend.postgres.models import TelemetryRun
    from backend.routes.c_telemetry.pipeline import halted_documents_for_rule, resume_document

    _seed(session, minio, {"TP12_T01.dat": labjack_bytes(rows=400)[0]})
    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    assert process_document(session, minio, release.doc_id, indexer=_fake_indexer).status == "HALTED"
    session.commit()

    _all_mapped_rule(session)
    session.commit()
    rule_id = session.scalar(select(Rule.rule_id))
    assert halted_documents_for_rule(session, rule_id) == [release.doc_id]

    raw_key = f"{session.scalar(select(Blob.sha256))}"  # the .dat itself is no longer needed
    minio.remove_object("dcl-raw", f"{raw_key[:2]}/{raw_key[2:4]}/{raw_key}")
    outcome = resume_document(session, minio, release.doc_id, indexer=_fake_indexer)
    session.commit()

    assert outcome.status in ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS")
    flags = {
        f.anchor["channel"]: f.status for f in session.scalars(select(ReviewFlag)) if "channel" in f.anchor
    }
    assert flags["y0"] == flags["y1"] == "AUTO_RESOLVED"
    (run,) = session.scalars(select(TelemetryRun)).all()
    assert run.n_rows == 400 and run.normalized_parquet_uri is not None
    assert halted_documents_for_rule(session, rule_id) == []
