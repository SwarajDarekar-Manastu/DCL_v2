"""A document stands for every byte-identical copy of its files, so a part that exists in two test plans must
be read from the copy beside its master, never from the alphabetically first copy anywhere.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT, and pylatexenc.
"""

import pytest
from sqlalchemy import select

from backend.dispatcher.routing import dispatch
from backend.dispatcher.source_run import process_a2_document
from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import Document, DriveFolder, DriveItem
from backend.tests.unit.dispatcher.test_dispatch import _put

pytest.importorskip("pylatexenc")

SHARED = b"\\section{Test setup}\nThe injector was fed from tank T1.\n"
ONLY_HERE = b"\\section{Observations}\nPressure was stable after two seconds.\n"


FOLDERS = [
    ("ROOT", "APU Injector", None, "APU Injector"),
    ("P18", "Test Plan 18", "ROOT", "APU Injector/Test Plan 18"),
    ("P4", "Test Plan 4", "ROOT", "APU Injector/Test Plan 4"),
    ("S18", "Sections", "P18", "APU Injector/Test Plan 18/Sections"),
    ("S4", "Sections", "P4", "APU Injector/Test Plan 4/Sections"),
]


def _tree(session) -> None:
    for item_id, name, parent, path in FOLDERS:
        session.add(
            DriveFolder(
                drive_id="D",
                item_id=item_id,
                root_name="APU Injector",
                name=name,
                parent_item_id=parent,
                path_cached=path,
            )
        )


def _file(session, minio, item_id, folder_id, name, data) -> None:
    path = next(f[3] for f in FOLDERS if f[0] == folder_id)
    session.add(
        DriveItem(
            drive_id="D",
            item_id=item_id,
            root_name="APU Injector",
            name=name,
            extension=".tex",
            parent_item_id=folder_id,
            path_cached=f"{path}/{name}",
            status=DriveItemStatus.LANDED,
            blob_sha256=_put(session, minio, data),
            detected_mime="text/x-tex",
            size_bytes=len(data),
        )
    )


def test_a_part_with_a_copy_in_another_plan_is_read_beside_its_master(session, minio):
    _tree(session)
    _file(session, minio, "shared-18", "S18", "setup.tex", SHARED)
    _file(session, minio, "shared-4", "S4", "setup.tex", SHARED)
    _file(session, minio, "only-4", "S4", "observations.tex", ONLY_HERE)
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["P4"], "test")
    pipeline_config.set_value(session, "routes.A2.enabled", True, "test")
    session.commit()
    dispatch(session, minio)
    (document,) = session.scalars(select(Document)).all()

    outcome = process_a2_document(session, minio, document.doc_id)

    assert outcome.status == "WAITING_FOR_ROUTE"  # processed cleanly; no indexer in this test
    assert session.get(Document, document.doc_id).metadata_sources.get("error") is None


def test_a_document_is_read_from_the_folder_it_was_created_in_not_its_first_copy(session, minio):
    """The real failure: the primary exists in plans 4 and 7, the part only in plan 7, the document was made
    in plan 7. The alphabetically first copy of the primary is plan 4's, a folder the part is not in."""
    for item_id, name, parent, path in [
        ("ROOT", "APU Injector", None, "APU Injector"),
        ("P4", "Test Plan 4", "ROOT", "APU Injector/Test Plan 4"),
        ("P7", "Test Plan 7", "ROOT", "APU Injector/Test Plan 7"),
        ("T4", "Tables", "P4", "APU Injector/Test Plan 4/Tables"),
        ("T7", "Tables", "P7", "APU Injector/Test Plan 7/Tables"),
    ]:
        session.add(
            DriveFolder(
                drive_id="D",
                item_id=item_id,
                root_name="APU Injector",
                name=name,
                parent_item_id=parent,
                path_cached=path,
            )
        )
    for item_id, folder, name, data in [
        ("e4", "T4", "Expectation_Parameters.tex", ONLY_HERE),
        ("e7", "T7", "Expectation_Parameters.tex", ONLY_HERE),
        ("t7", "T7", "TestPlan.tex", SHARED),
    ]:
        path = {"T4": "APU Injector/Test Plan 4/Tables", "T7": "APU Injector/Test Plan 7/Tables"}[folder]
        session.add(
            DriveItem(
                drive_id="D",
                item_id=item_id,
                root_name="APU Injector",
                name=name,
                extension=".tex",
                parent_item_id=folder,
                path_cached=f"{path}/{name}",
                status=DriveItemStatus.LANDED,
                blob_sha256=_put(session, minio, data),
                detected_mime="text/x-tex",
                size_bytes=len(data),
            )
        )
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["P7"], "test")
    pipeline_config.set_value(session, "routes.A2.enabled", True, "test")
    session.commit()
    dispatch(session, minio)
    (document,) = session.scalars(select(Document)).all()
    assert document.folder_context["path_cached"].startswith("APU Injector/Test Plan 7/")

    outcome = process_a2_document(session, minio, document.doc_id)

    assert outcome.status == "WAITING_FOR_ROUTE"
    assert session.get(Document, document.doc_id).metadata_sources.get("error") is None
