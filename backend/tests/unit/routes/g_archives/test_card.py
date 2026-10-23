"""Route G as metadata cards: one text node per file, nothing extracted, nothing that crashes on bad bytes."""

import gzip
import hashlib
import io
import tarfile
import zipfile
from datetime import UTC, datetime

import pytest

from backend.dispatcher.folder_context import FolderContext
from backend.indexing.anchors import make_anchor
from backend.indexing.chunker import chunk_document
from backend.postgres.enums import DocKind
from backend.routes.g_archives.card import Copy
from backend.routes.g_archives.route import Stores, process

FOLDER = FolderContext(
    root_name="APU",
    breadcrumb=["APU", "Test Campaign 2", "Test Plan 7", "CAD"],
    path_cached="APU/Test Campaign 2/Test Plan 7/CAD",
    test_plan_id="TP07",
    test_run_id="T01",
    hardware_item="INJ14",
)


def _card(name: str, data: bytes, **kwargs):
    cir: dict[str, bytes] = {}
    processed = process(
        data,
        blob_sha256=hashlib.sha256(data).hexdigest(),
        file_name=name,
        folder=FOLDER,
        stores=Stores(put_cir=lambda key, value: cir.setdefault(key, value) and key),
        **kwargs,
    )
    for node in chunk_document(processed, count_tokens=lambda texts: [len(t) // 4 + 1 for t in texts]):
        make_anchor("00000000-0000-0000-0000-000000000001", node)
    assert set(cir) == {"card.json"}
    return processed


def _zip(members: dict[str, bytes], encrypted: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    raw = bytearray(buffer.getvalue())
    if encrypted:
        for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            start = 0
            while (start := raw.find(signature, start)) != -1:
                raw[start + offset] |= 0x1
                start += 4
    return bytes(raw)


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_an_archive_card_lists_its_members_and_never_reads_one(monkeypatch):
    data = _zip(
        {
            "Injector/Test_plan.tex": b"\\section{A}",
            "Injector/Figures/p.png": b"png",
            "Injector/run.py": b"x=1",
        }
    )

    def refuse(*args, **kwargs):
        raise AssertionError("a member was read")

    monkeypatch.setattr(zipfile.ZipFile, "open", refuse)
    monkeypatch.setattr(zipfile.ZipFile, "read", refuse)
    processed = _card("Injector.zip", data)

    (node,) = processed.nodes
    assert processed.derived_blobs == [] and processed.flags == [] and processed.mentions == []
    assert "ZIP archive: Injector.zip" in node.content
    assert "Contents (zip): 3 files" in node.content
    assert "File types: tex 1, png 1, py 1" in node.content
    assert "Top-level entries: Injector/" in node.content
    assert "Injector/Test_plan.tex" in node.content
    assert processed.document.catalog["listing"]["count"] == 3


def test_the_card_names_the_plan_run_hardware_dates_and_every_copy():
    copies = [
        Copy("APU/Test Campaign 2/Test Plan 12/CAD/bracket.stl", datetime(2025, 12, 2, tzinfo=UTC)),
        Copy("APU/Test Campaign 1/Test Plan 4/CAD/bracket.stl", None),
    ]
    processed = _card(
        "bracket.dwg",
        b"AC1032" + bytes(40),
        created_at=datetime(2025, 11, 18, tzinfo=UTC),
        modified_at=datetime(2025, 11, 20, tzinfo=UTC),
        copies=copies,
    )
    text = processed.nodes[0].content
    assert "AutoCAD drawing (DWG): bracket.dwg" in text
    assert "Identified from the folder: test plan TP07, run T01, hardware INJ14" in text
    assert "File dates: last modified 2025-11-20, created 2025-11-18" in text
    assert "Test plans whose folders hold this file: TP07, TP12, TP04" in text
    assert "Also stored in 2 other places: APU/Test Campaign 2/Test Plan 12/CAD/bracket.stl" in text
    assert "bracket.stl (modified 2025-12-02)" in text
    assert processed.document.doc_kind == DocKind.CAD_REFERENCE
    assert processed.document.catalog["copies"][0]["modified_at"].startswith("2025-12-02")


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("cut_off.zip", _zip({"a.txt": b"x" * 500})[:-60], "could not be listed"),
        ("cut_off.tar.gz", _tar_gz({"a.txt": b"x" * 5000})[:-40], "could not be listed"),
        ("secret.zip", _zip({"a.txt": b"x"}, encrypted=True), "Password-protected: yes"),
        ("not_a_zip.wbpz", bytes(range(256)) * 4, "could not be listed"),
        ("traversal.tar.gz", _tar_gz({"../outside.txt": b"x", "ok.txt": b"y"}), "Contents (tar): 2 files"),
        ("empty.zip", b"PK\x05\x06" + bytes(18), "Contents (zip): 0 files"),
    ],
)
def test_a_damaged_hostile_or_locked_archive_is_a_card_not_a_failure(name, data, expected):
    processed = _card(name, data)
    assert expected in processed.nodes[0].content
    assert processed.flags == [] and processed.derived_blobs == []


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("study.wbpz", DocKind.CAE_PACKAGE),
        ("model.stl", DocKind.CAD_REFERENCE),
        ("part.step", DocKind.CAD_REFERENCE),
        ("part.stp", DocKind.CAD_REFERENCE),
        ("surface.igs", DocKind.CAD_REFERENCE),
        ("body.scdoc", DocKind.CAD_REFERENCE),
        ("plate.dwg", DocKind.CAD_REFERENCE),
        ("bundle.tgz", DocKind.UNKNOWN),
        ("run.dat.gz", DocKind.UNKNOWN),
    ],
)
def test_every_file_type_is_one_card_node_even_when_its_bytes_mean_nothing(name, kind):
    processed = _card(name, b"not what the name says" * 20)
    assert len(processed.nodes) == 1 and processed.flags == [] and processed.derived_blobs == []
    assert processed.document.doc_kind == kind
    assert processed.document.title == name


