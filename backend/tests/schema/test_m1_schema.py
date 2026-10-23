"""M1 schema: tables, CHECKs generated from enums, FK indexes, autogenerate parity, downgrade."""

import re
from enum import StrEnum
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import CheckConstraint, text
from sqlalchemy.exc import IntegrityError

import backend.postgres.models  # noqa: F401
from backend.postgres import enums
from backend.postgres.base import Base, Tier

M1_TABLES = {
    "sync_roots",
    "drive_folders",
    "drive_items",
    "blobs",
    "blob_derivations",
    "jobs",
    "pipeline_config",
}
M2_M4_TABLES = {
    "documents",
    "document_sources",
    "document_relations",
    "document_nodes",
    "assets",
    "entities",
    "entity_aliases",
    "entity_mentions",
    "numeric_facts",
    "audit_events",
    "rules",
    "review_flags",
    "benchmark_cases",
    "benchmark_runs",
    "benchmark_results",
    "telemetry_runs",
    "telemetry_channels",
}
AUTH_TABLES = {"users"}  # local password RBAC (migration 0010)
LEDGER_TABLES = {"llm_calls", "answer_traces"}  # migration 0012
EXPECTED_TABLES = M1_TABLES | M2_M4_TABLES | AUTH_TABLES | LEDGER_TABLES

# Every ✓ column of file 05 and the enum it must follow.
CHECKED_COLUMNS: dict[tuple[str, str], type[StrEnum]] = {
    ("llm_calls", "status"): enums.LlmCallStatus,
    ("sync_roots", "status"): enums.SyncRootStatus,
    ("sync_roots", "auth_status"): enums.AuthStatus,
    ("sync_roots", "default_source_origin"): enums.SourceOrigin,
    ("drive_folders", "source_origin_override"): enums.SourceOrigin,
    ("drive_items", "status"): enums.DriveItemStatus,
    ("blob_derivations", "kind"): enums.BlobDerivationKind,
    ("jobs", "stage"): enums.JobStage,
    ("jobs", "status"): enums.JobStatus,
    ("documents", "route"): enums.Route,
    ("documents", "doc_kind"): enums.DocKind,
    ("documents", "status"): enums.DocumentStatus,
    ("documents", "source_origin"): enums.SourceOrigin,
    ("document_sources", "role"): enums.DocumentSourceRole,
    ("document_relations", "relation"): enums.DocumentRelationType,
    ("assets", "kind"): enums.AssetKind,
    ("document_nodes", "node_type"): enums.NodeType,
    ("document_nodes", "source"): enums.NodeSource,
    ("document_nodes", "doc_kind"): enums.DocKind,
    ("document_nodes", "source_origin"): enums.SourceOrigin,
    ("document_nodes", "doc_status"): enums.DocumentStatus,
    ("entities", "type"): enums.EntityType,
    ("entities", "created_by"): enums.EntityCreatedBy,
    ("entity_aliases", "type"): enums.EntityType,
    ("entity_aliases", "created_by"): enums.AliasCreatedBy,
    ("entity_mentions", "source"): enums.MentionSource,
    ("numeric_facts", "quantity"): enums.Quantity,
    ("numeric_facts", "gauge_or_abs"): enums.GaugeOrAbs,
    ("numeric_facts", "source"): enums.NumericFactSource,
    ("audit_events", "entity_type"): enums.AuditEntityType,
    ("rules", "rule_type"): enums.RuleType,
    ("rules", "origin"): enums.RuleOrigin,
    ("review_flags", "flag_type"): enums.FlagType,
    ("review_flags", "severity"): enums.FlagSeverity,
    ("review_flags", "status"): enums.FlagStatus,
    ("benchmark_cases", "status"): enums.BenchmarkCaseStatus,
    ("benchmark_cases", "category"): enums.BenchmarkCategory,
    ("benchmark_runs", "status"): enums.BenchmarkRunStatus,
    ("benchmark_results", "failure_class"): enums.FailureClass,
    ("telemetry_runs", "source_format"): enums.TelemetrySourceFormat,
    ("telemetry_runs", "run_status"): enums.RunStatus,
    ("telemetry_runs", "ambient_condition"): enums.AmbientCondition,
    ("telemetry_channels", "quantity"): enums.Quantity,
    ("telemetry_channels", "gauge_or_abs"): enums.GaugeOrAbs,
}
# Hand-written CHECKs that are not enum lists.
OTHER_CHECKS = {
    "ck_documents_trust_tier",
    "ck_documents_staged_when_halted",
    "ck_document_relations_symmetric_order",
    "ck_review_flags_doc_or_location",
    "ck_users_roles",  # array containment, tested in test_users.py
    "ck_users_email_lower",
}

