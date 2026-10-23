"""draw.io (file 03 §9 E.1 steps 1–3, edge cases): ``<mxfile>`` → ``Graph``.

- Each ``<diagram>`` is a page; compressed diagrams (base64 → raw deflate → URL-encoding) are decoded.
- ``vertex="1"`` cells are components: label (HTML stripped, ``<UserObject label>`` wrappers too), shape type
  from the style (``shape=mxgraph.pid.valves.gate`` → ``valve: gate``), geometry. Cells styled ``text`` are
  notes; ``edgeLabel`` children label their edge.
- ``edge="1"`` cells are connections: source, target, label, direction (``endArrow=none`` without a start
  arrow is undirected; a start arrow alone reverses it), medium from the dash on P&ID pages
  (``mxgraph.pid`` shapes; dashed = electrical, solid = fluid, configurable); other diagrams get none.
- Containers (cells that other cells name as parent, ``group``, ``swimlane``, ``container=1``) are groups; an
  edge ending on a group ends on its boundary.
- Embedded images (``shape=image`` with a data URI) are counted and returned for the vision pass.
"""

import base64
import re
import zlib
from collections.abc import Mapping
from urllib.parse import unquote

from lxml import etree

from backend.routes.e_diagrams.graph import Component, Connection, Graph, Group, Note, Page, strip_html

DEFAULT_MEDIA = {"dashed": "electrical", "solid": "fluid"}
CONTAINER_STYLES = re.compile(r"(^|;)(group|swimlane|container=1|shape=(table|tableRow))(;|$)")


class DiagramError(ValueError):
    pass


def safe_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)


def parse_xml(data: bytes) -> etree._Element:
    try:
        return etree.fromstring(data, safe_parser())
    except etree.XMLSyntaxError as exc:
        raise DiagramError(f"invalid XML: {exc}") from exc


def decode_diagram(text: str) -> bytes:
    """A compressed ``<diagram>`` body → the ``<mxGraphModel>`` XML."""
    raw = base64.b64decode(text.strip())
    try:
        inflated = zlib.decompress(raw, -15)
    except zlib.error:
        inflated = raw
    return unquote(inflated.decode("utf-8", errors="replace")).encode("utf-8")


def style_map(style: str) -> dict[str, str]:
    out = {}
    for i, part in enumerate(p for p in (style or "").split(";") if p):
        key, sep, value = part.partition("=")
        out[key] = value if sep else ("1" if i else "1")
        if not sep and i == 0:
            out["_base"] = key
    return out


def shape_kind(style: str) -> str:
    styles = style_map(style)
    shape = styles.get("shape") or styles.get("_base") or ""
    if shape.startswith("mxgraph."):
        parts = shape.split(".")
        family = parts[2] if len(parts) > 2 else parts[-1]
        detail = parts[-1] if len(parts) > 3 else ""
        family = family.rstrip("s") if family.endswith("valves") else family
        return f"{family}: {detail}".strip(": ").replace("_", " ")
    if styles.get("ellipse") or shape == "ellipse":
        return "ellipse"
    return shape or "shape"


def _box(cell) -> tuple[float, float, float, float] | None:
    geometry = cell.find("mxGeometry")
    if geometry is None:
        return None
    try:
        return tuple(float(geometry.get(k, "0") or 0) for k in ("x", "y", "width", "height"))  # type: ignore[return-value]
    except ValueError:
        return None


def _cells(model) -> list[tuple[etree._Element, dict[str, str]]]:
    """(mxCell, attributes) with ``UserObject``/``object`` wrappers merged (label and id come from them)."""
    root = model.find("root")
    if root is None:
        return []
    out = []
    for child in root:
        if not isinstance(child.tag, str):
            continue
        if child.tag == "mxCell":
            out.append((child, dict(child.attrib)))
        elif child.tag in ("UserObject", "object"):
            cell = child.find("mxCell")
            if cell is None:
                continue
            attrs = dict(cell.attrib)
            attrs["id"] = child.get("id", attrs.get("id", ""))
            attrs["value"] = child.get("label", attrs.get("value", ""))
            out.append((cell, attrs))
    return out


