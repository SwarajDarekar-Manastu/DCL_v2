"""Route E (file 03 §9; Lead ruling 2026-10-23 adds SVG, Visio and DXF): a diagram → ``ProcessedDocument``.

Formats: draw.io (``.drawio``, ``.dio``, or XML starting ``<mxfile``/``<mxGraphModel``), XSD, SVG, ``.vsdx``,
DXF. Every graph format becomes one ``Graph`` (``graph.py``): ``documents.catalog`` holds it, ``graph.json``
in the CIR too, and the text nodes are a ``diagram_summary`` per page plus a ``diagram_component`` per
labeled component with its neighbourhood. DXF adds the layers, dimensions, blocks and table texts to its
summary. XSD becomes a section tree (one node per element or type) with ``enumeration`` mentions.

Renders (``render.py``): each draw.io page, the SVG drawing and the DXF modelspace as ``diagram_render``
assets (``diagrams/{sha256}/{page:02d}.png``). When cloud processing is allowed, ``read_schematic`` reads each
render and each image embedded in a draw.io page; its reading becomes a ``vlm`` node, and tags the model
reads that the file does not contain raise ``CONFLICT`` SOFT (labels drawn as free text or mislabeled).

Locators: ``page_no`` = diagram page (Visio page, DXF/SVG 1); ``line_start`` = the cell's line in the XML
where there is one. Flags: ``PARSE_FAILURE`` HARD for invalid XML or an unreadable package; ``CONFLICT``
SOFT for an incomplete graph (> 30 % unlabeled connections, > 20 % orphan components) and for render tags
the file lacks. ``Rev C`` in the file name sets ``revision_marker``.
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from backend.dispatcher.contract import (
    ConflictEvidence,
    ConflictSide,
    DocumentFields,
    Flag,
    FlagAnchor,
    Mention,
    ParseFailureEvidence,
    ProcessedAsset,
    ProcessedDocument,
    ProcessedNode,
)
from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import (
    AssetKind,
    DocKind,
    FlagSeverity,
    FlagType,
    NodeSource,
    NodeType,
    Route,
)
from backend.routes.e_diagrams import formats
from backend.routes.e_diagrams.drawio import DiagramError, parse_drawio
from backend.routes.e_diagrams.graph import (
    SEPARATOR,
    Graph,
    duplicate_tags,
    graph_flags,
    graph_nodes,
    tags_of,
)

PARSER_VERSION = 1
REVISION = re.compile(r"\b(rev(?:ision)?\.?\s*[A-Z0-9]{1,3})\b", re.IGNORECASE)
EXTENSIONS = (".drawio", ".dio", ".xsd", ".svg", ".vsdx", ".dxf")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Stores:
    put_cir: Callable[[str, bytes], str]
    put_asset: Callable[[str, bytes], str]


def diagram_format(head: bytes, name: str) -> str | None:
    suffix = PurePosixPath(name).suffix.casefold()
    text = head[:4096]
    if suffix in (".drawio", ".dio") or b"<mxfile" in text or b"<mxGraphModel" in text:
        return "drawio"
    if suffix == ".xsd" or (b"<xs:schema" in text or b"<xsd:schema" in text):
        return "xsd"
    if suffix == ".svg" or b"<svg" in text:
        return "svg"
    if suffix == ".vsdx" and head.startswith(b"PK\x03\x04"):
        return "vsdx"
    if suffix == ".dxf":
        return "dxf"
    return None


def can_handle(head: bytes, name: str) -> bool:
    return diagram_format(head, name) is not None


def _failure(blob_sha256: str, file_name: str, error: str, data: bytes) -> ProcessedDocument:
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.E,
        parser_version=PARSER_VERSION,
        cir_uri=f"s3://dcl-cir/{blob_sha256}/{Route.E}/v{PARSER_VERSION}/",
        document=DocumentFields(title=PurePosixPath(file_name).stem, doc_kind=DocKind.DIAGRAM),
        flags=[
            Flag(
                flag_type=FlagType.PARSE_FAILURE,
                severity=FlagSeverity.HARD,
                evidence=ParseFailureEvidence(
                    error=error[:2000],
                    magic_bytes_hex=data[:16].hex(),
                    size_bytes=len(data),
                    extension=PurePosixPath(file_name).suffix.lstrip("."),
                    first_kb_preview=data[:1024].decode("utf-8", errors="replace"),
                ),
            )
        ],
    )


def _xsd_nodes(data: bytes, title: str) -> tuple[list[ProcessedNode], list[Mention]]:
    nodes, mentions = [], []
    for section in formats.parse_xsd(data):
        lines = [
            f"{section['kind']} {section['name']}"
            + (f" (type {section['type']})" if section.get("type") else "")
        ]
        if section["doc"]:
            lines.append(section["doc"])
        if section["attributes"]:
            lines.append("Attributes: " + "; ".join(section["attributes"]))
        if section["children"]:
            lines.append("Elements: " + "; ".join(section["children"]))
        if section["enumerations"]:
            lines.append("Allowed values: " + ", ".join(section["enumerations"]))
        ref = f"x{len(nodes)}"
        nodes.append(
            ProcessedNode(
                ref=ref,
                node_type=NodeType.CHILD,
                level=2,
                ordinal=len(nodes),
                breadcrumb=SEPARATOR.join([title, f"{section['kind']} {section['name']}"]),
                language="en",
                content="\n".join(lines),
                line_start=section["line"],
                source=NodeSource.STRUCTURED,
                metadata={"xsd_kind": section["kind"], "name": section["name"]},
            )
        )
        mentions += [
            Mention(node_ref=ref, kind="enumeration", surface=v) for v in section["enumerations"] if v
        ]
    return nodes, mentions


def _schematic(vision, image: bytes, caption: str, context: str, doc_id, anchor: str):
    from backend.llm_engine.gemini_types import GeminiError, Image

    try:
        return vision.read_schematic(
            Image(image, "image/png" if image[:4] == b"\x89PNG" else "image/jpeg"),
            caption=caption,
            context=context,
            doc_id=doc_id,
            anchor=anchor,
        ).reading
    except GeminiError as exc:
        log.warning("read_schematic failed (%s): %s", anchor, exc)
        return None


def process_diagram(
    data: bytes,
    *,
    blob_sha256: str,
    file_name: str,
    folder: FolderContext,
    stores: Stores,
    vision=None,
    cloud_allowed: bool = False,
    doc_id: str | None = None,
) -> ProcessedDocument:
    kind = diagram_format(data[:4096], file_name)
    title = PurePosixPath(file_name).stem
    cir_uri = f"s3://dcl-cir/{blob_sha256}/{Route.E}/v{PARSER_VERSION}/"
    context = " / ".join([*folder.breadcrumb, file_name])
    renders: list[tuple[int, bytes]] = []
    embedded: list[tuple[int, str, bytes]] = []
    graph: Graph | None = None
    try:
        if kind == "xsd":
            nodes, mentions = _xsd_nodes(data, title)
        else:
            if kind == "drawio":
                graph, embedded = parse_drawio(data)
                for page in graph.pages:
                    try:
                        from backend.routes.e_diagrams.render import render_drawio_page

                        png = render_drawio_page(graph, page.number)
                    except Exception as exc:  # noqa: BLE001 — a failed render loses only the picture
                        log.warning("render of %s page %s failed: %s", file_name, page.number, exc)
                        png = None
                    if png:
                        renders.append((page.number, png))
            elif kind == "svg":
                graph = formats.parse_svg(data)
                try:
                    from backend.routes.e_diagrams.drawio import parse_xml
                    from backend.routes.e_diagrams.render import render_svg, svg_size

                    png = render_svg(data, svg_size(parse_xml(data)))
                except Exception as exc:  # noqa: BLE001 — a failed render loses only the picture
                    log.warning("render of %s failed: %s", file_name, exc)
                    png = None
                if png:
                    renders.append((1, png))
            elif kind == "vsdx":
                graph = formats.parse_vsdx(data)
            elif kind == "dxf":
                graph, document = formats.parse_dxf(data)
                try:
                    from backend.routes.e_diagrams.render import render_dxf

                    png = render_dxf(document)
                except Exception as exc:  # noqa: BLE001
                    log.warning("render of %s failed: %s", file_name, exc)
                    png = None
                if png:
                    renders.append((1, png))
            else:
                raise DiagramError(f"no diagram parser for {file_name}")
            nodes, mentions = graph_nodes(graph, title)
            if kind == "dxf":
                summary = nodes[0]
                nodes[0] = summary.model_copy(
                    update={"content": summary.content + "\n" + "\n".join(formats.dxf_texts(graph))}
                )
    except DiagramError as exc:
        return _failure(blob_sha256, file_name, str(exc), data)

    flags = graph_flags(graph) if graph is not None else []
    assets: list[ProcessedAsset] = []
    for page, png in renders:
        uri = stores.put_asset(f"diagrams/{blob_sha256}/{page:02d}.png", png)
        assets.append(
            ProcessedAsset(
                ref=f"render:{page}",
                kind=AssetKind.DIAGRAM_RENDER,
                minio_uri=uri,
                page_no=page,
                bytes=len(png),
            )
        )
    if graph is not None:
        for node_index, node in enumerate(nodes):
            if node.node_type == NodeType.DIAGRAM_SUMMARY and any(a.page_no == node.page_no for a in assets):
                nodes[node_index] = node.model_copy(update={"asset_ref": f"render:{node.page_no}"})

    readings = []
    if vision is not None and cloud_allowed and graph is not None:
        known = {t for c in graph.components for t in tags_of(c.label)} | {
            t for n in graph.notes for t in tags_of(n.text)
        }
        images = [(page, f"page {page}", png) for page, png in renders]
        images += [(page, f"embedded image {cid}", png) for page, cid, png in embedded]
        for page, what, png in images:
            reading = _schematic(vision, png, f"{title} {what}", context, doc_id, f"page:{page}:")
            if reading is None:
                continue
            from backend.routes.a1_office.figures import render_schematic

            text = render_schematic(reading)
            readings.append({"page": page, "image": what, "reading": reading.model_dump(mode="json")})
            ref = f"vlm{len(readings)}"
            nodes.append(
                ProcessedNode(
                    ref=ref,
                    node_type=NodeType.FIGURE,
                    level=2,
                    ordinal=len(nodes),
                    breadcrumb=SEPARATOR.join([title, f"schematic reading ({what})"]),
                    language="en",
                    content=text,
                    page_no=page,
                    source=NodeSource.VLM,
                    metadata={"image": what},
                )
            )
            seen = {t for c in reading.components for t in tags_of(" ".join(filter(None, [c.tag, c.label])))}
            extra_tags = sorted(seen - known)
            if extra_tags and known:
                flags.append(
                    Flag(
                        flag_type=FlagType.CONFLICT,
                        severity=FlagSeverity.SOFT,
                        anchor=FlagAnchor(
                            page=page, content_sha256=hashlib.sha256(f"tags|{what}".encode()).hexdigest()
                        ),
                        evidence=ConflictEvidence(
                            subject="tags read from the diagram image that the diagram file does not contain",
                            a=ConflictSide(
                                label="diagram file",
                                value=", ".join(sorted(known))[:500],
                                provenance=file_name,
                            ),
                            b=ConflictSide(
                                label="read_schematic", value=", ".join(extra_tags)[:500], provenance=what
                            ),
                        ),
                    )
                )

    catalog = graph.catalog() if graph is not None else {"diagram_format": "xsd", "sections": len(nodes)}
    if graph is not None:
        duplicates = duplicate_tags(graph)
        if duplicates:
            catalog["duplicate_tags"] = duplicates
    stores.put_cir(
        "graph.json",
        json.dumps({**catalog, "schematic_readings": readings}, ensure_ascii=False).encode("utf-8"),
    )
    revision = REVISION.search(title)
    fields = DocumentFields(
        title=title,
        doc_kind=DocKind.SCHEMA if kind == "xsd" else DocKind.DIAGRAM,
        source_origin=folder.source_origin,
        trust_tier=folder.trust_tier,
        test_plan_id=folder.test_plan_id,
        test_run_id=folder.test_run_id,
        hardware_item=folder.hardware_item,
        revision_marker=revision.group(1) if revision else None,
        language="en",
        page_count=len(graph.pages) if graph is not None else None,
        catalog=catalog,
    )
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.E,
        parser_version=PARSER_VERSION,
        cir_uri=cir_uri,
        document=fields,
        nodes=[n.model_copy(update={"ordinal": i}) for i, n in enumerate(nodes)],
        assets=assets,
        mentions=mentions,
        flags=flags,
    )
