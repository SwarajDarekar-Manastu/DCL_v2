"""Derived blobs: contract checks, one registration path, dispatch of the child as its own document, and its
OneDrive location inherited from the parent. Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT."""

import hashlib
import io

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.dispatcher.contract import DerivedBlob
from backend.dispatcher.location import primary_location
from backend.dispatcher.routing import dispatch
from backend.postgres import pipeline_config
from backend.postgres.models import Blob, BlobDerivation, Document, DocumentSource, DriveFolder, DriveItem
from backend.storage.derived import register_derived_blobs
from backend.storage.minio import RAW, BucketStore, raw_key
from backend.tests.unit.routes.c_telemetry.test_adapters import analysis_workbook


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"member_path": "a.xlsx"}, "either data or blob_sha256"),
        ({"member_path": "a.xlsx", "data": b"x", "blob_sha256": "a" * 64}, "either data or blob_sha256"),
        ({"member_path": "../a.xlsx", "data": b"x"}, "stays inside the parent"),
        ({"member_path": "a.xlsx", "data": b"x", "kind": "redacted_copy"}, "not a derived-file kind"),
    ],
)
def test_contract_refuses_bad_derived_blobs(values, message):
    with pytest.raises(ValidationError, match=message):
        DerivedBlob(**values)


def _parent(session, minio) -> tuple[Document, str]:
    data = b"%PDF-1.7 parent"
    sha = hashlib.sha256(data).hexdigest()
    minio.put_object(RAW, raw_key(sha), io.BytesIO(data), len(data))
    session.add(Blob(sha256=sha, size_bytes=len(data), minio_uri=f"s3://dcl-raw/{raw_key(sha)}"))
    session.add(
        DriveFolder(
            drive_id="D",
            item_id="F-TP9",
            root_name="APU Injector",
            name="Test Plan 9",
            parent_item_id="ROOT",
            path_cached="APU Injector/Test Plan 9",
        )
    )
    session.flush()
    session.add(
        DriveItem(
            drive_id="D",
            item_id="doc",
            root_name="APU Injector",
            name="Report.docx",
            extension=".docx",
            parent_item_id="F-TP9",
            path_cached="APU Injector/Test Plan 9/Report.docx",
            status="LANDED",
            blob_sha256=sha,
            detected_mime="application/pdf",
            size_bytes=len(data),
        )
    )
    parent = Document(
        route="A1",
        status="ACTIVE",
        title="Report",
        folder_context={
            "root_name": "APU Injector",
            "breadcrumb": ["APU Injector", "Test Plan 9"],
            "path_cached": "APU Injector/Test Plan 9/Report.docx",
            "test_plan_id": "TP09",
        },
    )
    session.add(parent)
    session.flush()
    session.add(DocumentSource(doc_id=parent.doc_id, blob_sha256=sha, role="primary"))
    session.flush()
    return parent, sha


def test_registration_is_idempotent_and_the_child_becomes_a_document(session, minio):
    parent, parent_sha = _parent(session, minio)
    pipeline_config.set_value(session, "routes.C.enabled", True, "test")
    workbook = analysis_workbook()
    blob = DerivedBlob(member_path="word/embeddings/Microsoft_Excel_Worksheet.xlsx", data=workbook)
    raw = BucketStore(minio, RAW)
    (child,) = register_derived_blobs(session, raw, parent_sha, [blob])
    assert register_derived_blobs(session, raw, parent_sha, [blob]) == [child]
    assert child == hashlib.sha256(workbook).hexdigest()
    assert raw.get(raw_key(child)) == workbook
    link = session.scalars(select(BlobDerivation)).one()
    assert (link.parent_blob_sha256, link.kind) == (parent_sha, "embedded_object")
    session.commit()

    result = dispatch(session, minio, section_file_sets=())
    doc = session.scalars(select(Document).where(Document.doc_id != parent.doc_id)).one()
    assert (doc.route, doc.status, doc.title, doc.test_plan_id) == (
        "C",
        "PROCESSING",
        "Microsoft_Excel_Worksheet",
        "TP09",
    )
    assert doc.folder_context["breadcrumb"] == ["APU Injector", "Test Plan 9", "Report"]
    assert doc.folder_context["path_cached"].endswith(
        "Report.docx/word/embeddings/Microsoft_Excel_Worksheet.xlsx"
    )
    assert doc.metadata_sources["derived_from"] == {
        "doc_id": str(parent.doc_id),
        "member_path": blob.member_path,
        "kind": "embedded_object",
    }
    assert [r.doc_id for r in result.to_process] == [doc.doc_id]
    assert dispatch(session, minio, section_file_sets=()).created == 0

    where = primary_location(session, child)
    assert (where.root_name, where.parent_item_id, where.name, where.extension, where.path_cached) == (
        "APU Injector",
        "F-TP9",
        "Microsoft_Excel_Worksheet.xlsx",
        ".xlsx",
        "APU Injector/Test Plan 9/Report.docx/word/embeddings/Microsoft_Excel_Worksheet.xlsx",
    )


def test_a_stored_blob_is_linked_by_sha_and_an_unknown_one_is_refused(session, minio):
    _, parent_sha = _parent(session, minio)
    raw = BucketStore(minio, RAW)
    with pytest.raises(LookupError, match="is not stored"):
        register_derived_blobs(
            session, raw, parent_sha, [DerivedBlob(member_path="m.bin", blob_sha256="b" * 64)]
        )
