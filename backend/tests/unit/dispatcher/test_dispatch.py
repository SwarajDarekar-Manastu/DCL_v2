"""Dispatch end to end on a migrated PostgreSQL + MinIO: scope, assembler, gating, flags, idempotency.

Uses S5's fixtures two_latex_masters and pdf_is_html. Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT.
"""

import hashlib
import io
from pathlib import Path

from sqlalchemy import func, select

from backend.dispatcher.routing import dispatch
from backend.postgres import pipeline_config
from backend.postgres.enums import DriveItemStatus as S
from backend.postgres.models import Blob, Document, DocumentSource, DriveFolder, DriveItem, ReviewFlag
from backend.storage.minio import RAW, raw_key

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
LATEX = FIXTURES / "a2_source" / "two_latex_masters"
FOLDERS = [
    ("ROOT", "APU Injector", None, "APU Injector"),
    ("F-TP37", "Test Plan 37", "ROOT", "APU Injector/Test Plan 37"),
    ("F-REPORT", "report", "F-TP37", "APU Injector/Test Plan 37/report"),
    ("F-SEC", "sections", "F-REPORT", "APU Injector/Test Plan 37/report/sections"),
    ("F-TP12", "Test Plan 12", "ROOT", "APU Injector/Test Plan 12"),
    ("F-OUT", "Other", "ROOT", "APU Injector/Other"),
]


def _put(session, minio, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    if session.get(Blob, sha) is None:
        minio.put_object(RAW, raw_key(sha), io.BytesIO(data), len(data))
        session.add(Blob(sha256=sha, size_bytes=len(data), minio_uri=f"s3://dcl-raw/{raw_key(sha)}"))
        session.flush()
    return sha


def _file(session, minio, item_id, folder_id, name, data, mime):
    folder = next(f for f in FOLDERS if f[0] == folder_id)
    sha = _put(session, minio, data)
    session.add(
        DriveItem(
            drive_id="D",
            item_id=item_id,
            root_name="APU Injector",
            name=name,
            extension="." + name.rsplit(".", 1)[-1] if "." in name else None,
            parent_item_id=folder_id,
            path_cached=f"{folder[3]}/{name}",
            status=S.LANDED,
            blob_sha256=sha,
            detected_mime=mime,
            size_bytes=len(data),
        )
    )
    return sha


def _folders(session):
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


def _seed(session, minio):
    _folders(session)
    for name in ("report_main.tex", "report_draft.tex"):
        _file(session, minio, name, "F-REPORT", name, (LATEX / name).read_bytes(), "text/x-tex")
    _file(
        session,
        minio,
        "results",
        "F-SEC",
        "results.tex",
        (LATEX / "sections" / "results.tex").read_bytes(),
        "text/x-tex",
    )
    html = (FIXTURES / "dispatcher" / "pdf_is_html" / "Test_Report_12.pdf").read_bytes()
    _file(session, minio, "html-pdf", "F-TP12", "Test_Report_12.pdf", html, "text/html")
    dat = b"time\tAIN0\n0.000\t1.20\n0.001\t1.21\n0.002\t1.22\n"
    _file(session, minio, "dat", "F-TP12", "TP12_T01.dat", dat, "text/plain")
    _file(session, minio, "dat-copy", "F-TP37", "TP12_T01 copy.dat", dat, "text/plain")
    _file(session, minio, "outside", "F-OUT", "notes.txt", b"outside the scope\n", "text/plain")
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP37", "F-TP12"], "test")
    session.commit()


def test_a_tex_no_master_includes_is_noted_on_its_document_and_raises_no_flag(session, minio):
    _folders(session)
    _file(session, minio, "stray", "F-TP12", "stray.tex", b"\\section{A loose fragment}\n", "text/x-tex")
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    session.commit()
    dispatch(session, minio)
    (stray,) = [d for d in session.scalars(select(Document)) if d.title == "stray"]
    assert stray.metadata_sources["assembler"]["notes"] == [
        "no master found in the top folder, assembled by filename"
    ]
    assert session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == stray.doc_id)).all() == []