FK_WITHOUT_INDEX_SQL = (Path(__file__).parent / "fk_without_index.sql").read_text()

# Tables of the current schema that no extension owns (the ParadeDB image ships PostGIS tables).
NOT_EXTENSION_OWNED = (
    "NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_class'::regclass "
    "AND d.objid = {rel} AND d.deptype = 'e')"
)
OWN_TABLES_SQL = (
    "SELECT c.relname FROM pg_class AS c WHERE c.relnamespace = current_schema()::regnamespace "
    "AND c.relkind IN ('r', 'p') AND " + NOT_EXTENSION_OWNED.format(rel="c.oid")
)
OWN_CHECKS_SQL = (
    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
    "WHERE contype = 'c' AND connamespace = current_schema()::regnamespace AND "
    + NOT_EXTENSION_OWNED.format(rel="conrelid")
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _check_values(definition: str) -> list[str]:
    """Allowed literals of a CHECK as PostgreSQL renders it (``= ANY (ARRAY['A'::text, ...])``)."""
    return re.findall(r"'([^']*)'", definition)


# ---------- model-level (no database) ----------


def test_every_model_has_a_tier_label():
    for table in Base.metadata.tables.values():
        assert table.info.get("tier") in set(Tier), table.name


def test_only_the_scheduled_tables_are_modelled():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_status_and_checked_column_has_an_enum_check():
    for table in Base.metadata.tables.values():
        checks = {
            c.name: c
            for c in table.constraints
            if isinstance(c, CheckConstraint) and c.name not in OTHER_CHECKS
        }
        expected = {col for (tbl, col) in CHECKED_COLUMNS if tbl == table.name}
        status_cols = {c.name for c in table.columns if c.name == "status"}
        assert status_cols <= expected, table.name
        for column in expected:
            name = f"ck_{table.name}_{column}"
            assert name in checks, name
            enum = CHECKED_COLUMNS[(table.name, column)]
            assert _check_values(str(checks[name].sqltext)) == [m.value for m in enum]


# ---------- database ----------


JOB_KEY = f"download:{SHA_A}:v1.1"
DOC_A = "00000000-0000-4000-8000-00000000000a"
DOC_B = "00000000-0000-4000-8000-00000000000b"
ASSET = "00000000-0000-4000-8000-0000000000a5"
NODE = "00000000-0000-4000-8000-0000000000a6"
ENTITY = "00000000-0000-4000-8000-0000000000e1"
RULE = "00000000-0000-4000-8000-0000000000c1"
RUN = "00000000-0000-4000-8000-0000000000b1"
TRUN = "00000000-0000-4000-8000-0000000000d1"


def _insert(conn, table: str, **values):
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    return conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values)


def _item(conn, item_id: str, drive_id: str = "d1", **extra):
    return _insert(
        conn, "drive_items", drive_id=drive_id, item_id=item_id, root_name="APU", name=item_id, **extra
    )


