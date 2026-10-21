"""Assembler: LaTeX masters and parts (S5 fixture two_latex_masters), orphans, PDF twins, JSON sets."""

from pathlib import Path

from backend.dispatcher.assembler import FileRef, assemble, load_section_file_sets
from backend.postgres.enums import DocumentSourceRole as R

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "a2_source" / "two_latex_masters"


def ref(path, kind=None):
    kind = kind or {"tex": "tex", "pdf": "pdf", "json": "json"}.get(path.rsplit(".", 1)[-1], "plain_text")
    return FileRef(path=path, blob_sha256=f"sha-{path}", kind=kind)


def texts(mapping):
    return lambda f: mapping.get(f.path, "")


def summary(plans):
    return {p.primary.path: ([(f.path, role) for f, role in p.parts], p.conflicts) for p in plans}


def test_s5_fixture_two_masters_become_two_documents_with_a_conflict_and_the_part_goes_to_main():
    files = [ref("report_main.tex"), ref("report_draft.tex"), ref("sections/results.tex")]
    plans = assemble(files, lambda f: (FIXTURE / f.path).read_text(encoding="utf-8"))
    got = summary(plans)
    assert set(got) == {"report_main.tex", "report_draft.tex"}
    assert got["report_main.tex"][0] == [("sections/results.tex", R.PART)]
    assert got["report_draft.tex"][0] == []
    assert all(conflicts == ["two masters in folder ."] for _, conflicts in got.values())


def test_includes_resolve_recursively_with_import_and_missing_ones_are_recorded():
    files = [ref("r/main.tex"), ref("r/ch/a.tex"), ref("r/ch/b.tex"), ref("r/fig/c.tex"), ref("r/main.pdf")]
    content = {
        "r/main.tex": (
            "\\documentclass{report}\n\\input{ch/a}\n\\import{fig/}{c}\n"
            "% \\input{commented}\n\\include{missing}"
        ),
        "r/ch/a.tex": "\\input{ch/b}",
    }
    (plan,) = assemble(files, texts(content))
    assert [(f.path, role) for f, role in plan.parts] == [
        ("r/ch/a.tex", R.PART),
        ("r/fig/c.tex", R.PART),
        ("r/ch/b.tex", R.PART),
        ("r/main.pdf", R.VISUAL_TWIN),
    ]
    assert plan.missing_includes == ["r/missing.tex"]
    assert plan.conflicts == []


def test_orphan_tex_files_are_assembled_per_folder_by_name_with_a_conflict():
    plans = assemble([ref("s/b.tex"), ref("s/a.tex")], texts({}))
    (plan,) = plans
    assert (plan.primary.path, [f.path for f, _ in plan.parts]) == ("s/a.tex", ["s/b.tex"])
    assert plan.conflicts == ["no master found in folder s, assembled by filename"]


def test_json_section_files_form_one_document_named_after_the_folder():
    sets = load_section_file_sets()
    files = [ref("T01/observations.json"), ref("T01/objectives.json"), ref("T01/other.json")]
    plans = assemble(files, texts({}), sets)
    got = summary(plans)
    assert got["T01/objectives.json"][0] == [("T01/observations.json", R.PART)]
    assert [p.title for p in plans if p.primary.path == "T01/objectives.json"] == ["T01"]
    assert got["T01/other.json"] == ([], [])


def test_a_lone_section_file_and_ordinary_files_are_single_documents():
    plans = assemble(
        [ref("x/objectives.json"), ref("x/run.dat", "telemetry_text")], texts({}), load_section_file_sets()
    )
    assert {p.primary.path for p in plans} == {"x/objectives.json", "x/run.dat"}
    assert all(p.parts == [] for p in plans)


def test_includes_relative_to_the_project_root_are_found_for_a_master_in_main_files():
    files = [
        ref("TP12/Main_Files/1.tex"),
        ref("TP12/Sections/Tables/Revision_History.tex"),
        ref("TP12/Sections/A.tex"),
    ]
    content = {
        "TP12/Main_Files/1.tex": (
            "\\documentclass{article}\n\\input{Sections/Tables/Revision_History.tex}\n\\input{Sections/A}"
        )
    }
    (plan,) = assemble(files, texts(content))
    assert [f.path for f, _ in plan.parts] == [
        "TP12/Sections/Tables/Revision_History.tex",
        "TP12/Sections/A.tex",
    ]
    assert (plan.missing_includes, plan.conflicts) == ([], [])


def test_tex_files_no_master_includes_are_reported_as_such_when_a_master_exists():
    content = {"p/main.tex": "\\documentclass{article}"}
    plans = assemble([ref("p/main.tex"), ref("p/Sections/unused.tex")], texts(content))
    orphan = next(p for p in plans if p.primary.path == "p/Sections/unused.tex")
    assert orphan.conflicts == ["not included by any master in folder p/Sections, assembled by filename"]
