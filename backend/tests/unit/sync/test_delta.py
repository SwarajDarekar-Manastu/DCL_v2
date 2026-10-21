"""Metadata crawl against scripted Graph pages and a disposable, migrated PostgreSQL.

Needs DCL_TEST_DATABASE_URL. The gate is seeded from the real config/gate.yaml.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus as S
from backend.postgres.models import Blob, DriveFolder, DriveItem, SyncRoot
from backend.postgres.session import normalize_url
from backend.sync.delta import GraphCallFailed, ResyncRequired, run_root
from backend.sync.graph_client import GraphClient

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "postgres" / "alembic.ini"
NEXT = "https://graph.microsoft.com/v1.0/drives/D/items/ROOT/delta?token=page2"
DELTA = "https://graph.microsoft.com/v1.0/drives/D/items/ROOT/delta?token=latest"
DELTA2 = "https://graph.microsoft.com/v1.0/drives/D/items/ROOT/delta?token=after-change"


def folder(id_, name, parent):
    return {"id": id_, "name": name, "folder": {"childCount": 1}, "parentReference": {"id": parent}}


def file(id_, name, parent, size=100, qxh="QXH-1", **extra):
    return {
        "id": id_,
        "name": name,
        "size": size,
        "file": {"hashes": {"quickXorHash": qxh}},
        "parentReference": {"id": parent},
        "eTag": "e1",
        "webUrl": f"https://x/{id_}",
        **extra,
    }


PAGE1 = [
    folder("ROOT", "APU Injector", "OUTSIDE"),
    file("i-dat", "TP30_T01.dat", "F-PRESSURE"),  # child before its parent folder
    file("i-dat", "TP30_T01.dat", "F-PRESSURE", qxh="QXH-DAT"),  # duplicate: the last occurrence wins
    folder("F-TP30", "Test Plan 30", "ROOT"),
    folder("F-VENV", ".venv", "F-TP30"),
    file("i-venv", "numpy.py", "F-VENV"),
    folder("F-DEL", "_to_delete", "ROOT"),
    file("i-del", "old.dat", "F-DEL"),
    file("i-lock", "~$report.docx", "F-TP30"),
    file("i-empty", "empty.csv", "F-TP30", size=0),
    file("i-big", "firing.mp4", "F-TP30", size=5 * 1024**3),
    file("i-one", "Notebook", "F-TP30", package={"type": "oneNote"}),
]
PAGE2 = [
    folder("F-PRESSURE", "Pressure_Data_Files", "F-TP30"),
    file("i-fail", "TP30_T02.dat_fail", "F-PRESSURE"),
    file("i-pdf", "report.pdf", "F-TP30"),
]


class FakeGraph:
    def __init__(self, pages: dict[str, list]) -> None:
        self.pages = pages  # url → list of (status, body, headers); the last one repeats
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = str(request.url) if "token=" in str(request.url) else request.url.path
        self.calls.append(key)
        script = self.pages[key]
        status, body, headers = script.pop(0) if len(script) > 1 else script[0]
        return httpx.Response(status, json=body, headers=headers or {})


def crawl_pages():
    return {
        "/v1.0/drives/D/items/ROOT/delta": [(200, {"value": PAGE1, "@odata.nextLink": NEXT}, None)],
        NEXT: [(200, {"value": PAGE2, "@odata.deltaLink": DELTA}, None)],
    }


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("DCL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DCL_TEST_DATABASE_URL is not set")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DCL_DATABASE_URL", url)
        config = Config(str(ALEMBIC_INI))
        command.upgrade(config, "head")
        eng = create_engine(normalize_url(url))
        yield eng
        eng.dispose()
        command.downgrade(config, "base")


@pytest.fixture()
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        pipeline_config.seed_gate(s, pipeline_config.load_gate_yaml())
        s.add(SyncRoot(root_name="APU Injector", remote_drive_id="D", remote_item_id="ROOT"))
        s.commit()
        yield s
        s.rollback()
        for table in ("drive_items", "drive_folders", "blobs", "sync_roots", "pipeline_config"):
            s.execute(text(f"DELETE FROM {table}"))
        s.commit()


def run(session, fake, sleeps=None):
    root = session.get(SyncRoot, "APU Injector")
    graph = GraphClient(lambda: "t", transport=httpx.MockTransport(fake))
    return run_root(
        session,
        graph,
        root,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
        now=lambda: datetime(2026, 10, 22, tzinfo=UTC),
    )


def state(session):
    return {i.item_id: (i.status, i.gate_reason, i.path_cached) for i in session.scalars(select(DriveItem))}


def test_initial_crawl_records_every_item_with_a_decision_and_a_computed_path(session):
    stats = run(session, FakeGraph(crawl_pages()))
    got = state(session)
    assert got == {
        "i-dat": (S.PENDING_DOWNLOAD, None, "APU Injector/Test Plan 30/Pressure_Data_Files/TP30_T01.dat"),
        "i-fail": (
            S.PENDING_DOWNLOAD,
            None,
            "APU Injector/Test Plan 30/Pressure_Data_Files/TP30_T02.dat_fail",
        ),
        "i-pdf": (S.PENDING_DOWNLOAD, None, "APU Injector/Test Plan 30/report.pdf"),
        "i-venv": (S.SKIPPED_JUNK, "T1:.venv", "APU Injector/Test Plan 30/.venv/numpy.py"),
        "i-del": (S.QUARANTINED, "T1:quarantine:_to_delete", "APU Injector/_to_delete/old.dat"),
        "i-lock": (S.SKIPPED_JUNK, "T2:~$", "APU Injector/Test Plan 30/~$report.docx"),
        "i-empty": (S.SKIPPED_EMPTY, "T3:empty", "APU Injector/Test Plan 30/empty.csv"),
        "i-big": (S.HELD_LARGE_FILE, "T3:size", "APU Injector/Test Plan 30/firing.mp4"),
        "i-one": (S.SKIPPED_UNSUPPORTED_PACKAGE, "T3:package", "APU Injector/Test Plan 30/Notebook"),
    }
    assert (
        session.scalars(select(DriveItem.quick_xor_hash).where(DriveItem.item_id == "i-dat")).one()
        == "QXH-DAT"
    )
    root = session.get(SyncRoot, "APU Injector")
    assert (root.delta_link, root.next_link_checkpoint, root.status) == (DELTA, None, "ACTIVE")
    assert root.last_full_crawl_at is not None
    venv = session.scalars(select(DriveFolder).where(DriveFolder.item_id == "F-VENV")).one()
    assert (venv.is_junk, venv.path_cached) == (True, "APU Injector/Test Plan 30/.venv")
    assert (stats.pages, stats.orphans) == (2, 0)


def test_a_crash_after_page_one_resumes_at_page_two_with_the_same_end_state(session, engine):
    pages = crawl_pages()
    pages[NEXT] = [(500, {"error": {"code": "serviceError"}}, None), *pages[NEXT]]
    fake = FakeGraph(pages)
    with pytest.raises(GraphCallFailed):
        run(session, fake)
    session.rollback()
    assert session.get(SyncRoot, "APU Injector").next_link_checkpoint == NEXT
    run(session, fake)
    assert fake.calls.count("/v1.0/drives/D/items/ROOT/delta") == 1
    assert state(session)["i-dat"][0] == S.PENDING_DOWNLOAD
    assert session.get(SyncRoot, "APU Injector").delta_link == DELTA


def _land(session, item_id, sha="a" * 64, qxh="QXH-DAT"):
    session.merge(Blob(sha256=sha, quick_xor_hash=qxh, size_bytes=100, minio_uri=f"s3://dcl-raw/{sha}"))
    item = session.scalars(select(DriveItem).where(DriveItem.item_id == item_id)).one()
    item.blob_sha256, item.status = sha, S.LANDED
    session.commit()


def _delta(session, items, delta=DELTA2):
    return run(session, FakeGraph({DELTA: [(200, {"value": items, "@odata.deltaLink": delta}, None)]}))


def test_folder_rename_recomputes_paths_without_any_download_and_keeps_landed(session):
    run(session, FakeGraph(crawl_pages()))
    _land(session, "i-dat")
    _delta(session, [folder("F-TP30", "TP30 renamed", "ROOT")])
    item = state(session)["i-dat"]
    assert item == (S.LANDED, None, "APU Injector/TP30 renamed/Pressure_Data_Files/TP30_T01.dat")


def test_moving_a_folder_into_and_out_of_quarantine(session):
    run(session, FakeGraph(crawl_pages()))
    _land(session, "i-dat")
    _delta(session, [folder("F-TP30", "TP30 (old)", "ROOT")])
    assert state(session)["i-dat"][:2] == (S.QUARANTINED, "T1:quarantine:TP30 (old)")
    run(
        session,
        FakeGraph(
            {
                DELTA2: [
                    (
                        200,
                        {"value": [folder("F-TP30", "Test Plan 30", "ROOT")], "@odata.deltaLink": DELTA},
                        None,
                    )
                ]
            }
        ),
    )
    assert state(session)["i-dat"][0] == S.LANDED


def test_changed_hash_on_a_landed_item_needs_a_download_but_a_metadata_change_does_not(session):
    run(session, FakeGraph(crawl_pages()))
    _land(session, "i-dat")
    _delta(session, [file("i-dat", "TP30_T01.dat", "F-PRESSURE", qxh="QXH-DAT", eTag="e2")])
    assert state(session)["i-dat"][0] == S.LANDED
    run(
        session,
        FakeGraph(
            {
                DELTA2: [
                    (
                        200,
                        {
                            "value": [file("i-dat", "TP30_T01.dat", "F-PRESSURE", qxh="QXH-NEW")],
                            "@odata.deltaLink": DELTA,
                        },
                        None,
                    )
                ]
            }
        ),
    )
    assert state(session)["i-dat"][0] == S.PENDING_DOWNLOAD


def test_deleted_facet_marks_the_item_deleted_and_nothing_else(session):
    run(session, FakeGraph(crawl_pages()))
    before = state(session)
    _delta(session, [{"id": "i-pdf", "deleted": {"state": "deleted"}, "parentReference": {"id": "F-TP30"}}])
    after = state(session)
    assert after.pop("i-pdf")[0] == S.DELETED
    before.pop("i-pdf")
    assert after == before


def test_throttling_waits_for_retry_after_and_retries_the_same_page(session):
    pages = crawl_pages()
    pages[NEXT] = [(429, {}, {"Retry-After": "7"}), *pages[NEXT]]
    sleeps: list[float] = []
    run(session, FakeGraph(pages), sleeps)
    assert sleeps == [7.0]
    assert session.get(SyncRoot, "APU Injector").delta_link == DELTA


def test_download_scope_holds_accepted_items_outside_it(session):
    pipeline_config.set_value(session, pipeline_config.DOWNLOAD_SCOPE, ["F-PRESSURE"], "s5")
    session.commit()
    run(session, FakeGraph(crawl_pages()))
    got = state(session)
    assert got["i-dat"][0] == S.PENDING_DOWNLOAD
    assert got["i-pdf"][:2] == (S.HELD_BY_SCOPE, "SCOPE:not_in_download_scope")
    assert got["i-venv"][0] == S.SKIPPED_JUNK


def test_expired_delta_token_raises_resync_required_with_the_location(session):
    run(session, FakeGraph(crawl_pages()))
    with pytest.raises(ResyncRequired) as info:
        run(session, FakeGraph({DELTA: [(410, {"error": {"code": "resyncRequired"}}, {"Location": DELTA2})]}))
    assert info.value.location == DELTA2


def test_folder_listing_reports_accepted_files_per_folder_with_slot_flags(session, tmp_path):
    from backend.sync.folder_listing import build, write

    run(session, FakeGraph(crawl_pages()))
    folders, library = build(session)
    by_path = {row.folder_path: row.as_csv() for row in folders}
    assert set(by_path) == {"Test Plan 30", "Test Plan 30/Pressure_Data_Files"}
    pressure = by_path["Test Plan 30/Pressure_Data_Files"]
    assert (pressure["n_accepted"], pressure["extensions"], pressure["has_dat_fail"]) == (
        2,
        ".dat:1;.dat_fail:1",
        True,
    )
    assert by_path["Test Plan 30"]["videos"] == "firing.mp4:5368.7MB"
    assert library == []
    folder_csv, _ = write(tmp_path, folders, library)
    assert folder_csv.read_text().splitlines()[0].startswith("root,folder_path,folder_id,n_accepted")