def _docs(session):
    return {d.title: d for d in session.scalars(select(Document))}


def test_dispatch_assembles_gates_flags_and_skips_out_of_scope(session, minio):
    _seed(session, minio)
    result = dispatch(session, minio)
    docs = _docs(session)

    assert set(docs) == {"report_main", "report_draft", "Test_Report_12", "TP12_T01"}
    main = docs["report_main"]
    roles = session.execute(
        select(DocumentSource.role, func.count())
        .where(DocumentSource.doc_id == main.doc_id)
        .group_by(DocumentSource.role)
    ).all()
    assert dict(roles) == {"primary": 1, "part": 1}
    assert (main.route, main.status, main.test_plan_id) == ("A2", "WAITING_FOR_ROUTE", "TP37")
    conflicts = session.scalars(
        select(ReviewFlag.flag_type).where(
            ReviewFlag.doc_id.in_([docs["report_main"].doc_id, docs["report_draft"].doc_id])
        )
    ).all()
    assert conflicts == ["CONFLICT", "CONFLICT"]
    notes = session.scalars(
        select(ReviewFlag.evidence).where(ReviewFlag.doc_id == docs["report_main"].doc_id)
    ).all()
    assert [(e["relation"], "b" in e and e["b"]) for e in notes] == [("note", None)]

    html = docs["Test_Report_12"]
    assert (html.route, html.status, html.staged_payload_uri is not None) == (None, "HALTED", True)
    (flag,) = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == html.doc_id)).all()
    assert (flag.flag_type, flag.severity, flag.evidence["error"]) == (
        "UNSUPPORTED_FORMAT",
        "HARD",
        "no adapter for text/html",
    )

    dat = docs["TP12_T01"]
    assert (dat.route, dat.status, dat.test_plan_id, dat.test_run_id) == (
        "C",
        "WAITING_FOR_ROUTE",
        "TP12",
        "T01",
    )
    assert (result.created, result.halted, result.waiting) == (4, 1, 3)
    assert "notes" not in docs


def test_a_second_dispatch_creates_nothing_and_copies_get_no_second_document(session, minio):
    _seed(session, minio)
    dispatch(session, minio)
    before = session.scalar(select(func.count()).select_from(Document))
    again = dispatch(session, minio)
    assert again.created == 0
    assert session.scalar(select(func.count()).select_from(Document)) == before
    assert (
        session.scalar(
            select(func.count()).select_from(DocumentSource).where(DocumentSource.role == "primary")
        )
        == before
    )


def test_restricted_or_uninspected_blobs_are_not_dispatched(session, minio):
    _seed(session, minio)
    for item in session.scalars(select(DriveItem)):
        item.detected_mime = None
    session.commit()
    assert dispatch(session, minio).created == 0


def _modify_in_place(session, minio, item_id, new_data):
    item = session.scalars(select(DriveItem).where(DriveItem.item_id == item_id)).one()
    new_sha = _put(session, minio, new_data)
    item.previous_blob_sha256 = item.previous_blob_sha256 or item.blob_sha256
    item.blob_sha256, item.size_bytes = new_sha, len(new_data)
    session.commit()
    return item


def test_content_modified_in_place_replaces_the_old_document_once_the_new_one_is_searchable(session, minio):
    from backend.dispatcher.routing import replace_older
    from backend.postgres.models import DocumentRelation

    _seed(session, minio)
    dispatch(session, minio)
    old = _docs(session)["Test_Report_12"]
    old_status = old.status
    item = _modify_in_place(session, minio, "html-pdf", b"%PDF-1.7\n% the real report now\n")

    result = dispatch(session, minio)

    new = next(
        d for d in session.scalars(select(Document)) if d.doc_id != old.doc_id and d.title == "Test_Report_12"
    )
    assert (new.route, new.status, result.superseded) == ("A1", "WAITING_FOR_ROUTE", 0)
    session.refresh(old)
    session.refresh(item)
    assert (
        old.status == old_status and item.previous_blob_sha256 is not None
    )  # still live, replacement pending

    new.status = "ACTIVE"  # its commit
    assert replace_older(session, item.blob_sha256) == 1
    relation = session.scalars(select(DocumentRelation)).one()
    assert (relation.doc_id_a, relation.doc_id_b, relation.relation) == (new.doc_id, old.doc_id, "SUPERSEDES")
    assert (old.status, item.previous_blob_sha256) == ("SUPERSEDED", None)


