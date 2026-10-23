"""Golden suites built by verification/build_suites.py (every suite except telemetry).

Templates are committed without measured values or company file names (DECISIONS.md 2026-10-22);
local fragments and the built suites live in the git-ignored data/benchmark/.
"""

import base64
import html
import importlib.util
import json
import re
import tarfile
import typing
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

import numpy as np
import pytest
import yaml

from backend.benchmark.catalog import CASE_ID, CaseCreate, ExpectedBehavior
from backend.llm_engine.engine.analysis import ToolName
from backend.postgres.enums import BenchmarkCategory

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s5_build_suites", HERE / "verification/build_suites.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

TEMPLATES = bs.templates()
TOOLS = set(typing.get_args(ToolName))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def all_template_ids() -> list[str]:
    ids = []
    for path in [*TEMPLATES, bs.SUITES / "telemetry.template.yaml"]:
        ids += [c["case_id"] for c in load(path)["cases"]]
    return ids


def test_case_ids_unique_across_all_suites():
    ids = all_template_ids()
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_shape(path):
    template = load(path)
    assert path.name == f"{template['suite']}.template.yaml"
    for case in template["cases"]:
        assert set(case) <= bs.CASE_KEYS, case["case_id"]
        assert re.fullmatch(CASE_ID, case["case_id"])
        assert case["category"] in {m.value for m in BenchmarkCategory}
        assert set(case.get("expected_tools", [])) <= TOOLS, case["case_id"]
        assert set(case.get("expected_behavior", [])) <= {b.value for b in ExpectedBehavior}
        assert case.get("expected_behavior") or case.get("numeric_from") or case.get("local"), case["case_id"]
        if case.get("expected_behavior") == ["must_clarify"]:
            assert case.get("clarification_answer"), case["case_id"]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_holds_no_values_or_file_names(path):
    text = path.read_text(encoding="utf-8")
    assert "expected_numeric" not in text and "expected_citations" not in text
    assert not re.search(r"\w\.(pdf|docx|pptx|xlsx|dat|csv|tdms|tex|json|py)\b", text, re.IGNORECASE)


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_numeric_from_points_to_telemetry_cases(path):
    telemetry = {c["case_id"] for c in load(bs.SUITES / "telemetry.template.yaml")["cases"] if "method" in c}
    for case in load(path)["cases"]:
        if "numeric_from" in case:
            assert case["numeric_from"] in telemetry, case["case_id"]


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_built_suite_validates(path):
    template = load(path)
    built = bs.LOCAL / f"{template['suite']}.json"
    if not built.is_file():
        pytest.skip(f"{built.name} not built locally")
    suite = json.loads(built.read_text(encoding="utf-8"))
    assert [c["case_id"] for c in suite["cases"]] == [c["case_id"] for c in template["cases"]]
    for case, source in zip(suite["cases"], template["cases"], strict=True):
        CaseCreate.model_validate(case)
        if source.get("local"):
            assert set(case["spec"]) - {"expected_behavior", "expected_tools", "expected_numeric"}, case[
                "case_id"
            ]


SAMPLES = bs.REPO / "data" / "samples"


def _number_forms(value: float) -> set[str]:
    forms = {f"{value:.2f}", f"{value:.1f}"}
    if float(value).is_integer():
        forms.add(str(int(value)))
    else:
        forms.add(repr(float(value)))
    return forms | {f.replace(".", ",") for f in forms}  # decimal-comma documents (ECSS)


def _cited_cases():
    for path in TEMPLATES:
        template = load(path)
        built = bs.LOCAL / f"{template['suite']}.json"
        if not built.is_file():
            continue
        for case in json.loads(built.read_text(encoding="utf-8"))["cases"]:
            if case["spec"].get("expected_citations"):
                yield case


def _local_file(file_name: str) -> Path:
    """The local copy a citation means; data/benchmark/verify_paths.yaml settles shared names."""
    overrides_path = bs.LOCAL / "verify_paths.yaml"
    overrides = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) if overrides_path.is_file() else {}
    if file_name in (overrides or {}):
        return SAMPLES / overrides[file_name]
    matches = [p for p in SAMPLES.rglob(file_name) if p.is_file()]
    if not matches:
        pytest.skip(f"{file_name} not exported locally")
    assert len({p.stat().st_size for p in matches}) == 1, (
        f"ambiguous local file {file_name}; add it to verify_paths"
    )
    return matches[0]