def _seed(conn) -> None:
    _insert(conn, "sync_roots", root_name="APU", remote_drive_id="d1", remote_item_id="r1")
    _insert(conn, "llm_calls", model="gemini-3.8-flash", purpose="triage_page", status="ok")
    _insert(conn, "blobs", sha256=SHA_A, size_bytes=1, minio_uri="s3://a")
    _insert(conn, "blobs", sha256=SHA_B, size_bytes=1, minio_uri="s3://b")
    _insert(conn, "drive_folders", drive_id="d1", item_id="f1", root_name="APU", name="TP07")
    _item(conn, "i1", blob_sha256=SHA_A)
    _insert(
        conn,
        "blob_derivations",
        parent_blob_sha256=SHA_A,
        member_path="inner/x.dat",
        child_blob_sha256=SHA_B,
        kind="archive_member",
    )
    _insert(conn, "jobs", job_key=JOB_KEY, stage="download")
    _insert(conn, "documents", doc_id=DOC_A, route="C", status="ACTIVE")
    _insert(conn, "documents", doc_id=DOC_B, route="C", status="ACTIVE")
    _insert(conn, "document_sources", doc_id=DOC_A, blob_sha256=SHA_A, role="primary")
    _insert(conn, "document_relations", doc_id_a=DOC_A, doc_id_b=DOC_B, relation="NEAR_DUPLICATE")
    _insert(
        conn, "assets", asset_id=ASSET, minio_uri="s3://dcl-assets/x.png", blob_sha256=SHA_A, kind="sparkline"
    )
    _insert(
        conn,
        "document_nodes",
        node_id=NODE,
        doc_id=DOC_A,
        node_type="run_summary",
        ordinal=0,
        content="x",
        source="structured",
    )
    _insert(
        conn,
        "entities",
        entity_id=ENTITY,
        type="material",
        canonical_name="C-103",
        canonical_key="c-103",
        created_by="seed",
    )
    _insert(
        conn,
        "entity_aliases",
        type="material",
        alias_key="c103",
        entity_id=ENTITY,
        alias="C103",
        created_by="seed",
    )
    _insert(
        conn, "entity_mentions", node_id=NODE, doc_id=DOC_A, entity_id=ENTITY, surface="C103", source="regex"
    )
    _insert(conn, "numeric_facts", node_id=NODE, doc_id=DOC_A, quantity="pressure", source="table")
    _insert(conn, "audit_events", actor="r@x", entity_type="rule", entity_id="1", action="create")
    _insert(
        conn, "rules", rule_id=RULE, rule_type="unit_mapping", origin="operator", body="{}", created_by="r@x"
    )
    _insert(
        conn,
        "review_flags",
        case_key=f"{DOC_A}:1",
        doc_id=DOC_A,
        fingerprint="f1",
        flag_type="CONFLICT",
        severity="SOFT",
    )
    _insert(
        conn,
        "benchmark_cases",
        case_id="TM-001",
        version=1,
        suite="telemetry",
        category="TELEMETRY_MATH",
        question="Peak chamber pressure of TP07_T01?",
        created_by="s5",
    )
    _insert(conn, "benchmark_runs", run_id=RUN, suite="telemetry")
    _insert(
        conn, "benchmark_results", run_id=RUN, case_id="TM-001", case_version=1, failure_class="UNIT_ERROR"
    )
    _insert(
        conn,
        "telemetry_runs",
        run_uuid=TRUN,
        run_label="TP07_T01",
        doc_id=DOC_A,
        blob_sha256=SHA_A,
        source_format="labjack_dat",
        channel_map_rule_id=RULE,
    )
    _insert(
        conn,
        "telemetry_channels",
        run_uuid=TRUN,
        canonical_name="pt_101_bar_g",
        raw_name="y0",
        quantity="pressure",
        gauge_or_abs="gauge",
        sparkline_asset_id=ASSET,
    )


def _paired(table: str, column: str) -> str:
    """Columns another CHECK ties to this one: a HALTED document carries a staged payload."""
    if (table, column) == ("documents", "status"):
        return ", staged_payload_uri = CASE WHEN :v = 'HALTED' THEN 's3://dcl-cir/x/staged.json' END"
    return ""


def _own_tables(engine) -> set[str]:
    with engine.connect() as conn:
        return set(conn.execute(text(OWN_TABLES_SQL)).scalars()) - {"alembic_version"}


