"""Route G as metadata cards (Lead, 2026-10-23): every archive, ANSYS package and CAD file becomes one
``ProcessedDocument`` with a single text node, the card, instead of being unpacked.

The card states what can be known without opening the content: name, kind, size, folder, test plan, run and
hardware from the folder, the file's dates, every other folder holding the same bytes with its date (where the
file was used), the related files beside it, and a contents summary: an archive's member names from its
directory, a mesh's or solid's measurements. The shared tail then enriches and embeds the card like any
other text, so the answer engine finds the file by what it was and where it sat. Nothing is extracted, so
nothing here can crash on a corrupt or hostile file: a damaged archive is a card with a "could not list"
line. The unpacking route stays in ``route.py`` as ``process_full``.
"""

import io
import json
import tarfile
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from backend.dispatcher.contract import DocumentFields, ProcessedDocument, ProcessedNode
from backend.dispatcher.folder_context import PLAN_PATTERNS, FolderContext
from backend.postgres.enums import DocKind, NodeSource, NodeType, Route
from backend.routes.g_archives import cad
from backend.routes.g_archives.archive import archive_kind

KINDS = (
    (".tar.gz", "gzip-compressed TAR archive"),
    (".tgz", "gzip-compressed TAR archive"),
    (".tar.bz2", "bzip2-compressed TAR archive"),
    (".tar.xz", "xz-compressed TAR archive"),
    (".tar", "TAR archive"),
    (".zip", "ZIP archive"),
    (".gz", "gzip-compressed file"),
    (".wbpz", "ANSYS Workbench package"),
    (".stl", "STL mesh"),
    (".step", "STEP CAD model"),
    (".stp", "STEP CAD model"),
    (".igs", "IGES CAD model"),
    (".iges", "IGES CAD model"),
    (".scdoc", "SpaceClaim document"),
    (".dwg", "AutoCAD drawing (DWG)"),
)
MEASURED = (".stl", ".step", ".stp")
MEASURE_MAX_BYTES = 200 * 1024**2
TAR_LIST_MAX_BYTES = 300 * 1024**2
LIST_MAX_ENTRIES = 5000
NAMES_SHOWN = 40
TOP_LEVEL_SHOWN = 12
COPIES_SHOWN = 8
LIST_ERRORS = (
    zipfile.BadZipFile,
    tarfile.TarError,
    OSError,
    EOFError,
    zlib.error,
    NotImplementedError,
    RuntimeError,
)


@dataclass(frozen=True)
class Copy:
    """Another live location of the same bytes."""

    path: str
    modified_at: datetime | None = None


def _kind_label(file_name: str) -> str:
    folded = file_name.casefold()
    return next((label for suffix, label in KINDS if folded.endswith(suffix)), "file")


def _day(moment: datetime | None) -> str | None:
    return moment.date().isoformat() if moment else None


