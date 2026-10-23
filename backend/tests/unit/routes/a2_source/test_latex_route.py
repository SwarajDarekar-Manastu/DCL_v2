"""Route A2 LaTeX on synthetic projects: the edge cases of file 03 §A2.2 and the A2 flags."""

import io
import json

import pytest

from backend.dispatcher.contract import ProcessedDocument
from backend.postgres.enums import DocumentSourceRole, FlagSeverity, FlagType, NodeSource, NodeType
from backend.routes.a2_source import latex
from backend.routes.a2_source.route import process_latex, unitless_values
from backend.tests.unit.routes.a2_source.conftest import FakeVision, primary, source

PREAMBLE = r"""\documentclass{article}
\usepackage{siunitx}
\newcommand{\Pc}{P_c}
\newcommand{\thruster}[1]{APU thruster #1}
\NewDocumentCommand{\pair}{O{left} m}{#1 and #2}
\graphicspath{{figures/}}
\title{Hot Fire Report TP12}
"""

MASTER = (
    PREAMBLE
    + r"""\begin{document}
\maketitle
\input{sections/intro}
\include{sections/results}
% \input{sections/old_draft}
\input{sections/missing_part}
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
"""
)

INTRO = r"""\section{Introduction}\label{sec:intro}
The chamber pressure $\Pc$ of the \thruster{4} was set to \SI{300}{\bar} and the flow to
\SI{2.5}{\kilo\pascal\per\second}. See \Cref{tab:results} and \Cref{fig:pc} for details; the model
follows \cite{smith2020}. Both \pair{inlet} were checked.

\begin{equation}
F = \dot m \, v_e + (p_e - p_a) A_e \label{eq:thrust}
\end{equation}
Thrust follows \eqref{eq:thrust}.

\begin{itemize}
\item first step
\item second step
\end{itemize}

\begin{lstlisting}[language=Python]
rate = 100 % 7  # modulo stays
\end{lstlisting}
"""

RESULTS = r"""\section{Results}
\subsection{Test 01}
\begin{table}[H]
\centering
\caption{Test output parameters}\label{tab:results}
\begin{tabular}{|l|c|c|}
\hline
\textbf{Parameter} & \textbf{Valve} & \textbf{Mean} \\
\hline
Chamber pressure [barg] & 5.65 & 5.73 \\
C\textsubscript{F} & 1.05 & 1.07 \\
\multicolumn{2}{|c|}{Spanning note} & 3 \\
\hline
\end{tabular}
\end{table}

\begin{figure}[H]
\centering
\includegraphics[width=\textwidth]{plots/pc.png}
\caption{Chamber pressure vs time}\label{fig:pc}
\end{figure}
As \Cref{sec:intro} explains, \Cref{fig:pc} shows the rise.
"""

BIB = r"""@article{smith2020,
  author = {Smith, John and Doe, Jane and Roe, Richard},
  title = {Catalyst bed {HTP} decomposition},
  journal = {Journal of Propulsion},
  year = 2020,
}
@string{jp = "Journal"}
"""

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea7"
    "d6a4b40000000049454e44ae426082"
)


def _project(**overrides):
    texts = {"report.tex": MASTER, "sections/intro.tex": INTRO, "sections/results.tex": RESULTS, **overrides}
    files = [primary("report.tex", texts.pop("report.tex"))] + [source(p, t) for p, t in texts.items()]
    siblings = {"refs.bib": BIB.encode(), "figures/plots/pc.png": PNG}
    return files, siblings


def _run(memory, folder, files, siblings=None, **kwargs):
    siblings = siblings or {}
    folder_files = [f.path for f in files] + list(siblings)
    processed = process_latex(
        files,
        title="report",
        folder=folder,
        stores=memory.stores(),
        folder_files=folder_files,
        read_file=siblings.get,
        **kwargs,
    )
    assert ProcessedDocument.model_validate_json(processed.model_dump_json()) == processed
    return processed


def _text(processed) -> str:
    return "\n".join(n.content for n in processed.nodes)


