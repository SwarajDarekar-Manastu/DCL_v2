"""Read-only export of landed blobs: subtree selection, relative paths, nothing written back.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT (+ access/secret keys).
"""

import io

import pytest
from sqlalchemy import func, select

from backend.postgres.enums import DriveItemStatus as S
from backend.postgres.models import Blob, DriveFolder, DriveItem
from backend.storage.minio import RAW, raw_key
from backend.sync.export_blobs import export

SHA_DAT, SHA_CFG, SHA_OUT = "1" * 64, "2" * 64, "3" * 64


def _landed(session, minio, item_id, path, sha, data, status=S.LANDED):
    minio.put_object(RAW, raw_key(sha), io.BytesIO(data), len(data))
    session.merge(Blob(sha256=sha, size_bytes=len(data), minio_uri=f"s3://dcl-raw/{raw_key(sha)}"))
    session.add(
        DriveItem(
            drive_id="D",
            item_id=item_id,
            root_name="APU Injector",
            name=path.rsplit("/", 1)[-1],
            path_cached=path,
            status=status,
            blob_sha256=sha,
        )
    )


def test_export_copies_landed_files_of_the_subtree_under_relative_paths(session, minio, tmp_path):
    base = "APU Injector/Injector 14/Pressure_Data_Files"
    session.add(
        DriveFolder(
            drive_id="D",
            item_id="F-E2",
            root_name="APU Injector",
            name="Pressure_Data_Files",
            path_cached=base,
        )
    )
    _landed(session, minio, "a", f"{base}/TP14_T01.dat", SHA_DAT, b"dat bytes")
    _landed(session, minio, "b", f"{base}/cfg/TP14.cfg", SHA_CFG, b"cfg bytes")
    _landed(session, minio, "c", "APU Injector/Other/run.dat", SHA_OUT, b"outside")
    session.commit()
    blobs_before = session.scalar(select(func.count()).select_from(Blob))
    objects_before = sorted(o.object_name for o in minio.list_objects(RAW, recursive=True))

    written = export(session, minio, ["F-E2"], tmp_path)

    assert sorted(p.relative_to(tmp_path).as_posix() for p in written) == [
        "Pressure_Data_Files/TP14_T01.dat",
        "Pressure_Data_Files/cfg/TP14.cfg",
    ]
    assert (tmp_path / "Pressure_Data_Files" / "cfg" / "TP14.cfg").read_bytes() == b"cfg bytes"
    assert session.scalar(select(func.count()).select_from(Blob)) == blobs_before
    assert sorted(o.object_name for o in minio.list_objects(RAW, recursive=True)) == objects_before
    for sha in (SHA_DAT, SHA_CFG, SHA_OUT):
        minio.remove_object(RAW, raw_key(sha))


def test_unknown_folder_id_is_refused(session, minio, tmp_path):
    with pytest.raises(LookupError, match="crawl first"):
        export(session, minio, ["NOPE"], tmp_path)