def _listing(data: bytes, file_name: str) -> dict[str, Any] | None:
    """Member names and sizes from the archive's directory, never member data; None when not an archive."""
    kind = archive_kind(file_name, data[:512])
    if kind is None:
        return None
    names: list[tuple[str, int | None]] = []
    result: dict[str, Any] = {"format": kind, "encrypted": False, "error": None}
    try:
        if kind in ("zip", "wbpz"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist():
                    if not info.is_dir():
                        names.append((info.filename, info.file_size))
                        result["encrypted"] = result["encrypted"] or bool(info.flag_bits & 0x1)
        elif kind == "tar":
            if len(data) > TAR_LIST_MAX_BYTES:
                result["error"] = "not listed: archive above 300 MB"
            else:
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                    for info in archive:
                        if info.isfile():
                            names.append((info.name, info.size))
                        if len(names) >= LIST_MAX_ENTRIES:
                            break
        else:
            stem = file_name[:-3] if file_name.casefold().endswith(".gz") else file_name
            names.append((stem, None))
    except LIST_ERRORS as exc:
        result["error"] = f"could not be listed: {type(exc).__name__}: {str(exc)[:120]}"
    result["files"] = [{"name": name, "size": size} for name, size in names[:LIST_MAX_ENTRIES]]
    result["count"] = len(names)
    return result


def _contents_lines(listing: dict[str, Any]) -> list[str]:
    files = listing["files"]
    lines = [f"Contents ({listing['format']}): {listing['count']} files"]
    if listing["error"]:
        lines[0] += f"; the directory {listing['error']}"
    if listing["encrypted"]:
        lines.append("Password-protected: yes, the contents cannot be read without the password")
    if not files:
        return lines
    paths = [PurePosixPath(f["name"]) for f in files]
    types = Counter(p.suffix.casefold().lstrip(".") or "no extension" for p in paths)
    lines.append("File types: " + ", ".join(f"{kind} {count}" for kind, count in types.most_common(10)))
    top = list(dict.fromkeys(p.parts[0] + ("/" if len(p.parts) > 1 else "") for p in paths))
    lines.append(
        "Top-level entries: "
        + ", ".join(top[:TOP_LEVEL_SHOWN])
        + (" …" if len(top) > TOP_LEVEL_SHOWN else "")
    )
    shown = [f["name"] for f in files[:NAMES_SHOWN]]
    more = listing["count"] - len(shown)
    lines.append("Files: " + "; ".join(shown) + (f"; and {more} more" if more > 0 else ""))
    return lines


def _plans(paths: Sequence[str]) -> list[str]:
    found: list[str] = []
    for path in paths:
        for pattern in PLAN_PATTERNS:
            for match in pattern.finditer(path):
                plan = f"TP{int(match.group(1)):02d}"
                if plan not in found:
                    found.append(plan)
    return found


def _copy_lines(copies: Sequence[Copy]) -> list[str]:
    if not copies:
        return []
    shown = [
        f"{c.path}" + (f" (modified {_day(c.modified_at)})" if c.modified_at else "")
        for c in copies[:COPIES_SHOWN]
    ]
    more = len(copies) - len(shown)
    return [
        f"Also stored in {len(copies)} other places: "
        + "; ".join(shown)
        + (f"; and {more} more" if more > 0 else "")
    ]


def build_card(
    data: bytes,
    *,
    blob_sha256: str,
    file_name: str,
    folder: FolderContext,
    put_cir: Callable[[str, bytes], str],
    parser_version: int,
    cir_uri: str,
    path: str | None = None,
    folder_files: Sequence[str] = (),
    web_url: str | None = None,
    created_at: datetime | None = None,
    modified_at: datetime | None = None,
    copies: Sequence[Copy] = (),
) -> ProcessedDocument:
    suffix = PurePosixPath(file_name).suffix.casefold()
    label = _kind_label(file_name)
    folder_path = "/".join(folder.breadcrumb) or folder.path_cached
    same, other = cad.related_files(path or file_name, folder_files)
    all_paths = [folder.path_cached, *(c.path for c in copies)]
    plans = _plans(all_paths)

    measurement = None
    measurement_error = None
    if suffix in MEASURED and len(data) <= MEASURE_MAX_BYTES:
        try:
            measurement = cad.measure(data, file_name)
        except cad.CadError as exc:
            measurement_error = str(exc)[:200]
    listing = _listing(data, file_name)

    lines = [f"{label}: {file_name}", f"Size: {len(data):,} bytes"]
    lines.append(f"Folder: {folder_path}")
    ids = [
        x
        for x in (
            folder.test_plan_id and f"test plan {folder.test_plan_id}",
            folder.test_run_id and f"run {folder.test_run_id}",
            folder.hardware_item and f"hardware {folder.hardware_item}",
        )
        if x
    ]
    if ids:
        lines.append("Identified from the folder: " + ", ".join(ids))
    dates = [
        x
        for x in (
            modified_at and f"last modified {_day(modified_at)}",
            created_at and f"created {_day(created_at)}",
        )
        if x
    ]
    if dates:
        lines.append("File dates: " + ", ".join(dates))
    if len(plans) > 1 or (plans and plans != [folder.test_plan_id]):
        lines.append("Test plans whose folders hold this file: " + ", ".join(plans))
    lines += _copy_lines(copies)
    if suffix in cad.DRAWING_SUFFIXES or measurement:
        facts = cad.describe(file_name, len(data), folder_path, measurement, same, other).splitlines()[1:]
        lines += facts
    if measurement_error:
        lines.append(f"Geometry could not be read: {measurement_error}")
    if listing is not None:
        lines += _contents_lines(listing)
    if suffix == ".igs" or suffix == ".iges":
        lines.append("IGES surfaces are not measured")
    content = "\n".join(lines)

    catalog: dict[str, Any] = {
        "format": suffix.lstrip("."),
        "kind": label,
        "file_name": file_name,
        "size_bytes": len(data),
        "folder": folder_path,
        "web_url": web_url,
        "created_at": created_at.isoformat() if created_at else None,
        "modified_at": modified_at.isoformat() if modified_at else None,
        "copies": [
            {"path": c.path, "modified_at": c.modified_at.isoformat() if c.modified_at else None}
            for c in copies
        ],
        "test_plans": plans,
        "measurement": measurement,
        "measurement_error": measurement_error,
        "listing": None
        if listing is None
        else {k: v for k, v in listing.items() if k != "files"}
        | {"names": [f["name"] for f in listing["files"][:200]]},
        "references": same,
        "folder_drawings": other,
    }
    put_cir("card.json", json.dumps(catalog, ensure_ascii=False, indent=1, default=str).encode())
    doc_kind = (
        DocKind.CAE_PACKAGE
        if suffix == ".wbpz"
        else DocKind.CAD_REFERENCE
        if suffix in cad.DRAWING_SUFFIXES and suffix not in (".pdf", ".dxf", ".drawio")
        else DocKind.UNKNOWN
    )
    node = ProcessedNode(
        ref="card",
        node_type=NodeType.CHILD,
        level=1,
        ordinal=0,
        breadcrumb=file_name,
        language="en",
        content=content,
        line_start=1,
        source=NodeSource.STRUCTURED,
        metadata={"measurement": measurement} if measurement else {},
    )
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.G,
        parser_version=parser_version,
        cir_uri=cir_uri,
        document=DocumentFields(
            title=file_name,
            doc_kind=doc_kind,
            source_origin=folder.source_origin,
            trust_tier=folder.trust_tier,
            test_plan_id=folder.test_plan_id,
            test_run_id=folder.test_run_id,
            hardware_item=folder.hardware_item,
            language="en",
            catalog=catalog,
        ),
        nodes=[node],
    )