def test_multi_file_project_assembles_into_one_document(memory, folder):
    files, siblings = _project()
    processed = _run(memory, folder, files, siblings)

    assert processed.document.title == "Hot Fire Report TP12"
    crumbs = {n.breadcrumb for n in processed.nodes}
    assert "Hot Fire Report TP12 › 1 Introduction" in crumbs
    assert "Hot Fire Report TP12 › 2 Results › 2.1 Test 01" in crumbs
    structure = json.loads(memory.cir["structure.json"])
    assert structure["included"] == ["sections/intro.tex", "sections/results.tex"]
    assert structure["missing_includes"] == ["sections/missing_part"]
    assert "old_draft" not in json.dumps(structure)
    assert processed.route == "A2"
    assert processed.cir_uri == f"s3://dcl-cir/{files[0].blob_sha256}/A2/v1/"


def test_refs_cites_and_macros_resolve_to_readable_text(memory, folder):
    files, siblings = _project()
    text = _text(_run(memory, folder, files, siblings))

    assert "The chamber pressure $P_c$ of the APU thruster 4 was set to 300 bar" in text
    assert "2.5 kPa/s" in text
    assert "See Table 1 and Figure 1 for details" in text
    assert "[Smith et al. 2020, Catalyst bed HTP decomposition]" in text
    assert "Both left and inlet were checked." in text
    assert "Thrust follows (1)." in text
    assert "As Section 1 explains, Figure 1 shows the rise." in text
    assert "" not in text


def test_equations_lists_and_code(memory, folder):
    files, siblings = _project()
    processed = _run(memory, folder, files, siblings)
    contents = [n.content for n in processed.nodes]

    assert any(c.startswith("$$F = \\dot m") and c.endswith("$$ (1)") for c in contents)
    assert "- first step" in contents and "- second step" in contents
    code = next(c for c in contents if c.startswith("```"))
    assert "rate = 100 % 7  # modulo stays" in code


def test_table_becomes_html_with_header_and_spans(memory, folder):
    files, siblings = _project()
    processed = _run(memory, folder, files, siblings)
    table = next(n for n in processed.nodes if n.node_type == NodeType.TABLE)

    assert table.metadata["caption"] == "Table 1: Test output parameters"
    assert "<thead><tr><th>Parameter</th><th>Valve</th><th>Mean</th></tr></thead>" in table.content
    assert '<td colspan="2">Spanning note</td>' in table.content
    assert "<td>C_F</td>" in table.content


def test_figure_links_the_image_and_digitizes_a_plot(memory, folder):
    files, siblings = _project()
    vision = FakeVision()
    processed = _run(memory, folder, files, siblings, vision=vision, cloud_allowed=True)
    figure = next(n for n in processed.nodes if n.node_type == NodeType.FIGURE)

    assert figure.content.startswith("Figure 1: Chamber pressure vs time")
    assert "Chamber pressure [bar]" in figure.content
    assert figure.source == NodeSource.VLM and figure.confidence == 0.8
    assert vision.calls == ["classify_image", "digitize_plot"]
    asset = next(a for a in processed.assets if a.ref == figure.asset_ref)
    assert asset.minio_uri == f"s3://dcl-assets/figures/{files[0].blob_sha256}/0000.png"
    assert asset.width == 1 and asset.height == 1
    assert figure.metadata["image_path"] == "figures/plots/pc.png"
    assert "As Section 1 explains, Figure 1 shows the rise." in figure.metadata["referenced_by"]


def test_no_vision_call_without_cloud_permission(memory, folder):
    files, siblings = _project()
    vision = FakeVision()
    processed = _run(memory, folder, files, siblings, vision=vision, cloud_allowed=False)

    assert vision.calls == []
    assert next(n for n in processed.nodes if n.node_type == NodeType.FIGURE).source == NodeSource.PRINTED


