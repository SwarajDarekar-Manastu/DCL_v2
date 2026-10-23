"""SVG, Visio and DXF diagrams → ``Graph`` (Lead ruling 2026-10-23: Route E also reads SVG, ``.vsdx``, DXF).

- SVG: every ``<text>`` (its ``<tspan>`` lines joined) is a labeled component at its position; a ``<switch>``
  keeps the English variant (``systemLanguage="en"``, else the variant without a language); ``<g>`` layers
  and groups (``inkscape:label`` or ``id``) are groups; ``<title>``/``<desc>`` of the drawing are notes.
  SVG carries no connections, so the incomplete-graph checks do not apply.
- Visio (``.vsdx``, a ZIP of XML parts): pages from ``visio/pages/pages.xml`` and its relationships; shapes
  with their text and master name (``Dynamic connector``, ``Router``); group shapes hold their sub-shapes;
  a shape glued by ``<Connect FromCell="BeginX"|"EndX">`` is a connector from its begin shape to its end
  shape, labeled by its own text; arrows from ``BeginArrow``/``EndArrow``.
- DXF (ezdxf): layers with entity counts, ``TEXT``/``MTEXT``/``ATTRIB`` strings as components on their layer
  (layers are groups), ``DIMENSION`` measurements, block inserts, ``ACAD_TABLE`` cell texts; drawing units
  from ``$INSUNITS``.
"""

import io
import re
import zipfile
from collections import Counter, defaultdict
from posixpath import dirname, join, normpath

from lxml import etree

from backend.routes.e_diagrams.drawio import DiagramError, parse_xml, safe_parser
from backend.routes.e_diagrams.graph import Component, Connection, Graph, Group, Note, Page

SVG = "{http://www.w3.org/2000/svg}"
INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"
VISIO = "{http://schemas.microsoft.com/office/visio/2012/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
INSUNITS = {0: None, 1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 14: "dm"}
MAX_VSDX_PART = 50 * 1024 * 1024


def _local(tag) -> str:
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


def _float(value, default: float = 0.0) -> float:
    try:
        return float(re.sub(r"[^\d.eE+-]", "", str(value)) or default)
    except ValueError:
        return default


# ---------------------------------------------------------------- SVG


def _svg_choice(switch):
    children = [c for c in switch if isinstance(c.tag, str)]
    for child in children:
        languages = [
            x.strip().split("-")[0].casefold() for x in (child.get("systemLanguage") or "").split(",")
        ]
        if "en" in languages:
            return child
    return next((c for c in children if not c.get("systemLanguage")), children[0] if children else None)


def parse_svg(data: bytes) -> Graph:
    root = parse_xml(data)
    if _local(root.tag) != "svg":
        raise DiagramError(f"not an SVG file (root element {_local(root.tag)})")
    graph = Graph("svg", pages=[Page(1, "Drawing")], edge_semantics=False)
    counter = 0

    def walk(element, group: str | None) -> None:
        nonlocal counter
        for child in element:
            name = _local(child.tag)
            if name == "switch":
                chosen = _svg_choice(child)
                if chosen is not None:
                    walk_one(chosen, group)
                continue
            walk_one(child, group)

    def walk_one(child, group: str | None) -> None:
        nonlocal counter
        name = _local(child.tag)
        if name in ("defs", "metadata", "style", "script", "symbol", "clipPath", "mask"):
            return
        if name == "text":
            lines = [" ".join(t.split()) for t in _text_lines(child)]
            label = " ".join(line for line in lines if line)
            if label:
                counter += 1
                graph.components.append(
                    Component(
                        child.get("id") or f"text{counter}",
                        label,
                        "text label",
                        1,
                        group,
                        child.sourceline,
                        (_float(child.get("x")), _float(child.get("y")), 0.0, 0.0),
                    )
                )
                if group is not None:
                    groups[group].members.append(graph.components[-1].id)
            return
        if name == "g":
            gid = child.get(INKSCAPE_LABEL) or child.get("id")
            if gid and gid not in groups:
                groups[gid] = Group(gid, child.get(INKSCAPE_LABEL) or "", 1, [], child.sourceline)
            walk(child, gid or group)
            return
        if name in ("title", "desc") and child.getparent() is root:
            text = " ".join("".join(child.itertext()).split())
            if text:
                graph.notes.append(Note(text, 1, child.sourceline))
            return
        walk(child, group)

    groups: dict[str, Group] = {}
    walk(root, None)
    graph.groups = [g for g in groups.values() if g.members]
    return graph


