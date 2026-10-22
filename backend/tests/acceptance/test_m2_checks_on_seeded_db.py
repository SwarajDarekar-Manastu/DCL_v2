"""The M2 and TP7 acceptance checks themselves are tested: each passes on a good state and fails on
a bad one. Disposable database (DCL_TEST_DATABASE_URL); Parquet comes from a dict instead of MinIO."""

import io
import os
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import Session

from backend.postgres.models import (
    Blob,
    Document,
    DocumentSource,
    DriveItem,
    ReviewFlag,
    SyncRoot,
    TelemetryChannel,
    TelemetryRun,
)
from backend.postgres.session import normalize_url

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "postgres" / "alembic.ini"
PARQUET = "s3://dcl-cir/telemetry/run-1/normalized.parquet"
FOOTER = "Test Campaign 2 - Test Plan 6"


@pytest.fixture()
def db(monkeypatch):
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    url = normalize_url(url)
    monkeypatch.setenv("DCL_DATABASE_URL", url)
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            seed(session)
            session.commit()
            yield session
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def parquet(units: dict[str, str]) -> bytes:
    fields = [pa.field("t_rel_ms", pa.float64()), pa.field("t_from_ignition_ms", pa.float64())]
    fields += [pa.field(name, pa.float64(), metadata={"unit": unit}) for name, unit in units.items()]
    schema = pa.schema(fields)
    buffer = io.BytesIO()
    pq.write_table(pa.table({f.name: [0.0] for f in schema}, schema=schema), buffer)
    return buffer.getvalue()


GOOD_PARQUET = {PARQUET: parquet({"tc_1": "kelvin", "p_feed": "bar"})}


def add_document(session, n, route, status, ext, folder_plan=None):
    sha = f"{n:064x}"
    session.add(Blob(sha256=sha, size_bytes=10, minio_uri=f"s3://dcl-raw/{sha}"))
    session.add(
        DriveItem(
            drive_id="D",
            item_id=f"I-{n}",
            root_name="APU",
            name=f"file{n}{ext}",
            status="LANDED",
            blob_sha256=sha,
            path_cached=f"APU/x/file{n}{ext}",
            size_bytes=10,
        )
    )
    session.flush()
    doc = Document(
        doc_id=uuid.uuid4(),
        route=route,
        status=status,
        entity_ids=[],
        test_plan_id=folder_plan,
        folder_context={"test_plan_id": folder_plan} if folder_plan else {},
        staged_payload_uri="s3://dcl-staging/x" if status == "HALTED" else None,
    )
    session.add(doc)
    session.flush()
    session.add(DocumentSource(doc_id=doc.doc_id, blob_sha256=sha, role="primary"))
    return doc


def add_flag(session, doc, flag_type, severity, evidence, page="", anchor=None, suggestion=None):
    session.add(
        ReviewFlag(
            case_key=f"{doc.doc_id}:{page}",
            doc_id=doc.doc_id,
            page_or_sheet=page,
            fingerprint=uuid.uuid4().hex,
            flag_type=flag_type,
            severity=severity,
            route=doc.route,
            anchor=anchor or {},
            evidence=evidence,
            suggested_resolution=suggestion,
        )
    )


UNIT_EVIDENCE = {"kind": "unit_telemetry", "channel": "AIN0", "header_lines": ["Time, AIN0"]}
SUGGESTION = {"resolution": {"unit": "V"}, "confidence": 0.5}


def seed(session):
    """Route C as on the stack (22 HALTED .dat/.tdms, 7 ACTIVE, 11 soft, one CSV run) plus the TP7 sheet."""
    session.add(SyncRoot(root_name="APU", remote_drive_id="D", remote_item_id="F-ROOT"))
    session.flush()
    n = 0
    for i in range(22):
        n += 1
        doc = add_document(session, n, "C", "HALTED", ".tdms" if i < 2 else ".dat")
        add_flag(session, doc, "UNIT_AMBIGUITY", "HARD", UNIT_EVIDENCE, suggestion=SUGGESTION)
    for i in range(7):
        n += 1
        doc = add_document(session, n, "C", "ACTIVE", ".csv" if i == 0 else ".cfg")
        if i == 0:
            run = TelemetryRun(
                run_uuid=uuid.uuid4(),
                run_label="run-1",
                doc_id=doc.doc_id,
                blob_sha256=f"{n:064x}",
                source_format="csv",
                normalized_parquet_uri=PARQUET,
            )
            session.add(run)
            session.flush()
            for name, unit in (("tc_1", "kelvin"), ("p_feed", "bar")):
                session.add(
                    TelemetryChannel(run_uuid=run.run_uuid, canonical_name=name, raw_name=name, unit_si=unit)
                )
    for _ in range(11):
        n += 1
        doc = add_document(session, n, "C", "ACTIVE_WITH_SOFT_FLAGS", ".xlsx")
        add_flag(session, doc, "UNIT_AMBIGUITY", "SOFT", {"kind": "unit_telemetry", "channel": "c"})
    n += 1
    sheet = add_document(session, n, "A1", "ACTIVE_WITH_SOFT_FLAGS", ".pdf", folder_plan="TP07")
    add_flag(
        session,
        sheet,
        "CONFLICT",
        "SOFT",
        {
            "kind": "conflict",
            "subject": "test_plan_id",
            "a": {"label": "folder", "value": "TP07", "provenance": "folder[3]"},
            "b": {
                "label": "page 1 header or footer",
                "value": "TP06",
                "provenance": f"page 1 header or footer: {FOOTER!r} ('Test Plan 6')",
            },
        },
        page="1",
        anchor={"page": 1},
    )


