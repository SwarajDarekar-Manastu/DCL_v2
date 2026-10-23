"""Route A1 wiring: a PDF is released to dcl.process.route_a1 on cpu_parse; the run hands S2's entry point
the folder context and stores, then gates (HALTED on HARD) and parks a clean result without an indexer.
Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT."""

import hashlib
import io
from pathlib import Path

from sqlalchemy import select

from backend.dispatcher.contract import DocumentFields, Flag, LowConfidenceEvidence, ProcessedDocument
from backend.dispatcher.office_run import process_a1_document
from backend.dispatcher.routing import PROCESSED_MARK, dispatch
from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus as S
from backend.postgres.models import Blob, Document, DriveFolder, DriveItem, ReviewFlag
from backend.storage.minio import ASSETS, CIR, RAW, raw_key

PDF = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "a1_office"
    / "german_datasheet"
    / "MT-1_Datenblatt_DE.pdf"
)


def _seed(session, minio) -> str:
    data = PDF.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    minio.put_object(RAW, raw_key(sha), io.BytesIO(data), len(data))
    session.add(Blob(sha256=sha, size_bytes=len(data), minio_uri=f"s3://dcl-raw/{raw_key(sha)}"))
    session.add(
        DriveFolder(
            drive_id="D",
            item_id="F-TP7",
            root_name="APU Injector",
            name="Test Plan 7",
            parent_item_id="ROOT",
            path_cached="APU Injector/Test Plan 7",
        )
    )
    session.flush()
    session.add(
        DriveItem(
            drive_id="D",
            item_id="pdf",
            root_name="APU Injector",
            name="MT-1_Datenblatt_DE.pdf",
            extension=".pdf",
            parent_item_id="F-TP7",
            path_cached="APU Injector/Test Plan 7/MT-1_Datenblatt_DE.pdf",
            status=S.LANDED,
            blob_sha256=sha,
            detected_mime="application/pdf",
            size_bytes=len(data),
        )
    )
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP7"], "test")
    pipeline_config.set_value(session, "routes.A1.enabled", True, "test")
    pipeline_config.set_value(session, "critical_field_patterns", ["(?i)pressure"], "test")
    session.commit()
    return sha


class FakeBuild:
    def __init__(self, severity):
        self.severity, self.calls = severity, []

    def __call__(self, pdf_bytes, *, session, **kwargs):
        self.calls.append((pdf_bytes, kwargs))
        uri = kwargs["stores"].put_cir("pages/1.txt", b"Datenblatt")
        asset = kwargs["stores"].put_asset(f"pages/{kwargs['blob_sha256']}/0001.png", b"\x89PNG")
        assert (uri, asset) == (
            f"s3://{CIR}/{kwargs['blob_sha256']}/A1/v1/pages/1.txt",
            f"s3://{ASSETS}/pages/{kwargs['blob_sha256']}/0001.png",
        )
        flag = Flag(
            flag_type="LOW_CONFIDENCE_EXTRACTION", severity=self.severity, evidence=LowConfidenceEvidence()
        )
        return ProcessedDocument(
            blob_sha256=kwargs["blob_sha256"],
            route="A1",
            parser_version=1,
            cir_uri=f"s3://dcl-cir/{kwargs['blob_sha256']}/A1/v1/",
            document=DocumentFields(title="MT-1 Datenblatt", page_count=1),
            flags=[flag],
        )


def _released(session, minio):
    released = []
    dispatch(session, minio, section_file_sets=[], enqueue=released.append)
    (doc,) = session.scalars(select(Document)).all()
    return doc, released


def test_pdf_is_released_to_route_a1_on_cpu_parse(session, minio):
    _seed(session, minio)
    doc, released = _released(session, minio)
    assert (doc.route, doc.status) == ("A1", "PROCESSING")
    assert [(r.doc_id, r.task, r.queue) for r in released] == [
        (doc.doc_id, "dcl.process.route_a1", "cpu_parse")
    ]


def test_clean_run_without_indexer_is_parked_with_its_inputs(session, minio):
    sha = _seed(session, minio)
    doc, _ = _released(session, minio)
    build = FakeBuild("SOFT")
    outcome = process_a1_document(session, minio, doc.doc_id, build)
    session.commit()

    ((pdf_bytes, kwargs),) = build.calls
    assert pdf_bytes == PDF.read_bytes()
    assert (kwargs["blob_sha256"], kwargs["file_name"], kwargs["doc_id"]) == (
        sha,
        "MT-1_Datenblatt_DE.pdf",
        str(doc.doc_id),
    )
    assert kwargs["folder"].test_plan_id == "TP07"
    assert kwargs["critical_field_patterns"] == ("(?i)pressure",)
    assert kwargs["enrichment_max"] == 30  # routes.A1.formula_enrichment_max unset: the decided default
    assert (outcome.status, outcome.hard_flags, outcome.soft_flags) == ("WAITING_FOR_ROUTE", 0, 1)
    assert doc.metadata_sources[PROCESSED_MARK]["uri"] == f"s3://dcl-cir/{sha}/A1/v1/processed.json"
    assert session.scalars(select(ReviewFlag.severity)).all() == ["SOFT"]


def test_hard_flag_halts_with_a_staged_payload(session, minio):
    _seed(session, minio)
    doc, _ = _released(session, minio)
    outcome = process_a1_document(session, minio, doc.doc_id, FakeBuild("HARD"))
    session.commit()
    assert (outcome.status, outcome.hard_flags) == ("HALTED", 1)
    assert doc.staged_payload_uri is not None
