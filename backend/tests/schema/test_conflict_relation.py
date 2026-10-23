"""Migration 0014: old CONFLICT evidence is tagged by its producer's labels; orphan notes leave the queue."""

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.dispatcher.contract import ConflictEvidence
from backend.postgres.models import Document

MIGRATION = (
    Path(__file__).resolve().parents[2] / "postgres" / "migrations" / "versions" / "0014_conflict_relation.py"
)


def side(label: str, value: str) -> dict:
    return {"label": label, "value": value, "provenance": "p", "doc_id": None, "date": None}


LEGACY = {
    "two_masters": {
        "kind": "conflict",
        "subject": "Report",
        "a": side("assembler", "two masters in folder X"),
        "b": side("expected", "one unambiguous document"),
    },
    "orphan": {
        "kind": "conflict",
        "subject": "Main_Files",
        "a": side("assembler", "not included by any master in folder Main_Files, assembled by filename"),
        "b": side("expected", "one unambiguous document"),
    },
    "orphan_a2": {
        "kind": "conflict",
        "subject": "no master found in folder Y, assembled by filename",
        "a": side("assembled as", "y.tex"),
        "b": side("reason", "no master found in folder Y, assembled by filename"),
    },
    "orphan_resolved": {
        "kind": "conflict",
        "subject": "Tables",
        "a": side("assembler", "not included by any master in folder Tables, assembled by filename"),
        "b": side("expected", "one unambiguous document"),
    },
    "threshold": {
        "kind": "conflict",
        "subject": "graph",
        "a": side("unlabeled edges", "13 of 13"),
        "b": side("threshold", "30%"),
    },
    "t0": {
        "kind": "conflict",
        "subject": "t0",
        "a": side("detected", "t0 at 5 ms"),
        "b": side("expected", "a sharp edge"),
    },
    "formula": {
        "kind": "conflict",
        "subject": "sheet",
        "a": side("cells", "A1"),
        "b": side("expected", "computed values"),
    },
    "plan": {
        "kind": "conflict",
        "subject": "test_plan_id",
        "a": side("folder", "TP26"),
        "b": side("page 1 text", "TP24"),
    },
}
STATUS = {"orphan_resolved": "RESOLVED"}
EXPECTED = {
    "two_masters": "note",
    "orphan_resolved": "note",
    "threshold": "check_failed",
    "t0": "check_failed",
    "formula": "check_failed",
    "plan": "sources_disagree",
}
DELETED = {"orphan", "orphan_a2"}


@pytest.fixture()
def migration():
    spec = importlib.util.spec_from_file_location("conflict_relation", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _store(session: Session) -> Document:
    document = Document(status="ACTIVE_WITH_SOFT_FLAGS", title="doc", route="A2")
    session.add(document)
    session.flush()
    for name, evidence in LEGACY.items():
        session.execute(
            text(
                "INSERT INTO review_flags (case_key, doc_id, fingerprint, flag_type, severity, "
                "status, evidence) "
                "VALUES (:k, :d, :k, 'CONFLICT', 'SOFT', :s, CAST(:e AS jsonb))"
            ),
            {"k": name, "d": document.doc_id, "s": STATUS.get(name, "OPEN"), "e": json.dumps(evidence)},
        )
    session.commit()
    return document


def _read(session: Session) -> dict[str, dict]:
    rows = session.execute(text("SELECT case_key, evidence FROM review_flags")).all()
    return {key: evidence for key, evidence in rows}


def _upgrade(session: Session, migration) -> None:
    for statement in migration.UPGRADE:
        session.execute(text(statement))
    session.commit()


def test_old_rows_are_tagged_and_still_validate(migrated, migration):
    with Session(migrated) as session:
        _store(session)
        _upgrade(session, migration)
        rows = _read(session)
        assert {name: row["relation"] for name, row in rows.items()} == EXPECTED
        assert "b" not in rows["two_masters"] and "b" in rows["plan"]
        for row in rows.values():
            ConflictEvidence.model_validate(row)


def test_open_orphan_notes_move_onto_the_document_and_stop_being_flags(migrated, migration):
    with Session(migrated) as session:
        document = _store(session)
        _upgrade(session, migration)
        assert DELETED.isdisjoint(_read(session))
        assert "orphan_resolved" in _read(session)  # history stays
        session.refresh(document)
        assert sorted(document.metadata_sources["assembler"]["notes"]) == [
            "no master found in folder Y, assembled by filename",
            "not included by any master in folder Main_Files, assembled by filename",
        ]
        assert document.status == "ACTIVE_WITH_SOFT_FLAGS"  # other open soft flags remain on this document


def test_a_document_soft_flagged_only_for_an_orphan_note_becomes_active(migrated, migration):
    with Session(migrated) as session:
        document = Document(status="ACTIVE_WITH_SOFT_FLAGS", title="lone", route="A2")
        session.add(document)
        session.flush()
        session.execute(
            text(
                "INSERT INTO review_flags (case_key, doc_id, fingerprint, flag_type, severity, evidence) "
                "VALUES ('lone', :d, 'lone', 'CONFLICT', 'SOFT', CAST(:e AS jsonb))"
            ),
            {"d": document.doc_id, "e": json.dumps(LEGACY["orphan"])},
        )
        session.commit()
        _upgrade(session, migration)
        session.refresh(document)
        assert (document.status, _read(session)) == ("ACTIVE", {})


def test_running_it_twice_changes_nothing(migrated, migration):
    with Session(migrated) as session:
        document = _store(session)
        _upgrade(session, migration)
        once, notes = _read(session), list(document.metadata_sources["assembler"]["notes"])
        _upgrade(session, migration)
        session.refresh(document)
        assert (_read(session), document.metadata_sources["assembler"]["notes"]) == (once, notes)


def test_downgrade_restores_the_old_two_sided_shape_of_the_rows_that_remain(migrated, migration):
    with Session(migrated) as session:
        _store(session)
        _upgrade(session, migration)
        for statement in migration.DOWNGRADE:
            session.execute(text(statement))
        rows = _read(session)
        assert all("relation" not in row for row in rows.values())
        assert rows["two_masters"]["b"]["value"] == "one unambiguous document"