def test_bibliography_entries_become_reference_mentions(memory, folder):
    files, siblings = _project()
    processed = _run(memory, folder, files, siblings)
    references = [m.surface for m in processed.mentions if m.kind == "reference"]
    quantities = [m.surface for m in processed.mentions if m.kind == "quantity"]

    assert references == [
        "Smith, John and Doe, Jane and Roe, Richard. (2020). "
        "Catalyst bed HTP decomposition. Journal of Propulsion"
    ]
    assert quantities == ["300 bar", "2.5 kPa/s"]
    assert "Smith, John" not in _text(processed)


def test_every_node_has_a_line_locator_and_a_source_map_entry(memory, folder):
    files, siblings = _project()
    processed = _run(memory, folder, files, siblings)
    markdown = memory.cir["assembled.md"].decode().split("\n")
    source_map = json.loads(memory.cir["source_map.json"])

    assert len(source_map) == len(markdown)
    for node in processed.nodes:
        assert node.line_start is not None and node.line_end >= node.line_start
        assert source_map[node.line_start - 1] == node.metadata["source"]
    intro = next(n for n in processed.nodes if "chamber pressure $P_c$" in n.content)
    assert intro.metadata["source"] == "sections/intro.tex:2"
    assert markdown[intro.line_start - 1].startswith("The chamber pressure $P_c$")


def test_unit_less_numeric_table_in_results_is_a_soft_unit_flag(memory, folder):
    files, siblings = _project()
    processed = _run(memory, folder, files, siblings)
    flags = [f for f in processed.flags if f.flag_type == FlagType.UNIT_AMBIGUITY]

    assert len(flags) == 1 and flags[0].severity == FlagSeverity.SOFT
    assert flags[0].evidence.value_raw == "1.05"
    assert "C_F" in flags[0].evidence.context


def test_unitless_values_ignores_id_columns_and_unit_headers():
    grid = [["Test No.", "Pressure [bar]", "Ratio"], ["1", "5.6", "0.9"], ["2", "5.8", "1.1"]]
    assert unitless_values(grid, 1) == [("0.9", "Ratio"), ("1.1", "Ratio")]
    assert unitless_values([["T90 [s]", "0.21"], ["Mass [g]", "433.8"]], 0) == []


def test_two_masters_and_orphans_raise_soft_conflicts(memory, folder):
    orphans = [
        primary("Sections/a_overview.tex", r"\section{Overview} Text A."),
        source("Sections/b_results.tex", r"\section{Results} Text B."),
    ]
    processed = _run(
        memory, folder, orphans, conflicts=["no master found in folder Sections, assembled by filename"]
    )

    assert [n.content for n in processed.nodes] == ["Text A.", "Text B."]
    assert [n.breadcrumb.split(" › ")[-1] for n in processed.nodes] == ["1 Overview", "2 Results"]
    conflict = next(f for f in processed.flags if f.flag_type == FlagType.CONFLICT)
    assert conflict.severity == FlagSeverity.SOFT
    assert conflict.evidence.subject.startswith("no master found")


def test_secret_in_the_source_is_a_hard_sensitive_flag(memory, folder):
    files, siblings = _project(**{"sections/intro.tex": INTRO + '\npassword = "hunter2-very-secret"\n'})
    processed = _run(memory, folder, files, siblings)
    flag = next(f for f in processed.flags if f.flag_type == FlagType.SENSITIVE_CONTENT)

    assert flag.severity == FlagSeverity.HARD and processed.has_hard_flags
    assert "hunter2-very-secret" not in flag.evidence.redacted_preview


def test_parse_failure_only_when_full_walk_and_every_section_fail(memory, folder, monkeypatch):
    files, siblings = _project()

    def boom(*_args, **_kwargs):
        raise RuntimeError("walker crashed")

    monkeypatch.setattr(latex.Walker, "run", boom)
    partial = _run(memory, folder, files, siblings)
    assert not any(f.flag_type == FlagType.PARSE_FAILURE for f in partial.flags)
    assert "300 bar" in _text(partial)

    monkeypatch.setattr(latex.Walker, "run_isolated", boom)
    failed = _run(memory, folder, files, siblings)
    flag = next(f for f in failed.flags if f.flag_type == FlagType.PARSE_FAILURE)
    assert flag.severity == FlagSeverity.HARD and failed.nodes == []


