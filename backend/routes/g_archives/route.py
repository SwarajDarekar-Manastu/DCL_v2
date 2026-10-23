"""Route G (file 03 §11; Lead 2026-10-23): archives, ANSYS packages and CAD → ``ProcessedDocument``.

``process_archive`` (``.zip``, ``.tar``, ``.tar.gz``/``.tgz``, ``.gz``, ``.wbpz``): bomb guard and gate
(``archive.py``); kept members are handed over as ``derived_blobs`` (kind ``archive_member``, bytes inside)
and S1's ``register_derived_blobs`` makes them blobs and documents, so a member identical to a loose file is
the same blob. The archive's own document lists its members (path, size, route the dispatcher will use, or
why the gate skipped it) in contents nodes and ``manifest.json``; more than 90 % skipped marks it
``mostly_junk`` in the catalog. A member over 1 GB is held (``HELD_LARGE_FILE`` SOFT). A ``.wbpz`` is
indexed inside (``wbpz.py``: solver summaries, materials, analysis systems) and hands over its images only.

``process_cad`` (``.stl``, ``.step``/``.stp``, ``.igs``/``.iges``, ``.scdoc``, ``.dwg``): a ``cad_reference``
document, with the trimesh measurement for meshes and B-reps, and the related drawings in the same folder
in ``catalog.references`` (S1 writes ``document_relations(REFERENCES)``).

Flags: ``PARSE_FAILURE`` HARD for a bomb-guard violation, an encrypted archive or an unreadable file (with
the partial manifest); ``HELD_LARGE_FILE`` SOFT per held member.
"""

import hashlib
import io
import json
import zipfile
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from backend.dispatcher.contract import (
    DerivedBlob,
    DocumentFields,
    FileFactsEvidence,
    Flag,
    FlagAnchor,
    Mention,
    ParseFailureEvidence,
    ProcessedDocument,
    ProcessedNode,
)
from backend.dispatcher.folder_context import FolderContext
from backend.dispatcher.type_resolution import resolve_type
from backend.postgres.enums import (
    BlobDerivationKind,
    DocKind,
    FlagSeverity,
    FlagType,
    MentionSource,
    NodeSource,
    NodeType,
    Route,
)
from backend.routes.g_archives import cad
from backend.routes.g_archives.archive import ArchiveBomb, ArchiveEncrypted, Expander, Member, archive_kind
from backend.sync.gate import GateConfig

PARSER_VERSION = 1
GATE_YAML = Path(__file__).resolve().parents[3] / "config" / "gate.yaml"
MEMBERS_PER_NODE = 60
MOSTLY_JUNK = 0.9
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff")
CAD_SUFFIXES = (*cad.MESH_SUFFIXES, *cad.BREP_SUFFIXES, *cad.REFERENCE_SUFFIXES)
SEPARATOR = " › "


@dataclass(frozen=True)
class Stores:
    """``put_cir(relative_key, bytes) -> uri`` under ``dcl-cir/{sha256}/G/v1/`` (Route G writes no assets)."""

    put_cir: Callable[[str, bytes], str]


def can_handle(head: bytes, name: str) -> bool:
    if name.casefold().endswith(CAD_SUFFIXES):
        return True
    return archive_kind(name, head) is not None and not name.casefold().endswith(
        (".docx", ".xlsx", ".pptx", ".vsdx")
    )


def _cir_uri(blob_sha256: str) -> str:
    return f"s3://dcl-cir/{blob_sha256}/{Route.G}/v{PARSER_VERSION}/"


def _fields(title: str, kind: DocKind, folder: FolderContext, catalog: dict) -> DocumentFields:
    return DocumentFields(
        title=title,
        doc_kind=kind,
        source_origin=folder.source_origin,
        trust_tier=folder.trust_tier,
        test_plan_id=folder.test_plan_id,
        test_run_id=folder.test_run_id,
        hardware_item=folder.hardware_item,
        language="en",
        catalog=catalog,
    )


def _failure(
    blob_sha256: str, file_name: str, error: str, data: bytes, folder: FolderContext, manifest: str = ""
) -> ProcessedDocument:
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.G,
        parser_version=PARSER_VERSION,
        cir_uri=_cir_uri(blob_sha256),
        document=_fields(file_name, DocKind.UNKNOWN, folder, {"error": error[:500]}),
        flags=[
            Flag(
                flag_type=FlagType.PARSE_FAILURE,
                severity=FlagSeverity.HARD,
                evidence=ParseFailureEvidence(
                    error=error[:2000],
                    magic_bytes_hex=data[:16].hex(),
                    size_bytes=len(data),
                    extension=PurePosixPath(file_name).suffix.lstrip("."),
                    partial_output=manifest[:20000] or None,
                ),
            )
        ],
    )


