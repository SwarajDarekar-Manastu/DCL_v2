"""Tier 4 on landed blobs: type and mismatch, secret scan with quarantine, restricted blob, flag.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT. Fake secrets are assembled at runtime.
"""

import io
import zipfile
from pathlib import Path

from sqlalchemy import func, select

from backend.postgres.enums import DriveItemStatus as S
from backend.postgres.models import Blob, DriveItem, ReviewFlag
from backend.storage.minio import RAW, raw_key
from backend.sync.inspect import inspect_item, pending_inspection

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
SECRET = "AKIA" + "Q7" * 8


def _landed(session, minio, item_id, name, data, sha):
    minio.put_object(RAW, raw_key(sha), io.BytesIO(data), len(data))
    session.merge(Blob(sha256=sha, size_bytes=len(data), minio_uri=f"s3://dcl-raw/{raw_key(sha)}"))
    item = DriveItem(
        drive_id="D",
        item_id=item_id,
        root_name="APU Injector",
        name=name,
        status=S.LANDED,
        blob_sha256=sha,
        path_cached=f"APU Injector/x/{name}",
    )
    session.add(item)
    session.commit()
    return item.location_id


def test_html_saved_as_pdf_is_recorded_as_a_mismatch(session, minio):
    data = (FIXTURES / "dispatcher" / "pdf_is_html" / "Test_Report_12.pdf").read_bytes()
    loc = _landed(session, minio, "i1", "Test_Report_12.pdf", data, "a" * 64)
    result = inspect_item(session, minio, loc)
    session.commit()
    item = session.get(DriveItem, loc)
    assert (item.detected_mime, item.ext_mime_mismatch, item.status) == ("text/html", True, S.LANDED)
    assert result.secret_hits == 0
    assert inspect_item(session, minio, loc) is None
    assert loc not in pending_inspection(session)


def test_xlsx_is_named_from_its_zip_members_by_ranged_reads(session, minio):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    loc = _landed(session, minio, "i2", "FMEA.xlsx", buffer.getvalue(), "b" * 64)
    inspect_item(session, minio, loc)
    item = session.get(DriveItem, loc)
    assert (item.detected_mime, item.ext_mime_mismatch) == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        False,
    )


def test_a_secret_quarantines_every_location_restricts_the_blob_and_raises_one_flag_each(session, minio):
    sha = "c" * 64
    data = f"AIN0 = pt_101\naws_key_id = {SECRET}\n".encode()
    first = _landed(session, minio, "i3", "T01.cfg", data, sha)
    session.add(
        DriveItem(
            drive_id="D",
            item_id="i4",
            root_name="APU Injector",
            name="T01 copy.cfg",
            status=S.LANDED,
            blob_sha256=sha,
            path_cached="APU Injector/y/T01 copy.cfg",
        )
    )
    session.commit()

    result = inspect_item(session, minio, first)
    session.commit()

    assert result.secret_hits == 1
    holders = session.scalars(select(DriveItem).where(DriveItem.blob_sha256 == sha)).all()
    assert {(h.status, h.gate_reason) for h in holders} == {(S.QUARANTINED, "T4:secret")}
    blob = session.get(Blob, sha)
    assert (blob.restricted, blob.minio_uri) == (True, f"s3://dcl-raw/_restricted/{sha}")
    assert [o.object_name for o in minio.list_objects(RAW, prefix=raw_key(sha)[:5], recursive=True)] == []
    assert minio.get_object(RAW, f"_restricted/{sha}").read() == data
    flags = session.scalars(select(ReviewFlag)).all()
    assert {(f.flag_type, f.severity, f.doc_id) for f in flags} == {("SENSITIVE_CONTENT", "HARD", None)}
    assert len(flags) == 2
    assert all(SECRET not in str(f.evidence) for f in flags)
    assert flags[0].anchor == {"line": 2}
    minio.remove_object(RAW, f"_restricted/{sha}")


def test_re_raising_a_location_flag_keeps_one_row(session, minio):
    from backend.dispatcher.contract import Flag, FlagAnchor
    from backend.postgres.enums import FlagSeverity, FlagType
    from backend.review.flags import upsert_location_flag

    loc = _landed(session, minio, "i5", "a.txt", b"hello", "d" * 64)
    flag = Flag(flag_type=FlagType.HELD_LARGE_FILE, severity=FlagSeverity.SOFT, anchor=FlagAnchor())
    upsert_location_flag(session, loc, flag)
    upsert_location_flag(session, loc, flag)
    session.commit()
    assert session.scalar(select(func.count()).select_from(ReviewFlag)) == 1
