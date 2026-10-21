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

# Every ✓ column of file 05 §4.1 and the enum it must follow.
CHECKED_COLUMNS: dict[tuple[str, str], type[StrEnum]] = {
    ("sync_roots", "status"): enums.SyncRootStatus,
    ("sync_roots", "auth_status"): enums.AuthStatus,
    ("sync_roots", "default_source_origin"): enums.SourceOrigin,
    ("drive_folders", "source_origin_override"): enums.SourceOrigin,
    ("drive_items", "status"): enums.DriveItemStatus,
    ("blob_derivations", "kind"): enums.BlobDerivationKind,
    ("jobs", "stage"): enums.JobStage,
    ("jobs", "status"): enums.JobStatus,
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


def test_only_m1_tables_are_modelled():
    assert set(Base.metadata.tables) == M1_TABLES


def test_every_status_and_checked_column_has_an_enum_check():
    for table in Base.metadata.tables.values():
        checks = {c.name: c for c in table.constraints if isinstance(c, CheckConstraint)}
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


def _own_tables(engine) -> set[str]:
    with engine.connect() as conn:
        return set(conn.execute(text(OWN_TABLES_SQL)).scalars()) - {"alembic_version"}


def test_upgrade_creates_exactly_the_m1_tables(migrated):
    assert _own_tables(migrated) == M1_TABLES


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
    found = {r.conname: _check_values(r.definition) for r in rows}
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
                conn.execute(text(f"UPDATE {table} SET {column} = :v"), {"v": member.value})
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
