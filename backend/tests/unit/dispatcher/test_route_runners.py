"""Route runners on the shared runner: A2 (S6's LaTeX) end to end on S5's fixture, D bursts, F wiring,
A1 office files released. Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT."""

import json
import uuid

import pytest
from sqlalchemy import select

from backend.dispatcher import media_run
from backend.dispatcher.contract import DocumentFields, ProcessedDocument
from backend.dispatcher.media_run import RepresentativePending, process_d_document, process_f_document
from backend.dispatcher.routing import PROCESSED_MARK, dispatch
from backend.dispatcher.source_run import process_a2_document
from backend.postgres import pipeline_config
from backend.postgres.models import Document
from backend.storage.minio import CIR, BucketStore, parse_uri
from backend.tests.unit.dispatcher.test_dispatch import _file, _seed

pytest.importorskip("pylatexenc")


def _processed(minio, document) -> dict:
    _, key = parse_uri(document.metadata_sources[PROCESSED_MARK]["uri"])
    return json.loads(BucketStore(minio, CIR).get(key))


def test_a2_assembles_the_master_with_its_section_file(session, minio):
    _seed(session, minio)
    pipeline_config.set_value(session, "routes.A2.enabled", True, "test")
    session.commit()
    released = dispatch(session, minio).to_process
    main = session.scalars(select(Document).where(Document.title == "report_main")).one()
    assert [(r.task, r.queue) for r in released if r.doc_id == main.doc_id] == [
        ("dcl.process.route_a2", "cpu_parse")
    ]

    outcome = process_a2_document(session, minio, main.doc_id)
    session.commit()
    assert outcome.status == "WAITING_FOR_ROUTE"  # clean, parked: no indexer in this test
    processed = _processed(minio, main)
    text = " ".join(node["content"] for node in processed["nodes"])
    assert "hot fire campaign" in text.casefold() and "845" in text
    sources = {node["metadata"].get("source", "").split(":")[0] for node in processed["nodes"]}
    assert sources == {
        "report/report_main.tex",
        "report/sections/results.tex",
    }  # relative to the Test Plan 37 subtree


def _fake_doc(sha: str, route: str) -> ProcessedDocument:
    return ProcessedDocument(
        blob_sha256=sha,
        route=route,
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{sha}/{route}/v1/",
        document=DocumentFields(title="x"),
    )


def _photos(session, minio):
    png = b"\x89PNG\r\n\x1a\n" + uuid.uuid4().bytes  # fresh content: readings cached in MinIO never leak in
    _file(session, minio, "p1", "F-TP12", "IMG_0001.png", png + b"1", "image/png")
    _file(session, minio, "p2", "F-TP12", "IMG_0002.png", png + b"2", "image/png")
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    pipeline_config.set_value(session, "routes.D.enabled", True, "test")
    session.commit()


def test_d_burst_members_wait_for_and_reuse_the_representative(session, minio, monkeypatch):
    pytest.importorskip("imagehash")  # the media dependency group
    from backend.routes import d_photos as d

    _seed_folders_only(session)
    _photos(session, minio)
    session.execute(__import__("sqlalchemy").text("UPDATE sync_roots SET cloud_allowed = true"))
    session.commit()
    dispatch(session, minio, section_file_sets=())
    docs = {doc.title: doc for doc in session.scalars(select(Document).where(Document.route == "D"))}
    first, second = docs["IMG_0001"], docs["IMG_0002"]
    shas = {
        t: session.execute(
            __import__("sqlalchemy").text("select blob_sha256 from document_sources where doc_id = :d"),
            {"d": doc.doc_id},
        ).scalar()
        for t, doc in docs.items()
    }
    monkeypatch.setattr(media_run, "vision_for", lambda session: object())
    monkeypatch.setattr(d, "burst_readings", lambda photos: {sha: ("0" * 16, None) for sha, _ in photos})
    seen = []

    def fake_photo(data, *, blob_sha256, representative, cluster_id, **kw):
        seen.append((blob_sha256, representative, cluster_id))
        reading = d.PhotoReading(
            image_class=d.ImageClass.HARDWARE_PHOTO, content="valve body", metadata={}, confidence=0.9
        )
        return _fake_doc(blob_sha256, "D"), None if representative else reading

    monkeypatch.setattr(d, "process_photo", fake_photo)
    rep_sha = min(shas.values())  # identical pHash, no time: the cluster's first id leads
    rep_doc, member_doc = (first, second) if shas["IMG_0001"] == rep_sha else (second, first)
    with pytest.raises(RepresentativePending):
        process_d_document(session, minio, member_doc.doc_id)
    session.rollback()
    process_d_document(session, minio, rep_doc.doc_id)
    session.commit()
    process_d_document(session, minio, member_doc.doc_id)
    session.commit()
    assert seen[0] == (rep_sha, None, rep_sha)
    member_sha, reading, cluster = seen[1]
    assert (reading.content, cluster) == ("valve body", rep_sha) and member_sha != rep_sha


def _seed_folders_only(session):
    from backend.postgres.models import DriveFolder
    from backend.tests.unit.dispatcher.test_dispatch import FOLDERS

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
    session.flush()


def test_f_hands_the_video_to_process_video_with_the_transcriber(session, minio, monkeypatch):
    from backend.routes import f_video as f

    _seed_folders_only(session)
    _file(
        session, minio, "v1", "F-TP12", "firing.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32, "video/mp4"
    )
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    pipeline_config.set_value(session, "routes.F.enabled", True, "test")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    assert (release.task, release.queue) == ("dcl.process.route_f", "media")
    monkeypatch.setattr(media_run, "vision_for", lambda session: "vision")
    monkeypatch.setattr(media_run, "_transcriber", lambda: "whisper")
    calls = []
    monkeypatch.setattr(
        f, "process_video", lambda data, **kw: calls.append(kw) or _fake_doc(kw["blob_sha256"], "F")
    )
    assert process_f_document(session, minio, release.doc_id).status == "WAITING_FOR_ROUTE"
    assert (calls[0]["file_name"], calls[0]["transcribe"], calls[0]["vision"]) == (
        "firing.mp4",
        "whisper",
        "vision",
    )