@pytest.fixture(scope="module")
def m2():
    from backend.tests.acceptance.conftest import _load

    return _load("m2_state")


def tp7_flag(db):
    return db.query(ReviewFlag).filter(ReviewFlag.flag_type == "CONFLICT").one()


# ---------------------------------------------------------------- good state passes


def test_every_check_passes_on_the_good_state(m2, db):
    runs = m2.committed_runs(db)
    assert m2.tp7_violations(db) == []
    assert m2.status_count_violations(m2.route_c_status_counts(db)) == []
    assert m2.flag_status_violations(db) == []
    assert m2.unit_case_violations(db, require_suggestion=True) == []
    assert m2.run_count_violations(runs) == []
    assert m2.si_column_violations(db, runs, GOOD_PARQUET.__getitem__) == []
    assert m2.duplicate_flag_violations(db) == []


# ---------------------------------------------------------------- bad states fail


def test_tp7_fails_without_the_conflict(m2, db):
    db.delete(tp7_flag(db))
    db.flush()
    assert m2.tp7_violations(db)


def test_tp7_fails_when_the_footer_line_is_not_page_1_furniture(m2, db):
    flag = tp7_flag(db)
    flag.evidence = {**flag.evidence, "b": {**flag.evidence["b"], "label": "page 1 text", "provenance": "x"}}
    db.flush()
    assert len(m2.tp7_violations(db)) == 2


def test_tp7_fails_when_the_footer_replaced_the_folder_value(m2, db):
    db.execute(update(Document).where(Document.route == "A1").values(test_plan_id="TP06"))
    assert m2.tp7_violations(db)


def test_tp7_fails_when_side_a_is_not_from_the_path(m2, db):
    flag = tp7_flag(db)
    flag.evidence = {**flag.evidence, "a": {**flag.evidence["a"], "provenance": "page 2 text"}}
    db.flush()
    assert m2.tp7_violations(db)


def test_status_counts_fail_on_a_failed_document(m2, db):
    db.execute(
        update(Document)
        .where(
            Document.doc_id == db.query(Document.doc_id).filter_by(status="ACTIVE").limit(1).scalar_subquery()
        )
        .values(status="FAILED")
    )
    assert m2.status_count_violations(m2.route_c_status_counts(db))


def test_flag_status_fails_for_active_with_open_flag(m2, db):
    doc = db.query(Document).filter_by(route="C", status="ACTIVE").first()
    add_flag(db, doc, "CONFLICT", "SOFT", {"kind": "conflict"})
    db.flush()
    assert m2.flag_status_violations(db) == [f"doc {doc.doc_id} ACTIVE with open flags ['SOFT']"]


def test_unit_case_fails_for_halted_series_without_a_case(m2, db):
    doc = db.query(Document).filter_by(route="C", status="HALTED").first()
    db.execute(delete(ReviewFlag).where(ReviewFlag.doc_id == doc.doc_id))
    assert m2.unit_case_violations(db, require_suggestion=False)


def test_unit_case_fails_without_evidence_or_suggestion(m2, db):
    db.execute(update(ReviewFlag).where(ReviewFlag.severity == "HARD").values(suggested_resolution=None))
    assert m2.unit_case_violations(db, require_suggestion=False) == []
    assert len(m2.unit_case_violations(db, require_suggestion=True)) == 22
    db.execute(update(ReviewFlag).where(ReviewFlag.severity == "HARD").values(evidence={"channel": "AIN0"}))
    assert len(m2.unit_case_violations(db, require_suggestion=False)) == 22


def test_run_count_fails_with_a_second_run(m2, db):
    runs = m2.committed_runs(db)
    assert m2.run_count_violations(runs + runs)


def test_si_columns_fail_on_a_non_canonical_unit(m2, db):
    runs = m2.committed_runs(db)
    bad = {PARQUET: parquet({"tc_1": "degC", "p_feed": "bar"})}
    assert m2.si_column_violations(db, runs, bad.__getitem__) == [
        "run run-1: Parquet column tc_1 unit 'degC' is not canonical SI"
    ]
    missing = {PARQUET: parquet({"tc_1": "kelvin"})}
    assert m2.si_column_violations(db, runs, missing.__getitem__) == [
        "run run-1: Parquet lacks columns ['p_feed']"
    ]
    db.execute(
        update(TelemetryChannel).where(TelemetryChannel.canonical_name == "p_feed").values(unit_si="psi")
    )
    assert m2.si_column_violations(db, runs, GOOD_PARQUET.__getitem__)
