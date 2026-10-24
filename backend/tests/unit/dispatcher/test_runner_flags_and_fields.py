"""The shared runner and commit (defects found by the A1 route run, 2026-10-24): a re-run closes the
route's own flags it does not raise again, the commit writes every document field a route decides, clears
the warnings of an earlier run and records whether the content went to Gemini.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT.
"""

from datetime import UTC, datetime

from sqlalchemy import select

from backend.dispatcher.contract import (
    ApproveInternal,
    DocumentFields,
    Flag,
    FlagAnchor,
    ProcessedDocument,
    ProcessedNode,
    SensitiveEvidence,
)
from backend.dispatcher.routing import dispatch
from backend.dispatcher.runner import resume_staged, run_document
from backend.postgres import pipeline_config
from backend.postgres.enums import FlagSeverity, FlagType, NodeSource, NodeType, Route, SourceOrigin
from backend.postgres.models import Document, DocumentNode, LlmCall, ReviewFlag
from backend.review.flags import upsert_document_flag
from backend.tests.unit.dispatcher.test_dispatch import _file
from backend.tests.unit.dispatcher.test_route_runners import _seed_folders_only
from backend.tests.unit.routes.c_telemetry.test_pipeline import _fake_indexer


def _flag(sha: str) -> Flag:
    return Flag(
        flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(content_sha256=sha * 64),
    )


def _document(session, minio) -> Document:
    _seed_folders_only(session)
    _file(session, minio, "s1", "F-TP12", "tool.py", b"def run():\n    return 1\n", "text/x-python")
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    pipeline_config.set_value(session, "routes.B.enabled", True, "test")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    return session.get(Document, release.doc_id)


def _run(session, minio, document, fields: DocumentFields, flags: list[Flag], warnings: list[str], nodes=()):
    document.status = "PROCESSING"
    session.commit()

    def build(ctx):
        return ProcessedDocument(
            blob_sha256=ctx.blob.sha256,
            route=Route.B,
            parser_version=1,
            cir_uri=f"s3://dcl-cir/{ctx.blob.sha256}/B/v1/",
            document=fields,
            flags=flags,
            nodes=list(nodes),
        )

    def indexer(session, doc, doc_id, cloud_allowed):
        plan = _fake_indexer(session, doc, doc_id, cloud_allowed)
        plan.warnings = list(warnings)
        return plan

    outcome = run_document(session, minio, document.doc_id, Route.B, 1, build, indexer)
    session.commit()
    return outcome


def _flags(session, document) -> dict[str, str]:
    rows = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == document.doc_id)).all()
    return {(r.anchor or {}).get("content_sha256", "assembler")[:1]: r.status for r in rows}


def test_a_rerun_closes_the_routes_own_flag_it_no_longer_raises_and_keeps_the_assembler_note(session, minio):
    document = _document(session, minio)
    note = Flag(
        flag_type=FlagType.CONFLICT,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(content_sha256="n" * 64),
        evidence={
            "kind": "conflict",
            "subject": "tool",
            "relation": "note",
            "a": {"label": "assembler", "value": "two masters", "provenance": "file 03 §1.3"},
            "b": None,
        },
    )
    upsert_document_flag(session, document.doc_id, note, "B")
    _run(session, minio, document, DocumentFields(title="tool"), [_flag("a")], ["first run"])
    _run(session, minio, document, DocumentFields(title="tool"), [_flag("b")], [])

    assert _flags(session, document) == {"a": "AUTO_RESOLVED", "b": "OPEN", "n": "OPEN"}