def test_a1_releases_word_files_now(session, minio):
    _seed_folders_only(session)
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as docx:
        docx.writestr("[Content_Types].xml", "<Types/>")
        docx.writestr("word/document.xml", "<w:document/>")
    _file(session, minio, "w1", "F-TP12", "Heater test.docx", buffer.getvalue(), "application/zip")
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    pipeline_config.set_value(session, "routes.A1.enabled", True, "test")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    assert (release.task, release.queue) == ("dcl.process.route_a1", "cpu_parse")


def test_b_indexes_a_script_through_s6_process_code(session, minio):
    from backend.dispatcher.source_run import process_b_document

    _seed_folders_only(session)
    script = (
        b'"""Nozzle sizing."""\n\nP_ATM_BAR = 1.01325\n\n\n'
        b"def expansion_ratio(pc_bar: float) -> float:\n    return pc_bar / P_ATM_BAR\n"
    )
    _file(
        session,
        minio,
        "s1",
        "F-TP12",
        "nozzle_calc.py",
        script + b"# " + uuid.uuid4().hex.encode() + b"\n",
        "text/x-python",
    )
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    pipeline_config.set_value(session, "routes.B.enabled", True, "test")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    assert (release.task, release.queue) == ("dcl.process.route_b", "cpu_parse")
    assert (
        process_b_document(session, minio, release.doc_id).status == "WAITING_FOR_ROUTE"
    )  # parked, no indexer
    document = session.get(Document, release.doc_id)
    text = " ".join(node["content"] for node in _processed(minio, document)["nodes"])
    assert "def expansion_ratio" in text and "nozzle_calc.py" in text


DRAWIO = (
    '<mxfile><diagram name="Feed system"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="2" value="Propellant tank" vertex="1" parent="1"/>'
    '<mxCell id="3" value="Solenoid valve SV-01" vertex="1" parent="1"/>'
    '<mxCell id="4" edge="1" source="2" target="3" parent="1"/></root></mxGraphModel></diagram></mxfile>'
)


def test_e_reads_a_drawio_diagram_through_s6_process_diagram(session, minio):
    from backend.dispatcher.source_run import process_e_document

    _seed_folders_only(session)
    data = (DRAWIO + f"<!-- {uuid.uuid4().hex} -->").encode()
    _file(session, minio, "e1", "F-TP12", "Feed system Rev C.drawio", data, "text/xml")
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    pipeline_config.set_value(session, "routes.E.enabled", True, "test")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    assert (release.task, release.queue) == ("dcl.process.route_e", "cpu_parse")
    assert (
        process_e_document(session, minio, release.doc_id).status == "WAITING_FOR_ROUTE"
    )  # parked, no indexer
    text = " ".join(
        node["content"] for node in _processed(minio, session.get(Document, release.doc_id))["nodes"]
    )
    assert "Propellant tank" in text and "SV-01" in text


def test_g_archive_members_become_documents_and_cad_references_become_relations(session, minio):
    import io
    import zipfile

    from backend.dispatcher.source_run import process_g_document
    from backend.postgres.models import BlobDerivation, DocumentRelation
    from backend.tests.unit.routes.c_telemetry.test_pipeline import _fake_indexer

    _seed_folders_only(session)
    tag = uuid.uuid4().hex.encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("run/notes.txt", b"Throat diameter 2.1 mm, chamber 12 bar. " + tag)
    _file(session, minio, "z1", "F-TP12", "bundle.zip", buffer.getvalue(), "application/zip")
    _file(session, minio, "c1", "F-TP12", "bracket.dwg", b"AC1032\x00\x00" + tag, "application/octet-stream")
    _file(session, minio, "c2", "F-TP12", "bracket.pdf", b"%PDF-1.4 drawing " + tag, "application/pdf")
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    pipeline_config.set_value(session, "routes.G.enabled", True, "test")
    pipeline_config.set_value(session, "routes.B.enabled", True, "test")
    session.commit()
    released = {
        session.get(Document, r.doc_id).title: r
        for r in dispatch(session, minio, section_file_sets=()).to_process
    }
    assert {t: (r.task, r.queue) for t, r in released.items() if t in ("bundle", "bracket")} == {
        "bundle": ("dcl.process.route_g", "cpu_parse"),
        "bracket": ("dcl.process.route_g", "cpu_parse"),
    }

    for title in ("bundle", "bracket"):
        outcome = process_g_document(session, minio, released[title].doc_id, indexer=_fake_indexer)
        session.commit()
        assert outcome.status in ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS"), title
    (link,) = session.scalars(select(BlobDerivation)).all()
    assert (link.member_path, link.kind) == ("run/notes.txt", "archive_member")
    member = dispatch(session, minio, section_file_sets=()).to_process
    assert [(session.get(Document, r.doc_id).title, r.task) for r in member] == [
        ("notes", "dcl.process.route_b")
    ]

    drawing = session.scalars(
        select(Document).where(Document.title == "bracket", Document.route == "A1")
    ).one()
    cad = session.get(Document, released["bracket"].doc_id)
    pair = tuple(sorted([cad.doc_id, drawing.doc_id], key=str))
    assert session.get(DocumentRelation, (*pair, "REFERENCES")) is not None