def _text_lines(text_element) -> list[str]:
    spans = [s for s in text_element if _local(s.tag) == "tspan"]
    if not spans:
        return ["".join(text_element.itertext())]
    head = (text_element.text or "").strip()
    return ([head] if head else []) + ["".join(s.itertext()) for s in spans]


# ---------------------------------------------------------------- Visio


def _zip_xml(archive: zipfile.ZipFile, name: str):
    info = archive.getinfo(name)
    if info.file_size > MAX_VSDX_PART:
        raise DiagramError(f"{name} is larger than {MAX_VSDX_PART} bytes")
    return etree.fromstring(archive.read(name), safe_parser())


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    rels_name = join(dirname(part), "_rels", part.rsplit("/", 1)[-1] + ".rels")
    if rels_name not in archive.namelist():
        return {}
    root = _zip_xml(archive, rels_name)
    return {
        r.get("Id"): normpath(join(dirname(part), r.get("Target", "")))
        for r in root.iter(f"{REL}Relationship")
    }


def _cell(shape, name: str) -> str | None:
    for cell in shape.findall(f"{VISIO}Cell"):
        if cell.get("N") == name:
            return cell.get("V")
    return None


def _shape_text(shape) -> str:
    text = shape.find(f"{VISIO}Text")
    return " ".join("".join(text.itertext()).split()) if text is not None else ""


def parse_vsdx(data: bytes) -> Graph:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DiagramError(f"not a Visio package: {exc}") from exc
    with archive:
        names = set(archive.namelist())
        if "visio/pages/pages.xml" not in names:
            raise DiagramError("not a Visio package: visio/pages/pages.xml missing")
        masters: dict[str, str] = {}
        if "visio/masters/masters.xml" in names:
            for master in _zip_xml(archive, "visio/masters/masters.xml").iter(f"{VISIO}Master"):
                masters[master.get("ID", "")] = master.get("NameU") or master.get("Name") or ""
        pages_root = _zip_xml(archive, "visio/pages/pages.xml")
        page_rels = _rels(archive, "visio/pages/pages.xml")
        graph = Graph("visio")
        for number, page in enumerate(pages_root.iter(f"{VISIO}Page"), start=1):
            if page.get("Background") == "1":
                continue
            part = (
                page_rels.get(page.find(f"{VISIO}Rel").get(R_ID))
                if page.find(f"{VISIO}Rel") is not None
                else None
            )
            graph.pages.append(Page(number, page.get("NameU") or page.get("Name") or f"Page-{number}"))
            if part is None or part not in names:
                continue
            _vsdx_page(_zip_xml(archive, part), number, masters, graph)
    return graph


