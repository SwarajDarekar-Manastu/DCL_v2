"""Conversion service of the libreoffice container (docs/architecture/01 §5.3): one soffice run per request.

    POST /convert?from=<ext>&to=<pdf|docx|pptx|xlsx>   body: the file bytes   -> 200 with the converted bytes
    GET  /health                                                               -> 200 "ok"

Each request gets its own temporary directory and a fresh copy of the profile template, whose settings make
Calc recalculate every formula on load, so an xlsx -> xlsx round trip refreshes stale cached values. Standard
library only; at most OFFICE_PARALLEL conversions run at once; inputs above OFFICE_MAX_BYTES are refused.
"""

import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PROFILE_TEMPLATE = Path("/home/office/lo-profile")
TARGETS = {
    "pdf": "pdf",
    "docx": "docx:MS Word 2007 XML",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
}
INPUTS = frozenset({"doc", "docx", "rtf", "odt", "ppt", "pptx", "odp", "xls", "xlsx", "ods"})
MAX_BYTES = int(os.environ.get("OFFICE_MAX_BYTES", str(200 * 1024 * 1024)))
TIMEOUT_S = int(os.environ.get("OFFICE_TIMEOUT_S", "180"))
SLOTS = threading.BoundedSemaphore(int(os.environ.get("OFFICE_PARALLEL", "2")))


def convert(data: bytes, source: str, target: str) -> bytes:
    with SLOTS, tempfile.TemporaryDirectory(prefix="convert-") as work:
        root = Path(work)
        profile = root / "profile"
        shutil.copytree(PROFILE_TEMPLATE, profile)
        infile = root / f"input.{source}"
        infile.write_bytes(data)
        outdir = root / "out"
        command = [
            "soffice",
            "--headless",
            "--norestore",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            TARGETS[target],
            "--outdir",
            str(outdir),
            str(infile),
        ]
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_S, check=False)  # noqa: S603
        result = outdir / f"input.{target}"
        if not result.is_file():
            raise ValueError(
                f"soffice produced no .{target} (exit {done.returncode}): {done.stderr.strip()[-300:]}"
            )
        return result.read_bytes()


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: bytes, kind: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/health":
            self._reply(200, b"ok")
        else:
            self._reply(404, b"not found")

    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        source, target = query.get("from", "").lower(), query.get("to", "").lower()
        length = int(self.headers.get("Content-Length") or 0)
        if url.path != "/convert" or source not in INPUTS or target not in TARGETS:
            return self._reply(400, b"use POST /convert?from=<ext>&to=<pdf|docx|pptx|xlsx>")
        if length <= 0 or length > MAX_BYTES:
            return self._reply(413, f"body must be 1..{MAX_BYTES} bytes".encode())
        data = self.rfile.read(length)
        try:
            out = convert(data, source, target)
        except subprocess.TimeoutExpired:
            return self._reply(504, f"conversion exceeded {TIMEOUT_S} s".encode())
        except ValueError as exc:
            return self._reply(422, str(exc).encode())
        self._reply(200, out, "application/octet-stream")

    def log_message(self, fmt: str, *args) -> None:
        print(f"office: {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 2003), Handler).serve_forever()  # noqa: S104