def parse_drawio(
    data: bytes, media: Mapping[str, str] = DEFAULT_MEDIA
) -> tuple[Graph, list[tuple[int, str, bytes]]]:
    """(graph, embedded images as (page, cell id, PNG/JPEG bytes))."""
    root = parse_xml(data)
    if root.tag == "mxGraphModel":
        diagrams = [(1, "Page-1", root, False, None)]
    elif root.tag == "mxfile":
        diagrams = []
        for number, diagram in enumerate(root.findall("diagram"), start=1):
            name = diagram.get("name") or f"Page-{number}"
            model = diagram.find("mxGraphModel")
            if model is None and (diagram.text or "").strip():
                try:
                    model = etree.fromstring(decode_diagram(diagram.text), safe_parser())
                except (ValueError, etree.XMLSyntaxError, zlib.error) as exc:
                    raise DiagramError(f"page {name}: compressed diagram not decodable: {exc}") from exc
                diagrams.append((number, name, model, True, diagram.sourceline))
                continue
            if model is not None:
                diagrams.append((number, name, model, False, diagram.sourceline))
    else:
        raise DiagramError(f"not a draw.io file (root element {root.tag})")

    graph = Graph("drawio")
    images: list[tuple[int, str, bytes]] = []
    for number, name, model, compressed, diagram_line in diagrams:
        graph.pages.append(Page(number, name))
        cells = _cells(model)
        attrs_by_id = {a.get("id", ""): a for _, a in cells}
        root_ids = {a.get("id", "") for _, a in cells if not a.get("parent")}
        layer_ids = root_ids | {
            a.get("id", "")
            for _, a in cells
            if a.get("parent") in root_ids and a.get("vertex") != "1" and a.get("edge") != "1"
        }
        parents = {a.get("parent") for _, a in cells}
        edge_ids = {a["id"] for _, a in cells if a.get("edge") == "1"}
        edge_labels: dict[str, list[str]] = {}

        def line_of(cell, compressed=compressed, diagram_line=diagram_line) -> int | None:
            """The cell's line in the file; a compressed page has only its ``<diagram>`` line."""
            return diagram_line if compressed else cell.sourceline

        for cell, attrs in cells:
            cid = attrs.get("id", "")
            if cid in layer_ids or attrs.get("vertex") != "1":
                continue
            style = attrs.get("style", "")
            label = strip_html(attrs.get("value", ""))
            parent = attrs.get("parent")
            if parent in edge_ids or "edgeLabel" in style:
                if label and parent:
                    edge_labels.setdefault(parent, []).append(label)
                continue
            styles = style_map(style)
            if "image" in styles and styles["image"].startswith("data:image/"):
                header, _, payload = styles["image"].partition(",")
                try:
                    images.append((number, cid, base64.b64decode(payload)))
                except ValueError:
                    pass
            if cid in parents or CONTAINER_STYLES.search(style):
                members = [a["id"] for _, a in cells if a.get("parent") == cid and a.get("edge") != "1"]
                graph.groups.append(Group(cid, label, number, members, line_of(cell)))
                if not label:
                    continue
            if styles.get("_base") == "text" or styles.get("text") == "1" and not styles.get("shape"):
                if label:
                    graph.notes.append(Note(label, number, line_of(cell), _box(cell), cid))
                continue
            group = parent if parent not in layer_ids and parent in attrs_by_id else None
            graph.components.append(
                Component(cid, label, shape_kind(style), number, group, line_of(cell), _box(cell), style)
            )
        pid_page = any("mxgraph.pid" in a.get("style", "") for _, a in cells)
        for cell, attrs in cells:
            if attrs.get("edge") != "1":
                continue
            style = attrs.get("style", "")
            styles = style_map(style)
            end, start = styles.get("endArrow"), styles.get("startArrow")
            source, target = attrs.get("source"), attrs.get("target")
            directed = end != "none" or (start not in (None, "none"))
            if end == "none" and start not in (None, "none"):
                source, target = target, source
            label = " ".join(
                [strip_html(attrs.get("value", "")), *edge_labels.get(attrs.get("id", ""), [])]
            ).strip()
            dashed = styles.get("dashed") == "1"
            points = [
                (float(p.get("x", 0)), float(p.get("y", 0)))
                for p in cell.iter("mxPoint")
                if p.get("as") in ("sourcePoint", "targetPoint")
            ]
            graph.connections.append(
                Connection(
                    attrs.get("id", ""),
                    source,
                    target,
                    number,
                    label,
                    directed,
                    media.get("dashed" if dashed else "solid") if pid_page else None,
                    line_of(cell),
                    style,
                    points,
                )
            )
    graph.extra["embedded_images"] = len(images)
    return graph, images
