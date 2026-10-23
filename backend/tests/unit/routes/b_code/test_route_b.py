"""Route B (file 03 §6) on synthetic sources and the real samples (skipped without ``data/samples``)."""

import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_python")  # parse dependency group

from backend.dispatcher.contract import ProcessedDocument  # noqa: E402
from backend.dispatcher.folder_context import FolderContext  # noqa: E402
from backend.indexing.anchors import make_anchor  # noqa: E402
from backend.indexing.chunker import chunk_document  # noqa: E402
from backend.postgres.enums import DocKind, FlagSeverity, FlagType, NodeType  # noqa: E402
from backend.routes.b_code.route import Stores, can_handle, process_code, split_symbol  # noqa: E402
from backend.routes.b_code.symbols import MAX_SYMBOL_CHARS, Symbol, unit_from_name  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[5] / "data" / "samples"
FOLDER = FolderContext(
    root_name="APU", breadcrumb=["APU", "Tools"], path_cached="APU/Tools", test_plan_id="TP7"
)

NOZZLE = '''#!/usr/bin/env python3
"""Nozzle sizing helpers for the APU."""
import numpy as np
from scipy.optimize import brentq
from dataclasses import dataclass

P_ATM_BAR = 1.01325
MAX_CHAMBER_PSI = 300
GAMMA = 1.4


@dataclass
class Propellant:
    name: str
    density_kgm3: float = 1400.0


class NozzleSizer:
    """Sizes a convergent-divergent nozzle."""

    design = "conical"

    def __init__(self, throat_mm, chamber_bar=10.0):
        self.throat_mm = throat_mm
        self.chamber_bar = chamber_bar

    def expansion_ratio(self, exit_pressure_bar: float) -> float:
        """Area ratio for the given exit pressure.

        exit_pressure_bar (bar)
        """
        # TODO: validate against CEA
        return brentq(lambda m: m - exit_pressure_bar, 0.1, 10.0)


def validate_pressure_columns(df, limit_psi=MAX_CHAMBER_PSI):
    return df[df.p < limit_psi]


if __name__ == "__main__":
    print(NozzleSizer(3).expansion_ratio(P_ATM_BAR))
'''