def test_upgrade_creates_exactly_the_scheduled_tables(migrated):
    assert _own_tables(migrated) == EXPECTED_TABLES


def test_alembic_check_reports_no_drift(migrated, alembic_config):
    command.check(alembic_config)


def test_no_foreign_key_without_index(migrated):
    with migrated.connect() as conn:
        rows = conn.execute(text(FK_WITHOUT_INDEX_SQL)).all()
    assert rows == []


def test_fk_index_query_detects_a_missing_index(migrated):
    with migrated.begin() as conn:
        conn.execute(text("CREATE TABLE probe_unindexed (sha256 char(64) REFERENCES blobs (sha256))"))
        rows = conn.execute(text(FK_WITHOUT_INDEX_SQL)).all()
        conn.execute(text("DROP TABLE probe_unindexed"))
    assert [(r.table_name, list(r.fk_columns)) for r in rows] == [("probe_unindexed", ["sha256"])]


def test_database_checks_match_python_enums(migrated):
    with migrated.connect() as conn:
        rows = conn.execute(text(OWN_CHECKS_SQL)).all()
    found = {r.conname: _check_values(r.definition) for r in rows if r.conname not in OTHER_CHECKS}
    assert OTHER_CHECKS <= {r.conname for r in rows}
    expected = {f"ck_{tbl}_{col}": [m.value for m in enum] for (tbl, col), enum in CHECKED_COLUMNS.items()}
    assert found == expected


@pytest.mark.parametrize(("table", "column"), sorted(CHECKED_COLUMNS))
def test_check_accepts_every_enum_value_and_rejects_others(migrated, table, column):
    enum = CHECKED_COLUMNS[(table, column)]
    with migrated.connect() as conn:
        with conn.begin():
            _seed(conn)
        for member in enum:
            with conn.begin():
                conn.execute(
                    text(f"UPDATE {table} SET {column} = :v{_paired(table, column)}"), {"v": member.value}
                )
        first = next(iter(enum)).value
        for bad in ("NOT_A_VALUE", first.swapcase(), f" {first}"):
            with pytest.raises(IntegrityError, match=f"ck_{table}_{column}"):
                with conn.begin():
                    conn.execute(text(f"UPDATE {table} SET {column} = :v"), {"v": bad})


def test_drive_item_identity_is_drive_and_item_id(migrated):
    with migrated.connect() as conn:
        with conn.begin():
            _seed(conn)
        with pytest.raises(IntegrityError, match="uq_drive_items_drive_id_item_id"):
            with conn.begin():
                _item(conn, "i1")
        with conn.begin():
            _item(conn, "i1", drive_id="d2")


def test_parent_item_id_has_no_foreign_key(migrated):
    with migrated.begin() as conn:
        _seed(conn)
        _item(conn, "i9", parent_item_id="unknown-parent")
        _insert(
            conn,
            "drive_folders",
            drive_id="d1",
            item_id="f9",
            root_name="APU",
            name="early",
            parent_item_id="unknown-parent",
        )


def test_blob_insert_is_conflict_safe(migrated):
    with migrated.begin() as conn:
        _seed(conn)
        result = conn.execute(
            text(
                "INSERT INTO blobs (sha256, size_bytes, minio_uri) VALUES (:sha, 1, 's3://dup') "
                "ON CONFLICT DO NOTHING"
            ),
            {"sha": SHA_A},
        )
        assert result.rowcount == 0
        uri = conn.execute(
            text("SELECT minio_uri FROM blobs WHERE sha256 = :sha"), {"sha": SHA_A}
        ).scalar_one()
        assert uri == "s3://a"


def test_job_key_is_unique(migrated):
    with migrated.connect() as conn:
        with conn.begin():
            _seed(conn)
        with pytest.raises(IntegrityError, match="uq_jobs_job_key"):
            with conn.begin():
                _insert(conn, "jobs", job_key=JOB_KEY, stage="download")


def test_downgrade_base_removes_every_table(alembic_config, engine):
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    assert _own_tables(engine) == set()


