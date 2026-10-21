"""Downloader: hashing stream, job keys, and landing against a disposable PostgreSQL + MinIO.

Server tests need DCL_TEST_DATABASE_URL (an empty database; migrated here) and
DCL_TEST_MINIO_ENDPOINT (+ DCL_TEST_MINIO_ACCESS_KEY / DCL_TEST_MINIO_SECRET_KEY).
"""

import base64
import hashlib
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
import quickxorhash
from alembic import command
from alembic.config import Config
from minio import Minio
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.postgres.enums import DriveItemStatus, JobStage
from backend.postgres.models import Blob, DriveItem, Job, SyncRoot
from backend.postgres.session import normalize_url
from backend.storage.minio import RAW, ensure_buckets, raw_key
from backend.sync.downloader import INCOMING_PREFIX, DownloadMismatch, HashingReader, land_item
from backend.sync.graph_client import GraphClient

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
CONTENT = b"LabJack LJStreamM header\n" + bytes(range(256)) * 4096


def qxh(data: bytes) -> str:
    h = quickxorhash.quickxorhash()
    h.update(data)
    return base64.b64encode(h.digest()).decode()


# ---------- without servers ----------


def test_hashing_reader_hashes_exactly_the_bytes_it_returns():
    reader = HashingReader([CONTENT[:1000], CONTENT[1000:70000], CONTENT[70000:]])
    out = b""
    while chunk := reader.read(65536):
        out += chunk
    assert out == CONTENT
    assert reader.size == len(CONTENT)
    assert reader.sha256.hexdigest() == hashlib.sha256(CONTENT).hexdigest()
    assert reader.quick_xor_b64 == qxh(CONTENT)


def test_job_key_names_content_never_a_location():
    sha = "ab" * 32
    assert Job.key_for(JobStage.DOWNLOAD, 1, 3, blob_sha256=sha) == f"download:{sha}:v1.3"
    doc = uuid.UUID("00000000-0000-4000-8000-000000000001")
    assert Job.key_for(JobStage.INDEX, 2, 5, doc_id=doc) == f"index:{doc}:v2.5"
    with pytest.raises(ValueError):
        Job.key_for(JobStage.PARSE, 1, 1)
    with pytest.raises(ValueError):
        Job.key_for(JobStage.PARSE, 1, 1, blob_sha256=sha, doc_id=doc)


# ---------- against disposable servers ----------


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url or not os.environ.get("DCL_TEST_MINIO_ENDPOINT"):
        pytest.skip("DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT are required")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        config = Config(str(ALEMBIC_INI))
        command.upgrade(config, "head")
        eng = create_engine(normalize_url(url))
        yield eng
        eng.dispose()
        command.downgrade(config, "base")