def _run(name: str, data: bytes | str, cir=None) -> ProcessedDocument:
    data = data.encode() if isinstance(data, str) else data
    cir = {} if cir is None else cir
    processed = process_code(
        data,
        blob_sha256=hashlib.sha256(data).hexdigest(),
        file_name=name,
        folder=FOLDER,
        stores=Stores(put_cir=lambda key, payload: cir.setdefault(key, payload) and key),
    )
    assert ProcessedDocument.model_validate_json(processed.model_dump_json()) == processed
    for node in chunk_document(processed, count_tokens=lambda texts: [len(t) // 4 + 1 for t in texts]):
        make_anchor("00000000-0000-0000-0000-000000000001", node)
    return processed


def _by_name(processed):
    return {n.metadata.get("qualname"): n for n in processed.nodes if n.node_type == NodeType.CODE_SYMBOL}


def test_python_module_header_symbols_and_context_headers():
    cir = {}
    processed = _run("nozzle_calc.py", NOZZLE, cir)
    header = processed.nodes[0]
    symbols = _by_name(processed)

    assert header.node_type == NodeType.MODULE_HEADER
    assert header.content.startswith(
        "# File: nozzle_calc.py | Module: nozzle_calc | Imports: numpy, scipy, dataclasses"
    )
    assert "Nozzle sizing helpers for the APU." in header.content
    assert "MAX_CHAMBER_PSI = 300  [psi]" in header.content
    assert "Dataclasses: Propellant(name: str, density_kgm3: float)" in header.content
    assert {"NozzleSizer", "NozzleSizer.__init__", "NozzleSizer.expansion_ratio", "Propellant"} <= set(
        symbols
    )
    assert "validate_pressure_columns" in symbols
    assert processed.document.doc_kind == DocKind.CODE
    assert json.loads(cir["ast.json"])["imports"][0] == "import numpy as np"


def test_methods_carry_their_class_preamble():
    method = _by_name(_run("nozzle_calc.py", NOZZLE))["NozzleSizer.expansion_ratio"]

    assert method.content.splitlines()[0].endswith(
        "| Class: NozzleSizer | Imports: numpy, scipy, dataclasses"
    )
    assert "class NozzleSizer:" in method.content
    assert '"""Sizes a convergent-divergent nozzle."""' in method.content
    assert 'design = "conical"' in method.content
    assert "# __init__: self.chamber_bar = chamber_bar" in method.content
    assert method.parent_ref == "sym:NozzleSizer"
    assert method.breadcrumb == "nozzle_calc.py › NozzleSizer › expansion_ratio"
    assert method.metadata["params"] == [{"name": "exit_pressure_bar", "annotation": "float", "unit": "bar"}]
    assert method.metadata["calls"] == ["brentq"]
    assert (method.line_start, method.line_end) == (27, 33)


def test_units_mentions_annotations_and_script_body():
    processed = _run("nozzle_calc.py", NOZZLE)
    symbols = _by_name(processed)

    assert {(m.kind, m.surface) for m in processed.mentions} >= {
        ("quantity", "1.01325 bar"),
        ("quantity", "300 psi"),
        ("annotation", "TODO: validate against CEA"),
    }
    todo = next(m for m in processed.mentions if m.kind == "annotation")
    assert todo.node_ref == "sym:NozzleSizer.expansion_ratio"
    init = symbols["NozzleSizer.__init__"]
    assert {"name": "chamber_bar", "default": "10.0", "unit": "bar"} in init.metadata["params"]
    validate = symbols["validate_pressure_columns"]
    assert validate.metadata["params"][1] == {
        "name": "limit_psi",
        "default": "MAX_CHAMBER_PSI",
        "unit": "psi",
    }
    scripts = [n for n in processed.nodes if n.breadcrumb == "nozzle_calc.py › script"]
    assert [(n.line_start, n.line_end) for n in scripts] == [(7, 9), (40, 41)]
    assert 'if __name__ == "__main__":' in scripts[1].content
    assert [h.key for h in processed.unit_hashes][:3] == ["<script lines 7-9>", "Propellant", "NozzleSizer"]


def test_hard_coded_credentials_are_hard_flags():
    processed = _run("upload.py", 'API_KEY = "sk-live-0123456789abcdef"\nprint(API_KEY)\n')
    flag = processed.flags[0]

    assert flag.flag_type == FlagType.SENSITIVE_CONTENT and flag.severity == FlagSeverity.HARD
    assert flag.anchor.line == 1 and "0123456789abcdef" not in flag.evidence.redacted_preview
    assert processed.has_hard_flags


def test_syntax_error_is_soft_and_indexed_as_text():
    processed = _run("broken.py", "def f(:\n    return 1\nx = [1, 2\n")
    flag = processed.flags[0]

    assert flag.flag_type == FlagType.PARSE_FAILURE and flag.severity == FlagSeverity.SOFT
    assert "syntax errors at lines 1" in flag.evidence.error
    assert [n.node_type for n in processed.nodes] == [NodeType.CHILD]
    assert processed.nodes[0].content.startswith("def f(:")


def test_long_function_is_split_with_the_signature_repeated():
    body = "\n".join(f"    value_{i} = compute({i}) + offset  # step {i}" for i in range(400))
    source = f"def long_one(offset):\n{body}\n    return value_399\n"
    parts = [n for n in _run("long.py", source).nodes if n.node_type == NodeType.CODE_SYMBOL]

    assert len(parts) >= 3
    assert all(len(p.content) < 1.6 * MAX_SYMBOL_CHARS + 400 for p in parts)
    assert "# … part 2/" in parts[1].content and "def long_one(offset)" in parts[1].content
    assert parts[1].metadata["part"].startswith("2/")
    assert parts[0].line_start == 1 and parts[-1].line_end == 402
    assert [p.line_start for p in parts[1:]] == [p.line_end + 1 for p in parts[:-1]]


def test_split_symbol_keeps_a_short_symbol_whole():
    symbol = Symbol("f", "f", "function", 3, 4, "def f():\n    pass")
    assert split_symbol(symbol) == [(3, 4, "def f():\n    pass")]


def test_generated_qt_file_is_tagged_and_windows_newlines_keep_lines():
    source = (
        "# Form implementation generated from reading ui file\r\n"
        "# Created by: PyQt5 UI code generator 5.15\r\n\r\n"
        "class Ui_Main(object):\r\n    def setupUi(self, Main):\r\n        pass\r\n"
    )
    processed = _run("ui_main.py", source)

    assert processed.document.catalog["generated"] is True
    assert _by_name(processed)["Ui_Main.setupUi"].line_start == 5


def test_c_functions_doc_comments_and_defines():
    source = """/* CRC helpers */
#include <stdint.h>
#define MAX_RATE_HZ 1000

/** Computes CRC-16/ARC over a buffer. */
uint16_t crc16(const uint8_t *data, size_t length_bytes)
{
    return table_lookup(data, length_bytes);
}

typedef struct { int pressure_kpa; } Sample;
"""
    processed = _run("crc.c", source)
    symbols = _by_name(processed)
    crc = symbols["crc16"]

    assert (
        "Imports: stdint.h" in processed.nodes[0].content
        and "MAX_RATE_HZ = 1000  [Hz]" in processed.nodes[0].content
    )
    assert crc.metadata["docstring"] == "Computes CRC-16/ARC over a buffer."
    assert crc.metadata["params"] == [
        {"name": "data", "annotation": "uint8_t"},
        {"name": "length_bytes", "annotation": "size_t"},
    ]
    assert crc.metadata["calls"] == ["table_lookup"]
    assert symbols["Sample"].metadata["symbol_kind"] == "type"


def test_matlab_classdef_methods_carry_the_class():
    source = """classdef Nozzle < handle
  % NOZZLE sizing
  properties
    throat_mm = 3
  end
  methods
    function a = area(obj, scale_pct)
      % AREA throat area
      a = pi*(obj.throat_mm/2)^2 * scale_pct / 100;
    end
  end
end
"""
    area = _by_name(_run("Nozzle.m", source))["Nozzle.area"]

    assert area.metadata["docstring"] == "AREA throat area"
    assert area.metadata["params"] == [{"name": "scale_pct", "unit": "%"}]
    assert "throat_mm = 3" in area.content and area.breadcrumb == "Nozzle.m › Nozzle › area"


def test_markdown_text_bat_and_requirements():
    markdown = "# Tools\n\nIntro text.\n\n## Usage\n\n```bash\n# not a heading\nrun.bat\n```\n\nSee docs.\n"
    md = _run("README.md", markdown)
    assert [(n.breadcrumb, n.line_start, n.line_end) for n in md.nodes] == [
        ("README.md › Tools", 3, 3),
        ("README.md › Tools › Usage", 7, 10),
        ("README.md › Tools › Usage", 12, 12),
    ]
    assert md.document.doc_kind == DocKind.TOOLING_DOC

    bat = _run("run.bat", "\n".join(f"echo {i}" for i in range(90)))
    assert [(n.line_start, n.line_end) for n in bat.nodes] == [(1, 40), (41, 80), (81, 90)]

    requirements = "numpy==2.2.3\r\npandas>=2.0  # data\r\n-e .\r\n".encode("utf-16")
    req = _run("requirements.txt", requirements)
    assert [m.surface for m in req.mentions] == ["numpy==2.2.3", "pandas>=2.0"]
    assert can_handle(requirements[:64], "requirements.txt")
    assert not can_handle(b"\x00\x01\x02", "blob.txt")


def test_notebook_cells_become_nodes_without_outputs():
    notebook = {
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": ["# Run\n", "Press `Shift-Enter` to run."]},
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [{"output_type": "stream", "text": ["SECRET OUTPUT\n"]}],
                "source": ["a = 10\n", "print(a)"],
            },
        ],
        "metadata": {"kernelspec": {"language": "python", "name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    processed = _run("demo.ipynb", json.dumps(notebook, indent=1))

    assert [n.node_type for n in processed.nodes] == [NodeType.CHILD, NodeType.CODE_SYMBOL]
    assert (
        processed.nodes[0].content == "Press `Shift-Enter` to run."
        and processed.nodes[0].breadcrumb == "demo.ipynb › Run"
    )
    assert processed.nodes[1].content == "# Notebook: demo.ipynb | Cell 2 | Kernel: python\na = 10\nprint(a)"
    assert "SECRET OUTPUT" not in "".join(n.content for n in processed.nodes)
    assert processed.nodes[1].line_start > processed.nodes[0].line_start


def test_unit_suffixes():
    assert unit_from_name("P_ATM_BAR") == "bar"
    assert unit_from_name("flow_gs") == "g/s"
    assert unit_from_name("bar") is None and unit_from_name("data") is None


# ---------------------------------------------------------------- real samples

CREATOR = SAMPLES / "E1" / "29122025 - Injector 10 Cold flow test" / "Test_plan_creator.py"
WEB = SAMPLES / "web"


@pytest.mark.skipif(not CREATOR.exists(), reason="data/samples not exported locally")
def test_test_plan_creator_every_function_is_retrievable_by_name():
    processed = _run(CREATOR.name, CREATOR.read_bytes())
    names = set(_by_name(processed))

    assert {"header_custom", "name_protect", "close_excel_workbook", "CBW", "f_D"} <= names
    assert processed.flags == []
    for node in processed.nodes:
        assert node.content.startswith("# File: Test_plan_creator.py")
        assert len(node.content) < 1.6 * MAX_SYMBOL_CHARS + 1000
    covered = {line for n in processed.nodes for line in range(n.line_start, n.line_end + 1)}
    source_lines = CREATOR.read_text(errors="replace").splitlines()
    code_lines = {
        i + 1 for i, line in enumerate(source_lines) if line.strip() and not line.lstrip().startswith("#")
    }
    assert len(code_lines - covered) / len(code_lines) < 0.02


@pytest.mark.skipif(not WEB.exists(), reason="data/samples/web not exported locally")
def test_web_samples_c_matlab_notebook():
    crc = _by_name(_run("cfe_es_crc.c", (WEB / "c" / "cfe_es_crc.c").read_bytes()))
    assert "CFE_ES_ComputeCRC_Algo_16_ARC" in crc
    assert (
        "0xA001" in crc["CFE_ES_ComputeCRC_Algo_16_ARC"].content.upper()
        or "CrcTable" in crc["CFE_ES_ComputeCRC_Algo_16_ARC"].content
    )

    doy = _by_name(_run("dayofyear.m", (WEB / "m" / "dayofyear.m").read_bytes()))["dayofyear"]
    assert "mod(d.Year,4) == 0" in doy.content and "daysPerMonth(2) = 29" in doy.content
    assert doy.metadata["docstring"].startswith("DAYOFYEAR Converts a date string")

    notebook = _run("Running_Code.ipynb", (WEB / "ipynb" / "Running_Code.ipynb").read_bytes())
    text = "\n".join(n.content for n in notebook.nodes)
    assert "`Alt-Enter` runs the current cell and inserts a new one below." in text
    assert "`Ctrl-Enter` run the current cell and enters command mode." in text