def test_a_halted_document_needs_a_staged_payload_and_only_then(migrated):
    with migrated.connect() as conn:
        with conn.begin():
            _seed(conn)
        with pytest.raises(IntegrityError, match="ck_documents_staged_when_halted"):
            with conn.begin():
                conn.execute(text("UPDATE documents SET status = 'HALTED' WHERE doc_id = :d"), {"d": DOC_A})
        with conn.begin():
            conn.execute(
                text(
                    "UPDATE documents SET status = 'HALTED', "
                    "staged_payload_uri = 's3://dcl-cir/x/staged.json' WHERE doc_id = :d"
                ),
                {"d": DOC_A},
            )


def test_one_document_per_primary_blob(migrated):
    with migrated.connect() as conn:
        with conn.begin():
            _seed(conn)
        with pytest.raises(IntegrityError, match="uq_document_sources_primary_blob"):
            with conn.begin():
                _insert(conn, "document_sources", doc_id=DOC_B, blob_sha256=SHA_A, role="primary")


def test_deleting_a_document_removes_its_nodes_mentions_and_facts(migrated):
    with migrated.connect() as conn:
        with conn.begin():
            _seed(conn)
            conn.execute(text("DELETE FROM document_nodes WHERE doc_id = :d"), {"d": DOC_A})
            counts = [
                conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                for t in ("entity_mentions", "numeric_facts")
            ]
    assert counts == [0, 0]


def test_hnsw_indexes_exist_on_both_vector_columns(migrated):
    with migrated.connect() as conn:
        names = set(
            conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE indexdef LIKE '%USING hnsw%'")
            ).scalars()
        )
    assert names == {"hnsw_document_nodes_embedding", "hnsw_document_nodes_image_embedding"}


def test_bm25_indexes_exist_and_answer_a_query(migrated):
    with migrated.begin() as conn:
        _seed(conn)
        names = set(
            conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE indexdef LIKE '%USING bm25%'")
            ).scalars()
        )
        hits = conn.execute(text("SELECT count(*) FROM document_nodes WHERE content @@@ 'x'")).scalar_one()
    assert names == {"bm25_document_nodes", "bm25_documents"}
    assert hits == 1


def test_a_flag_needs_a_document_or_a_location_and_location_flags_are_unique_per_fingerprint(migrated):
    with migrated.connect() as conn:
        with conn.begin():
            _seed(conn)
        with pytest.raises(IntegrityError, match="ck_review_flags_doc_or_location"):
            with conn.begin():
                _insert(
                    conn, "review_flags", case_key="x", fingerprint="f", flag_type="CONFLICT", severity="SOFT"
                )
        with conn.begin():
            location = conn.execute(text("SELECT location_id FROM drive_items LIMIT 1")).scalar_one()
        row = dict(
            case_key=f"{location}:",
            location_id=location,
            fingerprint="f2",
            flag_type="HELD_LARGE_FILE",
            severity="SOFT",
        )
        with conn.begin():
            _insert(conn, "review_flags", **row)
        with pytest.raises(IntegrityError, match="uq_review_flags_location_fingerprint"):
            with conn.begin():
                _insert(conn, "review_flags", **row)


def test_run_labels_are_unique_and_a_document_delete_removes_its_runs_and_channels(migrated):
    with migrated.connect() as conn:
        with conn.begin():
            _seed(conn)
        with pytest.raises(IntegrityError, match="uq_telemetry_runs_run_label"):
            with conn.begin():
                _insert(
                    conn,
                    "telemetry_runs",
                    run_uuid="00000000-0000-4000-8000-0000000000d2",
                    run_label="TP07_T01",
                    doc_id=DOC_B,
                    blob_sha256=SHA_B,
                    source_format="csv",
                )
        with conn.begin():
            conn.execute(text("DELETE FROM documents WHERE doc_id = :d"), {"d": DOC_A})
        counts = conn.execute(
            text("SELECT (SELECT count(*) FROM telemetry_runs), (SELECT count(*) FROM telemetry_channels)")
        ).one()
        assert tuple(counts) == (0, 0)
