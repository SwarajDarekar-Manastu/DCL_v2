"""The new Route C kinds through dispatch, the gate and the commit (PostgreSQL + MinIO): a short DAQ
export (table), a long one (series), a TDMS run without units (HALTED, sibling units as evidence),
an analysis workbook (tables) and a LabJack configuration file.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT.
"""

import hashlib
import io

from sqlalchemy import select

from backend.dispatcher.routing import dispatch
from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import (
    Blob,
    Document,
    DocumentNode,
    DriveFolder,
    DriveItem,
    ReviewFlag,
    TelemetryRun,
)
from backend.routes.c_telemetry.pipeline import process_document
from backend.storage.minio import RAW, raw_key
from backend.tests.unit.routes.c_telemetry.test_adapters import analysis_workbook, daqami_csv, write_tdms
from backend.tests.unit.routes.c_telemetry.test_pipeline import _fake_indexer

FOLDERS = [
    ("ROOT", "APU", None, "APU"),
    ("F-TP7", "Test Plan 7", "ROOT", "APU/Test Plan 7"),
    ("F-TEMP", "Temperature", "F-TP7", "APU/Test Plan 7/Temperature"),
    ("F-TEMP-RUN", "Temperature", "F-TEMP", "APU/Test Plan 7/Temperature/Temperature"),
]


def _seed(session, minio, files: dict[tuple[str, str], bytes]) -> None:
    from backend.postgres.models import SyncRoot

    session.add(SyncRoot(root_name="APU", remote_drive_id="D", remote_item_id="ROOT-APU"))
    session.flush()
    for item_id, name, parent, path in FOLDERS:
        session.add(
            DriveFolder(
                drive_id="D",
                item_id=item_id,
                root_name="APU",
                name=name,
                parent_item_id=parent,
                path_cached=path,
            )
        )
    paths = {f[0]: f[3] for f in FOLDERS}
    for (folder, name), data in files.items():
        sha = hashlib.sha256(data).hexdigest()
        minio.put_object(RAW, raw_key(sha), io.BytesIO(data), len(data))
        session.add(Blob(sha256=sha, size_bytes=len(data), minio_uri=f"s3://dcl-raw/{raw_key(sha)}"))
        session.flush()
        session.add(
            DriveItem(
                drive_id="D",
                item_id=f"{folder}/{name}",
                root_name="APU",
                name=name,
                extension="." + name.rsplit(".", 1)[-1].casefold(),
                parent_item_id=folder,
                path_cached=f"{paths[folder]}/{name}",
                status=DriveItemStatus.LANDED,
                blob_sha256=sha,
                detected_mime="application/octet-stream",
                size_bytes=len(data),
            )
        )
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP7"], "test")
    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    session.commit()


