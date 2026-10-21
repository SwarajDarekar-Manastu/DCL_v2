"""Type resolution: the file 03 §1.1 signatures, extension refinement of text, mismatch recording."""

import pickle
from pathlib import Path

import pytest

from backend.dispatcher.type_resolution import extension_of, resolve_type
from backend.postgres.enums import Route

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.mark.parametrize(
    ("head", "name", "zip_names", "kind", "route"),
    [
        (b"%PDF-1.7\n", "report.pdf", None, "pdf", Route.A1),
        (b"PK\x03\x04", "r.docx", ["[Content_Types].xml", "word/document.xml"], "docx", Route.A1),
        (b"PK\x03\x04", "s.pptx", ["[Content_Types].xml", "ppt/slides/slide1.xml"], "pptx", Route.A1),
        (b"PK\x03\x04", "FMEA.xlsx", ["[Content_Types].xml", "xl/workbook.xml"], "xlsx", Route.C),
        (b"PK\x03\x04", "model.wbpz", ["dp0/SYS/MECH/file.mechdat", "model.wbpj"], "wbpz", Route.G),
        (b"PK\x03\x04", "bundle.zip", ["a.py", "b.csv"], "zip", Route.G),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "old.doc", None, "doc", Route.A1),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "old.xls", None, "xls", Route.C),
        (b"\x93NUMPY\x01\x00", "arr.npy", None, "npy", Route.C),
        (b"\x80\x04\x95", "T03.plotdata", None, "pickle", Route.C),
        (b"\x89HDF\r\n\x1a\n", "t02_00", None, "hdf5", Route.C),
        (b"TDSm\x00\x00", "run.tdms", None, "tdms", Route.C),
        (b'<?xml version="1.0"?>\n<mxfile host="drawio">', "Rev C.drawio", None, "drawio", Route.E),
        (b'<?xml version="1.0"?>\n<xs:schema xmlns:xs="x">', "ECSS-M-50B.xsd", None, "xsd", Route.E),
        (b"\x1f\x8b\x08\x00", "11bar_10sec.dat.gz", None, "gzip", Route.G),
        (b"\x00\x00\x00\x18ftypheic\x00\x00", "IMG_1.heic", None, "heic", Route.D),
        (b"\xff\xd8\xff\xe0", "photo.jpg", None, "jpeg", Route.D),
        (b"\x89PNG\r\n\x1a\n", "plot.png", None, "png", Route.D),
        (b"\x00\x00\x00\x20ftypisom", "firing.mp4", None, "mp4", Route.F),
        (b"\x00\x00\x00\x14ftypqt  ", "firing.mov", None, "mov", Route.F),
    ],
)
def test_signatures_of_file_03_section_1_1(head, name, zip_names, kind, route):
    resolved = resolve_type(head, name, zip_names)
    assert (resolved.kind, resolved.route, resolved.by, resolved.ext_mismatch) == (
        kind,
        route,
        "magic",
        False,
    )


@pytest.mark.parametrize(
    ("name", "kind", "route"),
    [
        ("run.csv", "delimited_text", Route.C),
        ("TP07_T01.dat", "telemetry_text", Route.C),
        ("TP07_T02.dat_fail", "telemetry_text", Route.C),
        ("T01.cfg", "telemetry_text", Route.C),
        ("main.tex", "tex", Route.A2),
        ("nozzle_calc.py", "python", Route.B),
        ("README.md", "markdown", Route.B),
        ("objectives.json", "json", Route.A2),
    ],
)
def test_text_is_refined_by_its_extension_without_a_mismatch(name, kind, route):
    head = b"time,pt_101,tc_bed\n0.000,1.2,300.1\n0.001,1.3,300.2\n0.002,1.4,300.3\n"
    resolved = resolve_type(head, name)
    assert (resolved.kind, resolved.route, resolved.ext_mismatch) == (kind, route, False)


def test_extensionless_text_goes_to_the_route_c_mystery_sniffer():
    resolved = resolve_type(b"0.0 1.2 3.4\n0.1 1.3 3.5\n", "t02_00")
    assert (resolved.kind, resolved.route, resolved.ext_mismatch) == ("unknown_text", Route.C, False)


def test_an_xlsx_that_is_really_csv_is_csv_and_the_mismatch_is_recorded():
    resolved = resolve_type(b"a;b;c\n1;2;3\n4;5;6\n7;8;9\n", "export.xlsx")
    assert (resolved.kind, resolved.route, resolved.ext_mismatch) == ("delimited_text", Route.C, True)


def test_s5_fixture_pdf_that_is_html_has_no_route_and_a_recorded_mismatch():
    head = (FIXTURES / "dispatcher" / "pdf_is_html" / "Test_Report_12.pdf").read_bytes()
    resolved = resolve_type(head, "Test_Report_12.pdf")
    assert (resolved.kind, resolved.mime, resolved.route, resolved.ext_mismatch) == (
        "html",
        "text/html",
        None,
        True,
    )


def test_s5_malicious_pickle_is_named_from_its_bytes_without_loading_it(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("pickle must never be loaded")

    monkeypatch.setattr(pickle, "load", refuse)
    monkeypatch.setattr(pickle, "loads", refuse)
    head = (FIXTURES / "c_telemetry" / "malicious_pickle" / "T03.plotdata").read_bytes()[:4096]
    resolved = resolve_type(head, "T03.plotdata")
    assert (resolved.kind, resolved.route) == ("pickle", Route.C)


def test_unknown_binary_has_no_route_and_a_libmagic_mime():
    resolved = resolve_type(b"\x01\x02\x03\x04\xfe\xff" * 50, "mystery.bin2")
    assert resolved.route is None
    assert resolved.mime


def test_scdoc_is_trusted_by_extension_because_it_has_no_signature():
    resolved = resolve_type(b"\x05\x06\x07\x08" * 10, "part.scdoc")
    assert (resolved.kind, resolved.route, resolved.by) == ("scdoc", Route.G, "extension")


def test_a_pdf_extension_on_unknown_bytes_is_a_mismatch():
    resolved = resolve_type(b"\x01\x02\x03\xfe" * 20, "broken.pdf")
    assert (resolved.route, resolved.ext_mismatch) == (None, True)


def test_extension_of():
    assert extension_of("TP07.DAT_FAIL") == ".dat_fail"
    assert extension_of("t02_00") == ""
    assert extension_of("a.tar.gz") == ".gz"