@pytest.fixture(scope="module")
def minio() -> Minio:
    parts = urlsplit(os.environ["DCL_TEST_MINIO_ENDPOINT"])
    client = Minio(
        parts.netloc,
        access_key=os.environ.get("DCL_TEST_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("DCL_TEST_MINIO_SECRET_KEY", "minioadmin"),
        secure=parts.scheme == "https",
    )
    ensure_buckets(client)
    return client


class FakeOneDrive:
    """Graph answers /content with a 302; the CDN host serves the bytes and must not see the token."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.content_requests: list[str] = []
        self.cdn_auth_headers: list[str | None] = []

    def graph(self, request: httpx.Request) -> httpx.Response:
        item_id = request.url.path.split("/")[-2]
        self.content_requests.append(item_id)
        return httpx.Response(302, headers={"Location": f"https://cdn.example.net/blob/{item_id}"})

    def cdn(self, request: httpx.Request) -> httpx.Response:
        self.cdn_auth_headers.append(request.headers.get("Authorization"))
        return httpx.Response(200, content=self.files[request.url.path.rsplit("/", 1)[-1]])


@pytest.fixture()
def onedrive():
    return FakeOneDrive({"i1": CONTENT, "i2": CONTENT, "i3": CONTENT[:-10]})


@pytest.fixture()
def session(engine, minio):
    with Session(engine) as s:
        s.add(SyncRoot(root_name="APU", remote_drive_id="d1", remote_item_id="r1"))
        s.commit()
        yield s
        s.rollback()
        for table in ("drive_items", "blobs", "sync_roots"):
            s.execute(text(f"DELETE FROM {table}"))
        s.commit()
    for obj in minio.list_objects(RAW, recursive=True):
        minio.remove_object(RAW, obj.object_name)


def _item(session, item_id, data, **overrides) -> uuid.UUID:
    values = dict(
        drive_id="d1",
        item_id=item_id,
        root_name="APU",
        name=f"{item_id}.dat",
        size_bytes=len(data),
        quick_xor_hash=qxh(data),
        status=DriveItemStatus.PENDING_DOWNLOAD,
    )
    values.update(overrides)
    item = DriveItem(**values)
    session.add(item)
    session.commit()
    return item.location_id


def _land(session, minio, onedrive, location_id):
    graph = GraphClient(lambda: "graph-token", transport=httpx.MockTransport(onedrive.graph))
    cdn = httpx.Client(transport=httpx.MockTransport(onedrive.cdn))
    result = land_item(session, graph, minio, location_id, cdn)
    session.commit()
    return result


def test_new_content_lands_at_its_content_address_with_metadata(session, minio, onedrive):
    loc = _item(session, "i1", CONTENT)
    result = _land(session, minio, onedrive, loc)

    sha = hashlib.sha256(CONTENT).hexdigest()
    assert (result.blob_sha256, result.downloaded, result.new_blob) == (sha, True, True)
    stored = minio.get_object(RAW, raw_key(sha))
    assert stored.read() == CONTENT
    meta = {k.lower(): v for k, v in stored.headers.items()}
    assert meta["x-amz-meta-original_name"] == "i1.dat"
    assert meta["x-amz-meta-first_location_id"] == str(loc)
    blob = session.get(Blob, sha)
    assert (blob.quick_xor_hash, blob.size_bytes, blob.minio_uri) == (
        qxh(CONTENT),
        len(CONTENT),
        f"s3://dcl-raw/{raw_key(sha)}",
    )
    item = session.get(DriveItem, loc)
    assert (item.status, item.blob_sha256) == (DriveItemStatus.LANDED, sha)
    assert [o.object_name for o in minio.list_objects(RAW, prefix=INCOMING_PREFIX, recursive=True)] == []
    assert onedrive.cdn_auth_headers == [None]


def test_known_quickxorhash_and_size_link_without_any_content_request(session, minio, onedrive):
    _land(session, minio, onedrive, _item(session, "i1", CONTENT))
    onedrive.content_requests.clear()

    copy = _item(session, "i2", CONTENT, name="copy in another folder.dat")
    result = _land(session, minio, onedrive, copy)
    assert (result.downloaded, result.new_blob) == (False, False)
    assert onedrive.content_requests == []
    assert session.scalar(select(func.count()).select_from(Blob)) == 1


def test_two_items_with_the_same_new_content_make_one_blob(session, minio, onedrive):
    first = _item(session, "i1", CONTENT, quick_xor_hash=None)
    second = _item(session, "i2", CONTENT, quick_xor_hash=None)
    a = _land(session, minio, onedrive, first)
    b = _land(session, minio, onedrive, second)
    assert a.blob_sha256 == b.blob_sha256
    assert (a.new_blob, b.new_blob) == (True, False)
    assert session.scalar(select(func.count()).select_from(Blob)) == 1


def test_truncated_download_leaves_no_blob_no_object_and_keeps_the_item_pending(session, minio, onedrive):
    loc = _item(session, "i3", CONTENT)  # Graph says full size/hash; the CDN serves 10 bytes less
    with pytest.raises(DownloadMismatch, match="size"):
        _land(session, minio, onedrive, loc)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(Blob)) == 0
    assert list(minio.list_objects(RAW, recursive=True)) == []
    assert session.get(DriveItem, loc).status == DriveItemStatus.PENDING_DOWNLOAD


def test_an_item_landed_by_another_worker_is_not_downloaded_again(session, minio, onedrive):
    loc = _item(session, "i1", CONTENT, quick_xor_hash=None)
    _land(session, minio, onedrive, loc)
    onedrive.content_requests.clear()
    result = _land(session, minio, onedrive, loc)  # a duplicate task for the same item
    assert (result.downloaded, result.new_blob) == (False, False)
    assert onedrive.content_requests == []


def test_no_temp_bytes_survive_on_a_versioned_bucket(session, minio, onedrive):
    from minio.commonconfig import ENABLED
    from minio.versioningconfig import VersioningConfig

    minio.set_bucket_versioning(RAW, VersioningConfig(ENABLED))
    _land(session, minio, onedrive, _item(session, "i1", CONTENT))
    leftovers = list(minio.list_objects(RAW, prefix=INCOMING_PREFIX, recursive=True, include_version=True))
    assert leftovers == []


def test_non_ascii_names_land_with_percent_encoded_metadata(session, minio, onedrive):
    from urllib.parse import unquote

    name = "Hydrogen Peroxide – Water – Ethanol Blend für CubeSat.pdf"
    loc = _item(session, "i1", CONTENT, name=name)
    result = _land(session, minio, onedrive, loc)
    stored = minio.stat_object(RAW, raw_key(result.blob_sha256))
    meta = {k.lower(): v for k, v in stored.metadata.items()}
    assert unquote(meta["x-amz-meta-original_name"]) == name


def test_modified_in_place_records_the_previous_blob_and_a_double_edit_keeps_the_oldest(
    session, minio, onedrive
):
    v1, v2, v3 = CONTENT, CONTENT + b"v2", CONTENT + b"v3"
    onedrive.files.update({"i1": v1})
    loc = _item(session, "i1", v1, quick_xor_hash=None)
    first = _land(session, minio, onedrive, loc)
    item = session.get(DriveItem, loc)
    assert item.previous_blob_sha256 is None

    for version in (v2, v3):
        onedrive.files["i1"] = version
        item.status, item.quick_xor_hash, item.size_bytes = (
            DriveItemStatus.PENDING_DOWNLOAD,
            None,
            len(version),
        )
        session.commit()
        _land(session, minio, onedrive, loc)
    item = session.get(DriveItem, loc)
    assert item.blob_sha256 == hashlib.sha256(v3).hexdigest()
    assert item.previous_blob_sha256 == first.blob_sha256