def _route_of(member: Member) -> str | None:
    if member.data is None:
        return None
    zip_names = None
    if member.data.startswith(b"PK\x03\x04"):  # DOCX/XLSX/PPTX are told apart by their part names
        try:
            with zipfile.ZipFile(io.BytesIO(member.data)) as package:
                zip_names = package.namelist()
        except zipfile.BadZipFile:
            zip_names = None
    resolved = resolve_type(member.data[:4096], PurePosixPath(member.path.split("!/")[-1]).name, zip_names)
    return str(resolved.route) if resolved.route else None


def _manifest_line(member: Member, route: str | None) -> str:
    what = {
        "kept": f"route {route}" if route else "kept, no route",
        "skipped": f"skipped ({member.reason})",
        "held": f"held ({member.reason})",
        "symlink": "symlink ignored",
        "archive": member.reason,
    }[member.status]
    return f"{member.path} — {member.size:,} bytes — {what}"


def process_archive(
    data: bytes,
    *,
    blob_sha256: str,
    file_name: str,
    folder: FolderContext,
    stores: Stores,
    gate_config: GateConfig | None = None,
) -> ProcessedDocument:
    gate = gate_config or GateConfig.load(GATE_YAML)
    kind = archive_kind(file_name, data[:512])
    if kind is None:
        return _failure(blob_sha256, file_name, "not an archive this route reads", data, folder)
    expander = Expander(gate, folder.breadcrumb, len(data))
    try:
        members = expander.expand(data, file_name, kind)
    except (ArchiveBomb, ArchiveEncrypted) as exc:
        manifest = "\n".join(_manifest_line(m, None) for m in expander.budget.members)
        reason = "encrypted archive" if isinstance(exc, ArchiveEncrypted) else "bomb guard"
        return _failure(blob_sha256, file_name, f"{reason}: {exc}", data, folder, manifest)

    title = PurePosixPath(file_name).name
    routes = {m.path: _route_of(m) for m in members}
    leaves = [m for m in members if m.status in ("kept", "skipped", "held")]
    skipped = sum(1 for m in leaves if m.status == "skipped")
    catalog = {
        "archive_format": kind,
        "members": len(leaves),
        "kept": sum(1 for m in leaves if m.status == "kept"),
        "skipped": skipped,
        "held": sum(1 for m in leaves if m.status == "held"),
        "nested_archives": [m.path for m in members if m.status == "archive"],
        "total_uncompressed_bytes": expander.budget.total,
        "mostly_junk": bool(leaves) and skipped / len(leaves) > MOSTLY_JUNK,
        "routes": dict(Counter(r for r in routes.values() if r)),
    }
    manifest = [
        {
            "path": m.path,
            "size": m.size,
            "status": m.status,
            "reason": m.reason or None,
            "sha256": m.sha256,
            "route": routes.get(m.path),
        }
        for m in members
    ]
    lines = [_manifest_line(m, routes.get(m.path)) for m in members]
    nodes: list[ProcessedNode] = []
    mentions: list[Mention] = []
    flags: list[Flag] = []
    for start in range(0, len(lines), MEMBERS_PER_NODE):
        chunk = lines[start : start + MEMBERS_PER_NODE]
        header = (
            f"Archive {title} ({kind}): {catalog['members']} files, {catalog['kept']} kept, {skipped} skipped"
        )
        nodes.append(
            ProcessedNode(
                ref=f"contents{start // MEMBERS_PER_NODE}",
                node_type=NodeType.CHILD,
                level=2,
                ordinal=len(nodes),
                breadcrumb=SEPARATOR.join([title, "Contents"]),
                language="en",
                content="\n".join([header, *chunk]),
                line_start=start + 1,
                line_end=start + len(chunk),
                source=NodeSource.STRUCTURED,
            )
        )
    for member in members:
        if member.status == "held":
            flags.append(
                Flag(
                    flag_type=FlagType.HELD_LARGE_FILE,
                    severity=FlagSeverity.SOFT,
                    anchor=FlagAnchor(content_sha256=hashlib.sha256(member.path.encode()).hexdigest()),
                    evidence=FileFactsEvidence(
                        size_bytes=member.size,
                        extension=PurePosixPath(member.path).suffix.lstrip(".") or None,
                        folder=f"{title}!/{PurePosixPath(member.path).parent}",
                        note=member.reason,
                    ),
                )
            )

    kept = [m for m in members if m.status == "kept" and m.data is not None]
    doc_kind = DocKind.UNKNOWN
    if kind == "wbpz":
        doc_kind = DocKind.CAE_PACKAGE
        extra_nodes, extra_mentions, systems = _wbpz(kept, title, len(nodes))
        nodes += extra_nodes
        mentions += extra_mentions
        catalog.update(systems)
        kept = [m for m in kept if m.path.casefold().endswith(IMAGE_SUFFIXES)]
    stores.put_cir(
        "manifest.json",
        json.dumps({"catalog": catalog, "members": manifest}, ensure_ascii=False, indent=1).encode(),
    )
    derived = [
        DerivedBlob(member_path=m.path, data=m.data, kind=BlobDerivationKind.ARCHIVE_MEMBER) for m in kept
    ]
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.G,
        parser_version=PARSER_VERSION,
        cir_uri=_cir_uri(blob_sha256),
        document=_fields(title, doc_kind, folder, catalog),
        nodes=nodes,
        mentions=mentions,
        flags=flags,
        derived_blobs=derived,
    )


