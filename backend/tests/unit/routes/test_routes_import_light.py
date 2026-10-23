"""The dispatcher (io_light image, no parse libraries) imports the S6 route modules for ``can_handle``.
Each ``route`` module and its type checks must work with only the standard library and Pillow: the parse
libraries are blocked in ``sys.modules`` here, in a fresh interpreter, and every predicate is called."""

import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BLOCKED = [
    "lxml",
    "tree_sitter",
    "tree_sitter_python",
    "tree_sitter_c",
    "tree_sitter_matlab",
    "ezdxf",
    "trimesh",
    "cascadio",
    "resvg_py",
    "pylatexenc",
    "defusedxml",
    "networkx",
    "matplotlib",
    "docling",
    "pypdfium2",
    "pikepdf",
]

SCRIPT = textwrap.dedent(
    """
    import sys
    for name in {blocked!r}:
        sys.modules[name] = None  # any import of it raises ImportError
    from backend.routes.a2_source import route as a2
    from backend.routes.b_code import route as b
    from backend.routes.e_diagrams import route as e
    from backend.routes.g_archives import route as g

    checks = [
        a2.can_handle_tex(b"\\\\documentclass{{article}}", "Test_plan.tex"),
        a2.can_handle_json(b'{{"test_id": "T01"}}', "objectives.json"),
        b.can_handle(b"import numpy\\n", "nozzle.py"),
        b.can_handle(b"function y = f(x)\\n", "f.m"),
        e.can_handle(b"<mxfile host=", "diagram.drawio"),
        e.can_handle(b"<svg xmlns=", "x.svg"),
        e.can_handle(b"PK\\x03\\x04", "plant.vsdx"),
        e.can_handle(b"  0\\nSECTION", "part.dxf"),
        g.can_handle(b"PK\\x03\\x04", "bundle.zip"),
        g.can_handle(b"\\x1f\\x8b", "run.dat.gz"),
        g.can_handle(b"solid part", "part.stl"),
        g.can_handle(b"", "assembly.scdoc"),
        not g.can_handle(b"PK\\x03\\x04", "report.docx"),
    ]
    assert all(checks), checks
    loaded = sorted(n for n in {blocked!r} if sys.modules.get(n) is not None)
    assert not loaded, loaded
    print("ok")
    """
).format(blocked=BLOCKED)


def test_route_modules_import_without_parse_libraries():
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=REPO, capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr[-3000:]
