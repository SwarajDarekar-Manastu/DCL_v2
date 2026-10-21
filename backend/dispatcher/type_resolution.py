"""Real type of a landed blob (file 03 §1.1): magic bytes first, then the extension.

Custom sniffers read the first bytes (``HEAD_BYTES``); libmagic supplies the MIME string for
anything the sniffers do not name. ZIP-based formats (DOCX/PPTX/XLSX, ANSYS ``.wbpz``) are told
apart by their member names, which the caller reads from the archive's central directory.
Generic text is refined by the extension (``.csv``, ``.dat``, ``.tex``, ``.py`` …).

The content wins over the extension; a disagreement is reported in ``ext_mismatch`` and stored
on ``drive_items`` (file 02 §4 Tier 4). A type with no route is ``route = None``: the dispatcher
raises ``UNSUPPORTED_FORMAT`` (HARD). Nothing here deserializes content: a pickle is named from
its first bytes and never loaded.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

import magic

from backend.postgres.enums import Route

HEAD_BYTES = 4096
TEXT_MIN_PRINTABLE = 0.95


@dataclass(frozen=True)
class Kind:
    name: str
    mime: str
    route: Route | None
    text: bool = False


K = {
    k.name: k
    for k in (
        Kind("pdf", "application/pdf", Route.A1),
        Kind("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", Route.A1),
        Kind("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", Route.A1),
        Kind("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", Route.C),
        Kind("wbpz", "application/x-ansys-wbpz", Route.G),
        Kind("zip", "application/zip", Route.G),
        Kind("doc", "application/msword", Route.A1),
        Kind("ppt", "application/vnd.ms-powerpoint", Route.A1),
        Kind("xls", "application/vnd.ms-excel", Route.C),
        Kind("npy", "application/x-npy", Route.C),
        Kind("pickle", "application/x-python-pickle", Route.C),
        Kind("hdf5", "application/x-hdf5", Route.C),
        Kind("tdms", "application/x-tdms", Route.C),
        Kind("drawio", "application/vnd.jgraph.mxfile", Route.E),
        Kind("xsd", "application/xml-schema", Route.E),
        Kind("gzip", "application/gzip", Route.G),
        Kind("heic", "image/heic", Route.D),
        Kind("jpeg", "image/jpeg", Route.D),
        Kind("png", "image/png", Route.D),
        Kind("mp4", "video/mp4", Route.F),
        Kind("mov", "video/quicktime", Route.F),
        Kind("scdoc", "application/x-spaceclaim", Route.G),
        Kind("html", "text/html", None, text=True),
        Kind("json", "application/json", Route.A2, text=True),
        Kind("tex", "text/x-tex", Route.A2, text=True),
        Kind("python", "text/x-python", Route.B, text=True),
        Kind("notebook", "application/x-ipynb+json", Route.B, text=True),
        Kind("markdown", "text/markdown", Route.B, text=True),
        Kind("plain_text", "text/plain", Route.B, text=True),
        Kind("delimited_text", "text/csv", Route.C, text=True),
        Kind("telemetry_text", "text/plain", Route.C, text=True),
        Kind("unknown_text", "text/plain", Route.C, text=True),
    )
}

# What the extension says when the content is text (or when no sniffer matched).
EXTENSION_KINDS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".wbpz": "wbpz",
    ".zip": "zip",
    ".doc": "doc",
    ".ppt": "ppt",
    ".xls": "xls",
    ".npy": "npy",
    ".pkl": "pickle",
    ".tdms": "tdms",
    ".drawio": "drawio",
    ".xsd": "xsd",
    ".gz": "gzip",
    ".heic": "heic",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".mp4": "mp4",
    ".mov": "mov",
    ".scdoc": "scdoc",
    ".html": "html",
    ".htm": "html",
    ".json": "json",
    ".tex": "tex",
    ".py": "python",
    ".ipynb": "notebook",
    ".md": "markdown",
    ".txt": "plain_text",
    ".bat": "plain_text",
    ".csv": "delimited_text",
    ".tsv": "delimited_text",
    ".dat": "telemetry_text",
    ".dat_fail": "telemetry_text",
    ".cfg": "telemetry_text",
    ".ini": "telemetry_text",
}
OLE2_BY_EXTENSION = {".doc": "doc", ".ppt": "ppt", ".xls": "xls"}
NO_SIGNATURE_KINDS = frozenset({"scdoc"})  # trusted by extension: no sniffer can confirm them
DELIMITERS = (",", ";", "\t", "|")
GENERIC_TEXT = frozenset({"text", "delimited"})


@dataclass(frozen=True)
class ResolvedType:
    kind: str
    mime: str
    route: Route | None
    by: str
    ext_mismatch: bool


def extension_of(name: str) -> str:
    """Lowercased last suffix (``.dat_fail`` counts as one); ``""`` for extensionless names."""
    return PurePosixPath(name).suffix.casefold()


UTF16_BOMS = {b"\xff\xfe": "utf-16-le", b"\xfe\xff": "utf-16-be"}


def _decode_text(head: bytes) -> str | None:
    """The head as text, or None for binary. UTF-16 with a BOM (PowerShell's `pip freeze >`) is text."""
    encoding = UTF16_BOMS.get(head[:2])
    if encoding is not None:
        text = head[2:].decode(encoding, errors="ignore")
    elif b"\x00" in head:
        return None
    else:
        text = head.decode("utf-8", errors="ignore")
    if not text:
        return None
    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
    return text if printable / len(text) >= TEXT_MIN_PRINTABLE else None


def _zip_kind(names: Sequence[str] | None) -> str:
    if not names:
        return "zip"
    if "[Content_Types].xml" in names:
        for prefix, kind in (("word/", "docx"), ("ppt/", "pptx"), ("xl/", "xlsx")):
            if any(n.startswith(prefix) for n in names):
                return kind
    if any(n.startswith("dp0/") or n.endswith(".wbpj") for n in names):
        return "wbpz"
    return "zip"


def _sniff(head: bytes, extension: str, zip_names: Sequence[str] | None) -> str | None:
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        if extension == ".scdoc":
            return "scdoc"  # SpaceClaim documents are ZIP containers
        return _zip_kind(zip_names)
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return OLE2_BY_EXTENSION.get(extension, "ole2")
    if head.startswith(b"\x93NUMPY"):
        return "npy"
    if head[:2] in (b"\x80\x02", b"\x80\x03", b"\x80\x04", b"\x80\x05"):
        return "pickle"
    if head.startswith(b"\x89HDF"):
        return "hdf5"
    if head.startswith(b"TDSm"):
        return "tdms"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1"):
            return "heic"
        if brand in (b"isom", b"mp42", b"mp41", b"avc1"):
            return "mp4"
        if brand == b"qt  ":
            return "mov"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG"):
        return "png"
    text = _decode_text(head)
    if text is not None:
        return _sniff_text(text)
    return None


def _sniff_text(text: str) -> str:
    text = text.lstrip("\ufeff \t\r\n")
    lowered = text[:1024].casefold()
    if "<mxfile" in lowered or "<mxgraphmodel" in lowered:
        return "drawio"
    if lowered.startswith("<?xml") and ("<xs:schema" in lowered or "<xsd:schema" in lowered):
        return "xsd"
    if lowered.startswith("<!doctype html") or lowered.startswith("<html"):
        return "html"
    lines = [line for line in text.splitlines()[:-1] if line.strip()][:20]
    for delimiter in DELIMITERS:
        counts = {line.count(delimiter) for line in lines[-10:]}
        if len(lines) >= 3 and len(counts) == 1 and counts != {0}:
            return "delimited"
    return "text"


def resolve_type(head: bytes, name: str, zip_names: Sequence[str] | None = None) -> ResolvedType:
    """Content first, then extension. ``head`` is at least the first ``HEAD_BYTES`` of the blob."""
    extension = extension_of(name)
    by_extension = EXTENSION_KINDS.get(extension)
    sniffed = _sniff(head[:HEAD_BYTES], extension, zip_names)

    if sniffed in GENERIC_TEXT:
        ext_kind = K.get(by_extension) if by_extension else None
        if ext_kind is not None and ext_kind.text:
            return ResolvedType(ext_kind.name, ext_kind.mime, ext_kind.route, "extension", ext_mismatch=False)
        kind = K["delimited_text" if sniffed == "delimited" else "unknown_text"]
        return ResolvedType(kind.name, kind.mime, kind.route, "magic", ext_mismatch=by_extension is not None)

    if sniffed in K:
        kind = K[sniffed]
        return ResolvedType(kind.name, kind.mime, kind.route, "magic", by_extension not in (None, kind.name))

    if sniffed is None and by_extension in NO_SIGNATURE_KINDS:
        kind = K[by_extension]
        return ResolvedType(kind.name, kind.mime, kind.route, "extension", ext_mismatch=False)

    mime = magic.from_buffer(head[:HEAD_BYTES], mime=True) if head else "application/x-empty"
    return ResolvedType(sniffed or "unknown", mime, None, "magic", ext_mismatch=by_extension is not None)