def _wbpz(members: list[Member], title: str, offset: int) -> tuple[list[ProcessedNode], list[Mention], dict]:
    from backend.routes.g_archives import wbpz  # lxml: imported only when a .wbpz is processed

    nodes, mentions = [], []
    summaries, materials, systems = {}, [], set()
    for member in members:
        name = member.path.casefold()
        text = member.data.decode("utf-8", errors="replace")
        ordinal = offset + len(nodes)
        if name.endswith(".out"):
            summary = wbpz.solver_summary(text)
            summaries[member.path] = summary
            body = (
                "\n".join(f"{k}: {'; '.join(v) if isinstance(v, list) else v}" for k, v in summary.items())
                or "no solver summary lines found"
            )
            nodes.append(
                ProcessedNode(
                    ref=f"out{ordinal}",
                    node_type=NodeType.CHILD,
                    level=2,
                    ordinal=ordinal,
                    breadcrumb=SEPARATOR.join([title, "Solver log", PurePosixPath(member.path).name]),
                    language="en",
                    content=f"Solver output {member.path}\n{body}",
                    line_start=1,
                    source=NodeSource.STRUCTURED,
                    metadata={"member": member.path, "summary": summary},
                )
            )
        elif name.endswith((".xml", ".engd")) and b"MatML" in member.data[:200000]:
            for material in wbpz.materials(member.data):
                materials.append(material.name)
                rows = "".join(
                    f"<tr><td>{p}</td><td>{v}</td><td>{u}</td></tr>" for p, v, u in material.properties
                )
                ref = f"mat{offset + len(nodes)}"
                nodes.append(
                    ProcessedNode(
                        ref=ref,
                        node_type=NodeType.TABLE,
                        level=2,
                        ordinal=offset + len(nodes),
                        breadcrumb=SEPARATOR.join([title, "Engineering data", material.name]),
                        language="en",
                        content=f"<table><caption>{material.name}</caption><thead><tr><th>Property</th><th>Value</th>"
                        f"<th>Unit</th></tr></thead><tbody>{rows}</tbody></table>",
                        line_start=1,
                        source=NodeSource.STRUCTURED,
                        metadata={"member": member.path, "caption": f"Material {material.name}"},
                    )
                )
                mentions.append(
                    Mention(node_ref=ref, kind="material", surface=material.name, source=MentionSource.REGEX)
                )
        elif name.endswith(".wbpj"):
            systems |= set(wbpz.project_systems(text))
    return (
        nodes,
        mentions,
        {
            "analysis_systems": sorted(systems),
            "materials": sorted(set(materials)),
            "solver_logs": summaries,
        },
    )


def process_cad(
    data: bytes,
    *,
    blob_sha256: str,
    file_name: str,
    folder: FolderContext,
    stores: Stores,
    path: str | None = None,
    folder_files: Sequence[str] = (),
    web_url: str | None = None,
) -> ProcessedDocument:
    """``path``: the file's path in the subtree, so ``folder_files`` (same subtree) can be matched."""
    suffix = PurePosixPath(file_name).suffix.casefold()
    path = path or file_name
    same, other = cad.related_files(path, folder_files)
    measurement = None
    if suffix in (*cad.MESH_SUFFIXES, *cad.BREP_SUFFIXES):
        try:
            measurement = cad.measure(data, file_name)
        except cad.CadError as exc:
            return _failure(blob_sha256, file_name, str(exc), data, folder)
    folder_path = "/".join(folder.breadcrumb) or folder.path_cached
    content = cad.describe(file_name, len(data), folder_path, measurement, same, other)
    catalog = {
        "cad_format": suffix.lstrip("."),
        "file_name": file_name,
        "size_bytes": len(data),
        "folder": folder_path,
        "web_url": web_url,
        "measurement": measurement,
        "references": same,
        "folder_drawings": other,
    }
    mentions = []
    if measurement:
        x, y, z = measurement["extents"]
        mentions.append(
            Mention(node_ref="cad", kind="dimension", surface=f"{x} × {y} × {z} {measurement['units']}")
        )
    stores.put_cir("cad.json", json.dumps(catalog, ensure_ascii=False, indent=1).encode())
    node = ProcessedNode(
        ref="cad",
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
        parser_version=PARSER_VERSION,
        cir_uri=_cir_uri(blob_sha256),
        document=_fields(PurePosixPath(file_name).stem, DocKind.CAD_REFERENCE, folder, catalog),
        nodes=[node],
        mentions=mentions,
    )


def process(data: bytes, **kwargs) -> ProcessedDocument:
    """One entry for the runner: CAD by extension, everything else as an archive."""
    if kwargs["file_name"].casefold().endswith(CAD_SUFFIXES):
        return process_cad(data, **kwargs)
    for key in ("path", "folder_files", "web_url"):
        kwargs.pop(key, None)
    return process_archive(data, **kwargs)
