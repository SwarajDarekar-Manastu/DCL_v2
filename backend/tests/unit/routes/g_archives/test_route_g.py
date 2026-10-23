# ruff: noqa: E501 — the MatML fixture is one XML block
"""Route G (file 03 §11, Lead 2026-10-23) on synthetic archives and CAD files and the real/web samples."""

import gzip
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("lxml")  # parse dependency group (the .wbpz engineering-data reader)

from backend.dispatcher.contract import ProcessedDocument  # noqa: E402
from backend.dispatcher.folder_context import FolderContext  # noqa: E402
from backend.indexing.anchors import make_anchor  # noqa: E402
from backend.indexing.chunker import chunk_document  # noqa: E402
from backend.postgres.enums import DocKind, FlagSeverity, FlagType  # noqa: E402
from backend.routes.g_archives import archive  # noqa: E402
from backend.routes.g_archives.route import Stores, can_handle, process, process_archive, process_cad  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[5] / "data" / "samples"
WEB = SAMPLES / "web"
FOLDER = FolderContext(root_name="APU", breadcrumb=["APU", "Test Plan 9"], path_cached="APU/Test Plan 9")
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea7"
    "d6a4b40000000049454e44ae426082"
)


def _sample(path: Path) -> bytes:
    if not path.is_file():
        pytest.skip(f"{path} not exported locally")
    return path.read_bytes()