def test_csv_tdms_workbook_and_config_documents(session, minio, tmp_path):
    write_tdms(tmp_path / "Temperature.tdms", with_units=False)
    _seed(
        session,
        minio,
        {
            ("F-TEMP", "Temperature.tdms"): (tmp_path / "Temperature.tdms").read_bytes(),
            ("F-TEMP-RUN", "Analog - 04-12-2025 11-45-10.6.csv"): daqami_csv(22),
            ("F-TEMP-RUN", "Analog - 04-12-2025 13-25-17.6.csv"): daqami_csv(120),
            ("F-TP7", "Test 01_Data_Analysis.xlsx"): analysis_workbook(),
            ("F-TP7", "LJStreamM.cfg"): b"[Main]\r\nScanRate=1000.000000\r\nScaling=y=a*24.943-12.385#!#\r\n",
        },
    )
    releases = dispatch(session, minio, section_file_sets=()).to_process
    assert len(releases) == 5
    outcomes = {}
    for release in releases:
        title = session.get(Document, release.doc_id).title
        outcomes[title] = process_document(session, minio, release.doc_id, indexer=_fake_indexer)
        session.commit()
    docs = {d.title: d for d in session.scalars(select(Document))}

    short = docs["Analog - 04-12-2025 11-45-10.6"]
    assert (short.status, short.doc_kind) == ("ACTIVE", "engineering_table")
    rows = session.scalars(
        select(DocumentNode).where(DocumentNode.doc_id == short.doc_id, DocumentNode.node_type == "table_row")
    ).all()
    assert len(rows) == 22 and any("T1 - Upper Thermal Stdoff (°C): 30.000" in r.content for r in rows)

    long = docs["Analog - 04-12-2025 13-25-17.6"]
    assert long.status in ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS") and long.doc_kind == "telemetry_run"
    run = session.scalar(select(TelemetryRun).where(TelemetryRun.doc_id == long.doc_id))
    assert (run.source_format, run.n_rows) == ("csv", 120) and run.normalized_parquet_uri

    halted = docs["Temperature"]
    assert halted.status == "HALTED"
    flags = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == halted.doc_id)).all()
    assert sorted(f.anchor["channel"] for f in flags) == ["AI0", "AI1", "AI2"]
    siblings = flags[0].evidence["sibling_units"]
    assert {s["unit"] for s in siblings} == {"°C"} and len(siblings) == 4  # two CSVs, two channels each

    book = docs["Test 01_Data_Analysis"]
    assert book.status == "HALTED"  # the Raw sheet's "Pc (bar)" states no gauge/absolute (C.1 step 3)
    book_flags = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == book.doc_id)).all()
    hard = [f for f in book_flags if f.severity == "HARD"]
    assert [(f.anchor["channel"], f.anchor["sheet"]) for f in hard] == [("Pc (bar)", "Raw")]
    assert hard[0].evidence["note"] == "pressure without gauge/absolute"
    soft = {
        (f.flag_type, f.anchor.get("column") or f.anchor.get("sheet"))
        for f in book_flags
        if f.severity == "SOFT"
    }
    assert soft == {
        ("UNIT_AMBIGUITY", "Duration"),
        ("UNIT_AMBIGUITY", "y"),
        ("CONFLICT", "Performance Parameters"),
    }
    assert session.scalar(select(TelemetryRun).where(TelemetryRun.doc_id == book.doc_id)) is None  # no rows

    config = docs["LJStreamM.cfg"]
    assert (config.status, config.doc_kind) == ("ACTIVE", "config")
    assert outcomes["LJStreamM"].rows is None  # keyed by the dispatch title (the file stem)


def test_committed_table_nodes_carry_locators_and_old_ones_are_found(session, minio):
    from sqlalchemy import update

    from backend.postgres.models import DocumentNode
    from backend.routes.c_telemetry.pipeline import unlocated_table_documents

    _seed(session, minio, {("F-TEMP-RUN", "Analog - 04-12-2025 11-45-10.6.csv"): daqami_csv(22)})
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    process_document(session, minio, release.doc_id, indexer=_fake_indexer)
    session.commit()
    rows = session.scalars(
        select(DocumentNode)
        .where(DocumentNode.doc_id == release.doc_id, DocumentNode.node_type == "table_row")
        .order_by(DocumentNode.ordinal)
    ).all()
    assert [(r.line_start, r.line_end) for r in rows[:2]] == [(8, 8), (9, 9)]
    assert unlocated_table_documents(session) == []
    session.execute(update(DocumentNode).where(DocumentNode.doc_id == release.doc_id).values(line_start=None))
    assert unlocated_table_documents(session) == [release.doc_id]


def test_formula_errors_are_a_failed_check_not_two_sources():
    from backend.routes.c_telemetry.pipeline import _formula_conflict

    evidence = _formula_conflict("Sheet1", ["A1", "B2"], None).evidence
    assert (evidence.relation, evidence.a.value, evidence.b.value) == (
        "check_failed",
        "A1, B2",
        "computed values",
    )