def test_a_gzipped_file_card_names_the_file_inside_without_decompressing():
    processed = _card("11bar_10sec.dat.gz", gzip.compress(b"time\tAIN0\n0\t1.2\n" * 100))
    assert "Files: 11bar_10sec.dat" in processed.nodes[0].content


def test_a_mesh_card_carries_the_measurements_and_the_related_drawings():
    pytest.importorskip("trimesh")
    cube = (
        "solid c\n"
        + "".join(
            f"facet normal 0 0 0\nouter loop\nvertex {a}\nvertex {b}\nvertex {c}\nendloop\nendfacet\n"
            for a, b, c in [
                ("0 0 0", "20 0 0", "20 20 0"),
                ("0 0 0", "20 20 0", "0 20 0"),
                ("0 0 20", "20 20 20", "20 0 20"),
                ("0 0 20", "0 20 20", "20 20 20"),
                ("0 0 0", "0 20 20", "0 0 20"),
                ("0 0 0", "0 20 0", "0 20 20"),
                ("20 0 0", "20 0 20", "20 20 20"),
                ("20 0 0", "20 20 20", "20 20 0"),
                ("0 0 0", "20 0 20", "20 0 0"),
                ("0 0 0", "0 0 20", "20 0 20"),
                ("0 20 0", "20 20 0", "20 20 20"),
                ("0 20 0", "20 20 20", "0 20 20"),
            ]
        )
        + "endsolid c\n"
    )
    processed = _card(
        "bracket_v3.stl",
        cube.encode(),
        path="CAD/bracket_v3.stl",
        folder_files=["CAD/bracket_v3.pdf", "CAD/other_plate.dxf"],
    )
    text = processed.nodes[0].content
    assert "bounding box 20.0 × 20.0 × 20.0 model units" in text
    assert "Related files (same name): bracket_v3.pdf" in text
    assert processed.document.catalog["references"] == ["CAD/bracket_v3.pdf"]
    assert processed.document.catalog["measurement"]["triangles"] == 12