def _zip(files: dict[str, bytes], encrypted: set[str] = frozenset()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(info, data)
    raw = bytearray(buffer.getvalue())
    if encrypted:  # set the "encrypted" general-purpose bit in every local and central header
        for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            start = 0
            while (start := raw.find(signature, start)) != -1:
                raw[start + offset] |= 0x1
                start += 4
    return bytes(raw)


def _run(name: str, data: bytes, cir=None, **kwargs) -> ProcessedDocument:
    cir = {} if cir is None else cir
    processed = process(
        data,
        blob_sha256=hashlib.sha256(data).hexdigest(),
        file_name=name,
        folder=FOLDER,
        stores=Stores(put_cir=lambda k, v: cir.setdefault(k, v) and k),
        **kwargs,
    )
    assert ProcessedDocument.model_validate_json(processed.model_dump_json()) == processed
    for node in chunk_document(processed, count_tokens=lambda texts: [len(t) // 4 + 1 for t in texts]):
        make_anchor("00000000-0000-0000-0000-000000000001", node)
    return processed


def test_members_become_derived_blobs_and_junk_is_skipped():
    cir = {}
    data = _zip(
        {
            "project/notes.md": b"# Notes\nInjector 4 good.",
            "project/run/11bar.dat": b"x",
            "project/.DS_Store": b"\x00\x01junk",
            "project/env/site-packages/pkg/mod.py": b"print(1)",
        }
    )
    processed = _run("bundle.zip", data, cir)

    derived = {b.member_path: b for b in processed.derived_blobs}
    assert set(derived) == {"project/notes.md", "project/run/11bar.dat"}
    assert all(b.kind == "archive_member" for b in derived.values())
    assert derived["project/notes.md"].data == b"# Notes\nInjector 4 good."
    catalog = processed.document.catalog
    assert (catalog["members"], catalog["kept"], catalog["skipped"]) == (4, 2, 2)
    contents = processed.nodes[0].content
    assert "project/.DS_Store — 6 bytes — skipped (T2:.DS_Store)" in contents
    assert "project/notes.md — 24 bytes — route B" in contents
    manifest = json.loads(cir["manifest.json"])
    assert {m["path"]: m["status"] for m in manifest["members"]}[
        "project/env/site-packages/pkg/mod.py"
    ] == "skipped"
    assert processed.flags == []


def test_nested_archives_expand_in_place():
    inner = _zip({"docs/readme.txt": b"inner text"})
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("cad/part.txt")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"part"))
    processed = _run("outer.zip", _zip({"a/inner.zip": inner, "b/bundle.tar.gz": tar_buffer.getvalue()}))

    assert {b.member_path for b in processed.derived_blobs} == {
        "a/inner.zip!/docs/readme.txt",
        "b/bundle.tar.gz!/cad/part.txt",
    }
    assert processed.document.catalog["nested_archives"] == ["a/inner.zip", "b/bundle.tar.gz"]


def test_nesting_deeper_than_three_is_a_bomb():
    data = b"deep"
    for level in range(4):
        data = _zip({f"level{level}.zip" if level else "x.txt": data})
    processed = _run("deep.zip", data)
    flag = processed.flags[0]
    assert flag.flag_type == FlagType.PARSE_FAILURE and flag.severity == FlagSeverity.HARD
    assert "nesting depth above 3" in flag.evidence.error


def test_path_traversal_is_rejected_with_the_partial_manifest():
    processed = _run("evil.zip", _zip({"ok.txt": b"fine", "../../etc/passwd": b"root"}))
    flag = processed.flags[0]

    assert flag.flag_type == FlagType.PARSE_FAILURE and "path traversal" in flag.evidence.error
    assert processed.derived_blobs == [] and processed.nodes == []
    assert "ok.txt — 4 bytes" in flag.evidence.partial_output


def test_compression_ratio_bomb():
    processed = _run("zeros.zip", _zip({"zeros.bin": b"\x00" * (8 * 1024 * 1024)}))
    assert "compression ratio above 100" in processed.flags[0].evidence.error


def test_encrypted_member_is_a_hard_failure():
    processed = _run("secret.zip", _zip({"a.txt": b"x"}, encrypted={"a.txt"}))
    assert processed.flags[0].evidence.error.startswith("encrypted archive")


def test_entry_limit(monkeypatch):
    monkeypatch.setattr(archive, "MAX_ENTRIES", 3)
    processed = _run("many.zip", _zip({f"f{i}.txt": b"x" for i in range(5)}))
    assert "more than 3 entries" in processed.flags[0].evidence.error


def test_large_member_is_held_with_a_soft_flag(monkeypatch):
    monkeypatch.setattr(archive, "MAX_MEMBER_BYTES", 10)
    processed = _run("big.zip", _zip({"logs/big.txt": b"y" * 50, "small.txt": b"ok"}))

    assert [b.member_path for b in processed.derived_blobs] == ["small.txt"]
    flag = processed.flags[0]
    assert flag.flag_type == FlagType.HELD_LARGE_FILE and flag.severity == FlagSeverity.SOFT
    assert flag.evidence.size_bytes == 50


def test_single_gzip_member_and_mostly_junk():
    processed = _run("11bar_10sec.dat.gz", gzip.compress(b"t,p\n0,1\n"))
    assert [(b.member_path, b.data) for b in processed.derived_blobs] == [("11bar_10sec.dat", b"t,p\n0,1\n")]

    junk = _zip({f"d{i}/.DS_Store": b"x" for i in range(10)} | {"keep.txt": b"k"})
    catalog = _run("mac.zip", junk).document.catalog
    assert catalog["mostly_junk"] is True


def test_tar_symlinks_are_ignored():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
        info = tarfile.TarInfo("data.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    processed = _run("a.tar", buffer.getvalue())
    assert [b.member_path for b in processed.derived_blobs] == ["data.txt"]
    assert "link — 0 bytes — symlink ignored" in processed.nodes[0].content


WBPJ = b"<Project><System DisplayText='Static Structural'/><System DisplayText='Engineering Data'/></Project>"
SOLVE_OUT = b"""ANSYS Mechanical Enterprise  Release 2024 R1
 Number of elements =  12450
 Number of nodes =   40211
 *** WARNING *** element 112 is highly distorted
 >>> SOLUTION CONVERGED AFTER EQUILIBRIUM ITERATION 3
 Elapsed time spent computing solution = 12.5 s
"""
MATML = b"""<EngineeringData><Materials><MatML_Doc>
<Material><BulkDetails><Name>Inconel 718</Name>
<PropertyData property="pr0"><ParameterValue parameter="pa0" format="float"><Data>8190</Data></ParameterValue></PropertyData>
<PropertyData property="pr1"><ParameterValue parameter="pa1" format="float"><Data>2.0E+11</Data></ParameterValue>
<ParameterValue parameter="pa2" format="float"><Data>22</Data></ParameterValue></PropertyData>
</BulkDetails></Material>
<Metadata>
<ParameterDetails id="pa0"><Name>Density</Name><Units><Unit><Name>kg</Name></Unit><Unit power="-3"><Name>m</Name></Unit></Units></ParameterDetails>
<ParameterDetails id="pa1"><Name>Young's Modulus</Name><Units><Unit><Name>Pa</Name></Unit></Units></ParameterDetails>
<ParameterDetails id="pa2"><Name>Temperature</Name><Units><Unit><Name>C</Name></Unit></Units></ParameterDetails>
<PropertyDetails id="pr0"><Name>Density</Name></PropertyDetails>
<PropertyDetails id="pr1"><Name>Elasticity</Name></PropertyDetails>
</Metadata></MatML_Doc></Materials></EngineeringData>"""


def test_wbpz_solver_materials_systems_and_images():
    data = _zip(
        {
            "nozzle.wbpj": WBPJ,
            "dp0/SYS/MECH/solve.out": SOLVE_OUT,
            "dp0/SYS/ENGD/EngineeringData.xml": MATML,
            "dp0/SYS/MECH/file.rst": b"\x00binary results",
            "user_files/report/stress.png": PNG,
        }
    )
    processed = _run("nozzle.wbpz", data)
    catalog = processed.document.catalog

    assert processed.document.doc_kind == DocKind.CAE_PACKAGE
    assert catalog["analysis_systems"] == ["Engineering Data", "Static Structural"]
    assert catalog["materials"] == ["Inconel 718"]
    summary = catalog["solver_logs"]["dp0/SYS/MECH/solve.out"]
    assert summary["elements"] == "12450" and summary["nodes"] == "40211"
    assert summary["elapsed_time"] == "12.5 s"
    assert summary["warnings_errors"] == ["*** WARNING *** element 112 is highly distorted"]
    table = next(n for n in processed.nodes if n.node_type == "table")
    assert "<tr><td>Density</td><td>8190</td><td>kg m^-3</td></tr>" in table.content
    assert (
        "<td>Elasticity: Young&#x27;s Modulus</td>" in table.content
        or "Elasticity: Young's Modulus" in table.content
    )
    assert "Temperature" not in table.content
    assert [m.surface for m in processed.mentions if m.kind == "material"] == ["Inconel 718"]
    assert [b.member_path for b in processed.derived_blobs] == ["user_files/report/stress.png"]


def _stl_box() -> bytes:
    trimesh = pytest.importorskip("trimesh")
    return trimesh.creation.box(extents=(20.0, 10.0, 5.0)).export(file_type="stl")


def test_stl_is_measured_and_linked_to_drawings():
    processed = _run(
        "Nozzle_v2.stl",
        _stl_box(),
        path="cad/Nozzle_v2.stl",
        folder_files=[
            "cad/Nozzle_v2.stl",
            "cad/nozzle-v2.pdf",
            "cad/Bracket.dwg",
            "cad/notes.txt",
            "other/Nozzle_v2.step",
        ],
    )
    node = processed.nodes[0]
    catalog = processed.document.catalog

    assert processed.document.doc_kind == DocKind.CAD_REFERENCE
    assert "bounding box 20.0 × 10.0 × 5.0 model units" in node.content
    assert "volume 1000.0 model units³;" in node.content and "12 triangles" in node.content
    assert catalog["measurement"]["watertight"] is True and catalog["measurement"]["bodies"] == 1
    assert catalog["references"] == ["cad/nozzle-v2.pdf"] and catalog["folder_drawings"] == [
        "cad/Bracket.dwg"
    ]
    assert [m.surface for m in processed.mentions] == ["20.0 × 10.0 × 5.0 model units"]


def test_scdoc_and_dwg_are_cad_references():
    processed = _run(
        "Thruster Assembly.scdoc",
        b"PK\x03\x04spaceclaim",
        path="TP9/Thruster Assembly.scdoc",
        folder_files=["TP9/Thruster Assembly.scdoc", "TP9/thruster_assembly.step"],
        web_url="https://example.invalid/item",
    )
    catalog = processed.document.catalog

    assert processed.document.doc_kind == DocKind.CAD_REFERENCE and catalog["measurement"] is None
    assert catalog["references"] == ["TP9/thruster_assembly.step"] and catalog["web_url"].startswith(
        "https://"
    )
    assert "SpaceClaim document Thruster Assembly.scdoc" in processed.nodes[0].content
    assert _run("plan.dwg", b"AC1032....").document.catalog["cad_format"] == "dwg"


def test_broken_stl_is_a_hard_failure():
    pytest.importorskip("trimesh")
    processed = _run("broken.stl", b"solid x\nendsolid x\n")
    assert processed.flags[0].flag_type == FlagType.PARSE_FAILURE and processed.has_hard_flags


def test_can_handle():
    assert can_handle(b"PK\x03\x04", "a.zip") and can_handle(b"\x1f\x8b", "x.dat.gz")
    assert can_handle(b"solid", "part.STL") and can_handle(b"", "model.scdoc") and can_handle(b"", "a.dwg")
    assert not can_handle(b"PK\x03\x04", "report.docx")


def test_process_archive_rejects_non_archives():
    processed = process_archive(
        b"plain", blob_sha256="0" * 64, file_name="x.txt", folder=FOLDER, stores=Stores(lambda k, v: k)
    )
    assert processed.has_hard_flags
    assert process_cad  # the CAD entry point is public for the runner


# ---------------------------------------------------------------- real and web samples


def test_real_injector_zip():
    processed = _run("Injector.zip", _sample(SAMPLES / "X2" / "Good Condition" / "Injector.zip"))
    catalog = processed.document.catalog

    assert catalog["members"] == 27 and catalog["skipped"] == 2
    paths = {b.member_path for b in processed.derived_blobs}
    assert "Injector/Test_plan_creator.py" in paths and "Injector/Test_plan.tex" in paths
    assert catalog["routes"]["A2"] >= 10 and catalog["routes"].get("G", 0) == 0


def test_web_zip_with_junk_and_tar_bundle():
    zipped = _run("nested_public_project.zip", _sample(WEB / "zip" / "nested_public_project.zip"))
    assert {b.member_path for b in zipped.derived_blobs} == {
        "sample_project/docs/diagrams/pid_1.drawio",
        "sample_project/src/fsw/es/cfe_es_crc.c",
        "sample_project/src/matlab/dayofyear.m",
    }
    assert "sample_project/src/.DS_Store" in zipped.nodes[0].content

    bundle = _run("public_cad_bundle.tar.gz", _sample(WEB / "tar.gz" / "public_cad_bundle.tar.gz"))
    assert len(bundle.derived_blobs) == 3


def test_web_stl_extents_and_step_solids():
    pytest.importorskip("trimesh")
    stl = _run("CubeSat_top.stl", _sample(WEB / "stl" / "CubeSat_top.stl"))
    assert "bounding box 103.0 × 102.8 × 8.8 model units" in stl.nodes[0].content

    pytest.importorskip("cascadio")
    step = _run("red_cube_blue_cylinder.step", _sample(WEB / "step" / "red_cube_blue_cylinder.step"))
    assert "bounding box 25.0 × 10.0 × 10.0 mm" in step.nodes[0].content
    assert "2 solids (blue_cylinder, red_cube)" in step.nodes[0].content