def test_the_commit_writes_every_field_a_route_decides_and_clears_old_warnings(session, minio):
    document = _document(session, minio)
    fields = DocumentFields(
        title="Monopropellant thrusters",
        source_origin=SourceOrigin.EXTERNAL_KEPT,
        publisher="Moog",
        external_ids={"report_number": "MT-1"},
        standard_id="ECSS-E-ST-35C",
        standard_revision="Rev.1",
        classification_marking="public",
        languages_detected=["en", "de"],
        number_locale="comma",
    )
    _run(session, minio, document, fields, [], ["cloud processing not allowed for this root: no enrichment"])
    session.refresh(document)
    assert document.metadata_sources["index_warnings"] and document.cloud_processed is False
    assert (document.source_origin, document.publisher, document.external_ids) == (
        "external_kept",
        "Moog",
        {"report_number": "MT-1"},
    )
    assert (document.standard_id, document.standard_revision, document.classification_marking) == (
        "ECSS-E-ST-35C",
        "Rev.1",
        "public",
    )
    assert (document.languages_detected, document.number_locale) == (["en", "de"], "comma")
    assert document.parser_version == 1
    assert document.cir_uri.startswith("s3://dcl-cir/") and document.cir_uri.endswith("/B/v1/")

    session.add(
        LlmCall(
            at=datetime.now(UTC),
            model="gemini-3.8-flash",
            purpose="enrichment.parent",
            doc_id=document.doc_id,
            status="ok",
            input_tokens=10,
            output_tokens=5,
        )
    )
    _run(session, minio, document, fields, [], [])
    session.refresh(document)
    assert "index_warnings" not in document.metadata_sources and document.cloud_processed is True


def test_the_nodes_follow_every_status_change_but_stay_searchable_while_a_rerun_processes(session, minio):
    document = _document(session, minio)
    node = ProcessedNode(
        ref="m",
        node_type=NodeType.PARENT,
        ordinal=0,
        breadcrumb="tool.py",
        content="def run(): return 1",
        source=NodeSource.PRINTED,
        language="en",
    )
    _run(session, minio, document, DocumentFields(title="tool"), [], [], nodes=[node])

    def node_statuses():
        session.expire_all()
        return set(
            session.scalars(select(DocumentNode.doc_status).where(DocumentNode.doc_id == document.doc_id))
        )

    assert node_statuses() == {"ACTIVE"}
    before = document.updated_at
    document.status = "PROCESSING"
    session.commit()
    assert node_statuses() == {"ACTIVE"}
    document.status = "QUARANTINED"
    session.commit()
    assert node_statuses() == {"QUARANTINED"}
    assert document.updated_at > before


def _sensitive() -> Flag:
    return Flag(
        flag_type=FlagType.SENSITIVE_CONTENT,
        severity=FlagSeverity.HARD,
        anchor=FlagAnchor(content_sha256="s" * 64),
        evidence=SensitiveEvidence(pattern="ITAR", redacted_preview="ITAR controlled"),
    )


def test_a_decided_hard_flag_resumes_the_document_from_its_staged_payload(session, minio):
    from backend.review import cases
    from backend.review.api_models import FlagResolution, ResolveRequest

    document = _document(session, minio)
    halted = _run(session, minio, document, DocumentFields(title="tool"), [_sensitive()], [])
    assert (halted.status, halted.hard_flags) == ("HALTED", 1)
    (row,) = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == document.doc_id)).all()

    outcome = cases.resolve_case(
        session,
        row.case_key,
        ResolveRequest(resolutions=[FlagResolution(flag_id=row.flag_id, resolution=ApproveInternal())]),
        "admin@test",
        is_admin=True,
    )
    session.commit()
    assert outcome.resume_doc_id == document.doc_id

    resumed = resume_staged(session, minio, document.doc_id, _fake_indexer)
    session.commit()
    session.refresh(document)
    assert (resumed.status, document.status, document.staged_payload_uri) == ("ACTIVE", "ACTIVE", None)
    assert session.get(ReviewFlag, row.flag_id).status == "RESOLVED"

    again = _run(session, minio, document, DocumentFields(title="tool"), [_sensitive()], [])
    assert again.status == "ACTIVE"  # the route raises it again; the person's decision stands


def test_a_flag_the_pipeline_closed_is_open_again_when_the_route_raises_it_again(session, minio):
    document = _document(session, minio)
    _run(session, minio, document, DocumentFields(title="tool"), [_sensitive()], [])
    (row,) = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == document.doc_id)).all()
    row.status, row.resolved_by = "AUTO_RESOLVED", "pipeline"
    document.status, document.staged_payload_uri = "ACTIVE", None
    session.commit()
    again = _run(session, minio, document, DocumentFields(title="tool"), [_sensitive()], [])
    session.refresh(row)
    assert (again.status, row.status, row.resolved_by) == ("HALTED", "OPEN", None)