def test_a_copy_of_the_old_content_keeps_the_old_document_live(session, minio):
    from backend.postgres.models import DocumentRelation

    _seed(session, minio)
    dispatch(session, minio)
    old = _docs(session)["TP12_T01"]  # its content also sits at "TP12_T01 copy.dat"
    _modify_in_place(session, minio, "dat", b"time\tAIN0\n0.000\t2.00\n0.001\t2.01\n0.002\t2.02\n")
    dispatch(session, minio)
    session.refresh(old)
    assert old.status == "WAITING_FOR_ROUTE"
    assert session.scalar(select(func.count()).select_from(DocumentRelation)) == 1


def test_sweep_settles_documents_no_live_location_holds(session, minio):
    from backend.dispatcher.routing import sweep_documents

    _seed(session, minio)
    dispatch(session, minio)
    docs = _docs(session)
    for item in session.scalars(select(DriveItem).where(DriveItem.item_id.in_(["report_main.tex"]))):
        item.status = S.DELETED
    for item in session.scalars(select(DriveItem).where(DriveItem.item_id == "report_draft.tex")):
        item.status = S.QUARANTINED
    session.commit()
    counts = sweep_documents(session)
    session.commit()
    session.refresh(docs["report_main"])
    session.refresh(docs["report_draft"])
    assert (docs["report_main"].status, docs["report_draft"].status) == ("DELETED", "QUARANTINED")
    assert (counts["deleted"], counts["quarantined"]) == (1, 1)
    for item in session.scalars(select(DriveItem).where(DriveItem.item_id == "report_draft.tex")):
        item.status = S.LANDED
    session.commit()
    assert sweep_documents(session)["reactivated"] == 1


def _zip_bytes(*members: str) -> bytes:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member in members:
            archive.writestr(member, "x")
    return buffer.getvalue()


def test_office_files_are_routed_by_their_zip_members_and_retype_fixes_older_rows(session, minio):
    from backend.dispatcher.routing import retype_waiting

    _seed(session, minio)
    xlsx = _zip_bytes("[Content_Types].xml", "xl/workbook.xml")
    docx = _zip_bytes("[Content_Types].xml", "word/document.xml")
    _file(
        session,
        minio,
        "xlsx",
        "F-TP12",
        "Setup.xlsx",
        xlsx,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    _file(
        session,
        minio,
        "docx",
        "F-TP12",
        "Report.docx",
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    session.commit()
    dispatch(session, minio)
    docs = _docs(session)
    assert (docs["Setup"].route, docs["Report"].route) == ("C", "A1")

    docs["Setup"].route = "G"  # as written by the first live dispatch before the fix
    session.commit()
    assert retype_waiting(session, minio) == {"G->C": 1}
    session.refresh(docs["Setup"])
    assert docs["Setup"].route == "C"


def test_reassemble_rebuilds_untouched_waiting_documents_of_a_route(session, minio):
    from backend.dispatcher.routing import reset_waiting
    from backend.postgres.enums import Route

    _seed(session, minio)
    dispatch(session, minio)
    touched = _docs(session)["report_draft"]
    for flag in session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == touched.doc_id)):
        flag.status = "IN_PROGRESS"
    session.commit()
    assert reset_waiting(session, Route.A2) == 1  # report_main only; report_draft has a flag in progress
    session.commit()
    again = dispatch(session, minio)
    assert again.created == 1
    assert set(_docs(session)) == {"report_main", "report_draft", "Test_Report_12", "TP12_T01"}