def _vsdx_page(content, number: int, masters: dict[str, str], graph: Graph) -> None:
    shapes: dict[str, tuple] = {}

    def collect(container, group: str | None, inherited: str | None) -> None:
        for shape in container.findall(f"{VISIO}Shape"):
            sid = f"{number}:{shape.get('ID')}"
            master = masters.get(shape.get("Master", "")) or inherited
            shapes[sid] = (shape, group, master)
            inner = shape.find(f"{VISIO}Shapes")
            if inner is not None:
                collect(inner, sid, master if shape.get("Type") != "Group" else None)

    top = content.find(f"{VISIO}Shapes")
    if top is not None:
        collect(top, None, None)
    ends: dict[str, dict[str, str]] = defaultdict(dict)
    connects = content.find(f"{VISIO}Connects")
    for connect in connects.findall(f"{VISIO}Connect") if connects is not None else []:
        cell = connect.get("FromCell", "")
        if cell in ("BeginX", "EndX"):
            ends[f"{number}:{connect.get('FromSheet')}"][cell] = f"{number}:{connect.get('ToSheet')}"
    groups: dict[str, Group] = {}
    for sid, (shape, group, master) in shapes.items():
        text = _shape_text(shape)
        if sid in ends or (master or "").casefold().endswith("connector"):
            begin, end = ends.get(sid, {}).get("BeginX"), ends.get(sid, {}).get("EndX")
            begin_arrow, end_arrow = _cell(shape, "BeginArrow"), _cell(shape, "EndArrow")
            # a Visio connector runs from its begin to its end; arrows are usually inherited from the master,
            # so only explicit "no arrow at either end" makes it undirected
            directed = not (begin_arrow in ("0", None) and end_arrow == "0")
            if _float(begin_arrow) and not _float(end_arrow) and end_arrow is not None:
                begin, end = end, begin
            graph.connections.append(Connection(sid, begin, end, number, text, directed, None))
            continue
        if shape.get("Type") == "Group":
            groups[sid] = Group(sid, text or (master or ""), number, [])
        x, y = _float(_cell(shape, "PinX")), _float(_cell(shape, "PinY"))
        width, height = _float(_cell(shape, "Width")), _float(_cell(shape, "Height"))
        if group is not None and shape.get("Type") != "Group" and not text:
            continue  # sub-shapes of a stencil (the router's drawing parts)
        graph.components.append(
            Component(sid, text, master or "shape", number, group, None, (x, y, width, height))
        )
    for component in graph.components:
        if component.group in groups:
            groups[component.group].members.append(component.id)
    graph.groups += list(groups.values())


# ---------------------------------------------------------------- DXF


def parse_dxf(data: bytes) -> tuple[Graph, object]:
    """(graph, ezdxf document for rendering)."""
    from ezdxf import recover
    from ezdxf.lldxf.const import DXFStructureError

    try:
        document, _auditor = recover.read(io.BytesIO(data))
    except (DXFStructureError, ValueError, OSError) as exc:
        raise DiagramError(f"DXF not readable: {exc}") from exc
    modelspace = document.modelspace()
    units = INSUNITS.get(document.header.get("$INSUNITS", 0))
    graph = Graph("dxf", pages=[Page(1, "Model")], edge_semantics=False)
    counts: dict[str, Counter] = defaultdict(Counter)
    dimensions: list[str] = []
    inserts: Counter = Counter()
    tables: list[list[str]] = []
    index = 0

    def add_text(layer: str, text: str, position) -> None:
        nonlocal index
        text = " ".join(text.split())
        if not text:
            return
        index += 1
        point = (float(position[0]), float(position[1]), 0.0, 0.0) if position is not None else None
        graph.components.append(Component(f"t{index}", text, "text", 1, f"layer:{layer}", None, point))

    for entity in modelspace:
        kind = entity.dxftype()
        layer = entity.dxf.get("layer", "0")
        counts[layer][kind] += 1
        if kind == "TEXT":
            add_text(layer, entity.plain_text(), entity.dxf.get("insert"))
        elif kind == "MTEXT":
            add_text(layer, entity.plain_text(), entity.dxf.get("insert"))
        elif kind == "DIMENSION":
            try:
                measurement = entity.get_measurement()
                value = f"{float(measurement):.4g}" if not hasattr(measurement, "x") else str(measurement)
            except (AttributeError, TypeError, ValueError):
                value = "?"
            override = entity.dxf.get("text", "")
            shown = override.replace("<>", value) if override and override != "<>" else value
            dimensions.append(f"{shown}{' ' + units if units and shown != '?' else ''} (layer {layer})")
        elif kind == "INSERT":
            inserts[entity.dxf.name] += 1
            for attrib in getattr(entity, "attribs", []):
                add_text(layer, f"{attrib.dxf.tag}: {attrib.dxf.text}", attrib.dxf.get("insert"))
        elif kind == "ACAD_TABLE":
            block = (
                document.blocks.get(entity.get_block_name()) if hasattr(entity, "get_block_name") else None
            )
            cells = [
                " ".join(e.plain_text().split())
                for e in (block or [])
                if e.dxftype() in ("MTEXT", "TEXT") and e.plain_text().strip()
            ]
            if cells:
                tables.append(cells)
    layers = []
    for layer in document.layers:
        name = layer.dxf.name
        entities = counts.get(name, Counter())
        layers.append(
            {
                "name": name,
                "color": layer.dxf.get("color"),
                "linetype": layer.dxf.get("linetype"),
                "off": not layer.is_on(),
                "frozen": layer.is_frozen(),
                "entities": dict(entities),
            }
        )
        members = [c.id for c in graph.components if c.group == f"layer:{name}"]
        graph.groups.append(Group(f"layer:{name}", f"Layer {name}", 1, members))
    graph.extra = {
        "units": units,
        "dxf_version": document.dxfversion,
        "layers": layers,
        "dimensions": dimensions,
        "block_inserts": dict(inserts),
        "tables": tables,
    }
    return graph, document


