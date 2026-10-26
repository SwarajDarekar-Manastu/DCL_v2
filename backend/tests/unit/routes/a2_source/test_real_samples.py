"""Route A2 on the real allowlist samples (git-ignored ``data/samples/``; skipped when not exported).

E4 is the Test Plan 12 report (master ``Test_plan.tex``, 21 section and table files, PDF twin); E3 holds the
Test Plan 7 project with the section JSON files the test-plan creator writes.
"""

import hashlib
import json

import pytest

from backend.dispatcher.assembler import FileRef, assemble, load_section_file_sets
from backend.postgres.enums import DocumentSourceRole, NodeType
from backend.routes.a2_source.route import SourceFile, process_json, process_latex
from backend.tests.unit.routes.a2_source.conftest import SAMPLES

E4 = SAMPLES / "E4" / "APU - Firing"
E3 = SAMPLES / "E3" / "APU-Firing"
KINDS = {".tex": "tex", ".pdf": "pdf", ".json": "json"}


def _plans(root):
    paths = [p for p in root.rglob("*") if p.is_file()]
    refs = [
        FileRef(
            str(p.relative_to(root)),
            hashlib.sha256(p.read_bytes()).hexdigest(),
            KINDS.get(p.suffix.lower(), "x"),
        )
        for p in paths
    ]
    plans = assemble(refs, lambda f: (root / f.path).read_text(errors="replace"), load_section_file_sets())
    return refs, plans


def _files(root, plan):
    files = [
        SourceFile(
            plan.primary.path,
            plan.primary.blob_sha256,
            (root / plan.primary.path).read_bytes(),
            DocumentSourceRole.PRIMARY,
        )
    ]
    files += [SourceFile(f.path, f.blob_sha256, (root / f.path).read_bytes(), role) for f, role in plan.parts]
    return files


@pytest.mark.skipif(not E4.exists(), reason="data/samples/E4 not exported locally")
def test_tp12_report_assembles_with_page_map(memory, folder):
    pytest.importorskip("pypdfium2")
    refs, plans = _plans(E4)
    plan = next(p for p in plans if p.primary.path == "Test_plan.tex")
    files = _files(E4, plan)
    assert any(f.role == DocumentSourceRole.VISUAL_TWIN for f in files)

    processed = process_latex(
        files,
        title=plan.title,
        folder=folder,
        stores=memory.stores(),
        folder_files=[r.path for r in refs],
        read_file=lambda p: (E4 / p).read_bytes() if (E4 / p).is_file() else None,
        conflicts=plan.conflicts,
    )

    assert processed.document.title == "Report - Test Campaign 1 - Test Plan 12"
    sections = {n.breadcrumb.split(" › ")[1] for n in processed.nodes if " › " in n.breadcrumb}
    for number, name in enumerate(
        [
            "Overview",
            "Objectives",
            "Test Setup",
            "Test Plan",
            "Procedure",
            "Emergency Procedures",
            "Prefiring Activities",
            "Observations - Test",
            "Observations - De-Integration",
            "Discussion",
            "Conclusions",
        ],
        start=1,
    ):
        assert f"{number} {name}" in sections
    assert {"A Integration Data Sheet", "B Catalyst Data Sheet"} <= sections
    text = "\n".join(n.content for n in processed.nodes)
    assert "Preheat the thruster according to the criterion mentioned in Table 3." in text
    assert "" not in text
    tables = [n for n in processed.nodes if n.node_type == NodeType.TABLE]
    assert "Table 7: Test Duration, Thruster Response and Throughput - Test 01" in [
        t.metadata["caption"] for t in tables
    ]
    assert "<td>Through put [grams]</td><td>433.81</td>" in text

    page_map = json.loads(memory.cir["page_map.json"])
    pages = [h["page_no"] for h in page_map["headings"]]
    assert processed.document.page_count == 45
    assert pages == sorted(pages)
    structure = json.loads(memory.cir["structure.json"])
    assert structure["missing_includes"] == []
    assert set(structure["unresolved_refs"]) <= {"cref:Apdx:B", "cref:P&ID"}  # undefined in the source too


@pytest.mark.skipif(not E4.exists(), reason="data/samples/E4 not exported locally")
def test_tp12_sections_land_on_their_twin_pages(memory, folder):
    pytest.importorskip("pypdfium2")
    refs, plans = _plans(E4)
    plan = next(p for p in plans if p.primary.path == "Test_plan.tex")
    processed = process_latex(
        _files(E4, plan),
        title=plan.title,
        folder=folder,
        stores=memory.stores(),
        folder_files=[r.path for r in refs],
        read_file=lambda p: (E4 / p).read_bytes() if (E4 / p).is_file() else None,
    )
    pages = {h["heading"]: h["page_no"] for h in json.loads(memory.cir["page_map.json"])["headings"]}
    assert pages["1 Overview"] == 6 and pages["3 Test Setup"] == 8
    overview = next(n for n in processed.nodes if n.breadcrumb.endswith("› 1 Overview"))
    assert overview.page_no == 6


@pytest.mark.skipif(not E3.exists(), reason="data/samples/E3 not exported locally")
def test_tp7_section_json_files(memory, folder):
    _, plans = _plans(E3)
    plan = next(p for p in plans if p.primary.path == "Sections/objectives.json")
    processed = process_json(_files(E3, plan), title=plan.title, folder=folder, stores=memory.stores())

    assert [p.path for p, _ in plan.parts] == ["Sections/conclusions.json"]
    assert processed.nodes and processed.flags == []
    assert "700 seconds cumulative firing time" in processed.nodes[0].content

    # one section per file with no test_id: its fields are read and its test comes from the folder
    single = next(p for p in plans if p.primary.path == "Sections/test_plan.json")
    read = process_json(_files(E3, single), title=single.title, folder=folder, stores=memory.stores())
    assert read.flags == []
    assert "content.text: This section outlines the test plan and procedures." in read.nodes[0].content