def test_include_cycle_is_guarded(memory, folder):
    files = [
        primary("main.tex", "\\documentclass{article}\\begin{document}\\input{a}\\end{document}"),
        source("a.tex", "Alpha text. \\input{b}"),
        source("b.tex", "Beta text. \\input{a}"),
    ]
    processed = _run(memory, folder, files)

    assert _text(processed) == "Alpha text. Beta text."
    assert json.loads(memory.cir["structure.json"])["missing_includes"] == ["a (include cycle)"]


def test_master_in_subfolder_includes_from_the_project_root(memory, folder):
    files = [
        primary(
            "Main_Files/1.tex", "\\documentclass{article}\\begin{document}\\input{Sections/x}\\end{document}"
        ),
        source("Sections/x.tex", "\\section{Overview}Root-relative include."),
    ]
    assert _text(_run(memory, folder, files)) == "Root-relative include."


def test_latin1_source_and_comments(memory, folder):
    body = (
        "\\documentclass{article}\\begin{document}Temperatur 300 \\% über Grenze % comment\n\\end{document}"
    )
    files = [primary("de.tex", body.encode("latin-1"))]
    assert _text(_run(memory, folder, files)) == "Temperatur 300 % über Grenze"


def test_longtable_keeps_the_first_head_and_drops_repeats(memory, folder):
    table = r"""\documentclass{article}\begin{document}
\begin{longtable}{ll}
\caption{Channels}\label{tab:ch} \\
Name & Unit \\ \endfirsthead
Name & Unit \\ \endhead
Foot & row \\ \endfoot
PT-101 & bar \\
TC-1 & degC \\
\end{longtable}
\end{document}"""
    processed = _run(memory, folder, [primary("t.tex", table)])
    node = next(n for n in processed.nodes if n.node_type == NodeType.TABLE)

    assert node.metadata["caption"] == "Table 1: Channels"
    assert node.content.count("<tr>") == 3
    assert "<thead><tr><th>Name</th><th>Unit</th></tr></thead>" in node.content
    assert "Foot" not in node.content


def test_twin_gives_pages_renders_and_page_map(memory, folder):
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    pytest.importorskip("pikepdf")
    buffer = io.BytesIO()
    canvas = reportlab.Canvas(buffer)
    for lines in (
        ["Hot Fire Report TP12"],
        ["1. Introduction", "The chamber pressure"],
        ["2. Results", "2.1 Test 01", "Table 1"],
    ):
        for i, line in enumerate(lines):
            canvas.drawString(72, 750 - 20 * i, line)
        canvas.showPage()
    canvas.save()
    files, siblings = _project()
    twin = source("report.pdf", buffer.getvalue(), DocumentSourceRole.VISUAL_TWIN)
    processed = _run(memory, folder, [*files, twin], siblings)

    page_map = json.loads(memory.cir["page_map.json"])
    assert [h["page_no"] for h in page_map["headings"]] == [2, 3, 3]
    intro = next(n for n in processed.nodes if "chamber pressure $P_c$" in n.content)
    assert intro.page_no == 2 and intro.line_start is not None
    assert next(n for n in processed.nodes if n.node_type == NodeType.TABLE).page_no == 3
    renders = [a for a in processed.assets if a.kind == "page_render"]
    assert [a.minio_uri for a in renders] == [
        f"s3://dcl-assets/pages/{twin.blob_sha256}/{p:04d}.png" for p in (1, 2, 3)
    ]
    assert processed.document.page_count == 3


def test_unit_text_for_siunitx():
    assert latex.unit_text(r"\kilo\pascal\per\second") == "kPa/s"
    assert latex.unit_text(r"\degreeCelsius") == "°C"
    assert latex.unit_text(r"\newton\meter") == "N·m"
    assert latex.unit_text("bar") == "bar"
