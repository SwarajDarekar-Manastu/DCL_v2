"""Routes D and F run in the media worker image, which has no PDF stack: importing them must not pull in
pikepdf, pypdfium2, docling or lxml (65 photos FAILED live on d_photos → a1_office.figures → preflight)."""

import subprocess
import sys

BLOCKED = ("pikepdf", "pypdfium2", "docling", "lxml")
PROBE = f"""
import sys
for name in {BLOCKED!r}:
    sys.modules[name] = None  # any import of it raises ImportError
import backend.routes.d_photos as d
import backend.routes.f_video as f
from backend.routes.a1_office.figures import render_plot, render_schematic
print("ok")
"""


def test_routes_d_and_f_import_without_the_pdf_stack():
    result = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "ok"