def dxf_texts(graph: Graph) -> list[str]:
    """Lines for the DXF summary: layers with their entities, dimensions, blocks, tables."""
    extra = graph.extra
    lines = [f"Drawing units: {extra.get('units') or 'unitless'}; DXF {extra.get('dxf_version')}"]
    layer_parts = []
    for layer in extra.get("layers", []):
        entities = ", ".join(f"{n} {k}" for k, n in sorted(layer["entities"].items())) or "empty"
        state = " (off)" if layer["off"] else ""
        layer_parts.append(f"{layer['name']}{state}: {entities}")
    lines.append("Layers: " + "; ".join(layer_parts))
    if extra.get("dimensions"):
        lines.append("Dimensions: " + "; ".join(extra["dimensions"][:100]))
    if extra.get("block_inserts"):
        lines.append("Blocks: " + ", ".join(f"{k} ×{n}" for k, n in extra["block_inserts"].items()))
    for i, cells in enumerate(extra.get("tables", []), start=1):
        lines.append(f"Table {i}: " + " | ".join(cells[:200]))
    return lines


# ---------------------------------------------------------------- XSD


XS = "{http://www.w3.org/2001/XMLSchema}"


def parse_xsd(data: bytes) -> list[dict]:
    """Section entries (file 03 §9 E.2): one per top-level element, complex type and simple type, with
    attributes, child elements, enumerations and documentation; each with its line."""
    root = parse_xml(data)
    if root.tag != f"{XS}schema":
        raise DiagramError("not an XML schema (root is not xs:schema)")

    def documentation(node) -> str:
        texts = [
            " ".join("".join(d.itertext()).split()) for d in node.findall(f"{XS}annotation/{XS}documentation")
        ]
        return " ".join(t for t in texts if t)

    sections = []
    schema_doc = documentation(root)
    if schema_doc:
        sections.append(
            {
                "kind": "schema",
                "name": root.get("targetNamespace") or "schema",
                "doc": schema_doc,
                "line": root.sourceline,
                "attributes": [],
                "children": [],
                "enumerations": [],
            }
        )
    for node in root:
        local = _local(node.tag)
        if local not in ("element", "complexType", "simpleType", "attributeGroup", "group"):
            continue
        attributes = [
            f"{a.get('name') or a.get('ref')} ({a.get('type', 'inline')}"
            + (", required)" if a.get("use") == "required" else ")")
            for a in node.iter(f"{XS}attribute")
        ]
        children = [
            f"{e.get('name') or e.get('ref')}"
            + (f" ({e.get('type')})" if e.get("type") else "")
            + (
                f" [{e.get('minOccurs', '1')}..{e.get('maxOccurs', '1')}]"
                if e.get("minOccurs") or e.get("maxOccurs")
                else ""
            )
            for e in node.iter(f"{XS}element")
            if e is not node
        ]
        enumerations = [e.get("value", "") for e in node.iter(f"{XS}enumeration")]
        nested_docs = [documentation(e) for e in node.iter() if e is not node and isinstance(e.tag, str)]
        sections.append(
            {
                "kind": {"complexType": "complex type", "simpleType": "simple type"}.get(local, local),
                "name": node.get("name", "(anonymous)"),
                "type": node.get("type"),
                "doc": " ".join(filter(None, [documentation(node), *[d for d in nested_docs if d][:10]])),
                "line": node.sourceline,
                "attributes": attributes,
                "children": children,
                "enumerations": enumerations,
            }
        )
    return sections