def _xml_text(xml: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", xml)).split())


def _office_text(path: Path) -> str:
    """Text runs of a .docx, .pptx or .vsdx (each run kept whole, so "Col head 1" stays one phrase)."""
    with zipfile.ZipFile(path) as z:
        parts = [
            n
            for n in z.namelist()
            if re.match(r"(word/document|ppt/slides/slide\d+|visio/pages/page\d+)\.xml$", n)
        ]
        runs = []
        for name in parts:
            xml = z.read(name).decode("utf-8", "replace")
            runs += re.findall(r"<(?:w:t|a:t|Text)[^>]*>(.*?)</(?:w:t|a:t|Text)>", xml, re.S)
    return " | ".join(_xml_text(r) for r in runs)


def _drawio_text(path: Path) -> str:
    """Labels and styles of every page, compressed pages (base64 + deflate + URL-encoding) decoded."""
    root = ET.parse(path).getroot()
    pages = []
    for diagram in root.iter("diagram"):
        if len(diagram) == 0 and (diagram.text or "").strip():
            raw = zlib.decompress(base64.b64decode(diagram.text.strip()), -15).decode()
            pages.append(urllib.parse.unquote(raw))
        else:
            pages.append(ET.tostring(diagram, encoding="unicode"))
    return " ".join(
        f"{_xml_text(html.unescape(c.get('value') or ''))} {c.get('style') or ''}"
        for page in pages
        for c in ET.fromstring(page).iter("mxCell")
    )


def _stl_text(path: Path) -> str:
    """Recomputed axis-aligned extents of a binary STL (the adapter's measurement, done independently)."""
    data = path.read_bytes()
    count = int.from_bytes(data[80:84], "little")
    record = np.dtype([("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attr", "<u2")])
    vertices = np.frombuffer(data[84 : 84 + count * 50], dtype=record)["vertices"].reshape(-1, 3)
    extents = vertices.max(axis=0) - vertices.min(axis=0)
    return " ".join(f"{e:.1f} {e:.2f}" for e in extents)


def _tdms_text(path: Path) -> str:
    """Channel names, unit strings and maxima of a TDMS file."""
    from nptdms import TdmsFile

    tdms = TdmsFile.read(path)
    return " ".join(
        f"{c.name} {c.properties.get('unit_string', '')} {float(np.max(c[:])):.3f}"
        for group in tdms.groups()
        for c in group.channels()
    )


def _archive_text(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            return " ".join(z.namelist())
    with tarfile.open(path) as t:
        return " ".join(t.getnames())


def _cited_text(citation: dict) -> str:
    path = _local_file(citation["file_name"])
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = [reader.pages[citation["page"] - 1]] if citation.get("page") else reader.pages
        return " ".join(" ".join((p.extract_text() or "").split()) for p in pages)
    readers = {
        ".docx": _office_text,
        ".pptx": _office_text,
        ".vsdx": _office_text,
        ".drawio": _drawio_text,
        ".svg": lambda p: _xml_text(p.read_text(encoding="utf-8")),
        ".stl": _stl_text,
        ".tdms": _tdms_text,
        ".zip": _archive_text,
        ".gz": _archive_text,
    }
    if suffix in readers:
        return readers[suffix](path)
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("case", list(_cited_cases()), ids=lambda c: c["case_id"])
def test_cited_pages_contain_the_answer(case):
    """Golden answers are verified outside the pipeline: every expected number and entity must
    appear in the cited page (PDF text layer) or the cited source file of the local copy."""
    if not SAMPLES.is_dir():
        pytest.skip("data/samples/ not exported locally")
    joined = " ".join(_cited_text(c) for c in case["spec"]["expected_citations"]).casefold()
    if not joined.strip():
        # Image-only pages: no text layer to search; S5's visual reading must be on record.
        readings_path = bs.LOCAL / "visual_readings.yaml"
        readings = (
            yaml.safe_load(readings_path.read_text(encoding="utf-8")) if readings_path.is_file() else {}
        )
        assert (readings or {}).get(case["case_id"]), (
            f"{case['case_id']}: image-only citation without a recorded reading"
        )
        return
    for numeric in case["spec"].get("expected_numeric", []):
        assert any(f in joined for f in _number_forms(numeric["value"])), (case["case_id"], numeric["value"])
    for entity in case["spec"].get("expected_entities", []):
        assert entity.casefold() in joined, (case["case_id"], entity)
