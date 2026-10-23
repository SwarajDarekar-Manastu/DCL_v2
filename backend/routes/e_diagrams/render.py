"""PNG renders for the UI and for ``read_schematic`` (file 03 §9 E.1 step 6).

There is no draw.io CLI on the workers, so a draw.io page is drawn from its parsed geometry with matplotlib
(boxes, labels, connections, notes); a DXF modelspace is drawn with ezdxf's matplotlib backend. Both use the
object-oriented ``Figure`` API, so no global pyplot state is touched. An SVG is rasterized by resvg (no system
libraries), English ``<switch>`` variants first, at the draw.io size rule: 1 inch per 60 drawing units at
``RENDER_DPI``, the long side at most ``MAX_SIDE_INCHES`` and at least 4 inches.
"""

import io
import tempfile

from backend.routes.e_diagrams.graph import Graph

RENDER_DPI = 110
MAX_SIDE_INCHES = 16.0


def _figure(width: float, height: float):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    scale = min(MAX_SIDE_INCHES / max(width, 1.0), MAX_SIDE_INCHES / max(height, 1.0), 1 / 60)
    figure = Figure(figsize=(max(width * scale, 4.0), max(height * scale, 3.0)), dpi=RENDER_DPI)
    FigureCanvasAgg(figure)
    return figure


def _png(figure) -> bytes:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    return buffer.getvalue()


def render_drawio_page(graph: Graph, page: int) -> bytes | None:
    from matplotlib.patches import Rectangle

    components = [c for c in graph.components if c.page == page and c.box]
    notes = [n for n in graph.notes if n.page == page and n.box]
    if not components and not notes:
        return None
    boxes = [c.box for c in components] + [n.box for n in notes]
    x0 = min(b[0] for b in boxes) - 20
    y0 = min(b[1] for b in boxes) - 20
    x1 = max(b[0] + b[2] for b in boxes) + 20
    y1 = max(b[1] + b[3] for b in boxes) + 20
    figure = _figure(x1 - x0, y1 - y0)
    axes = figure.add_axes((0, 0, 1, 1))
    axes.set_xlim(x0, x1)
    axes.set_ylim(y1, y0)  # draw.io: origin top left
    axes.axis("off")
    centers = {}
    for component in components:
        x, y, w, h = component.box
        centers[component.id] = (x + w / 2, y + h / 2)
        axes.add_patch(Rectangle((x, y), w, h, fill=False, linewidth=0.8))
        if component.label:
            axes.text(x + w / 2, y + h / 2, component.label, ha="center", va="center", fontsize=7, wrap=True)
    for note in notes:
        x, y, w, h = note.box
        axes.text(x + w / 2, y + h / 2, note.text, ha="center", va="center", fontsize=7)
    for edge in graph.connections:
        if edge.page != page:
            continue
        a = centers.get(edge.source) or (edge.points[0] if edge.points else None)
        b = centers.get(edge.target) or (edge.points[-1] if edge.points else None)
        if a is None or b is None:
            continue
        style = "--" if "dashed=1" in edge.style else "-"
        if edge.directed:
            axes.annotate("", xy=b, xytext=a, arrowprops={"arrowstyle": "->", "linestyle": style, "lw": 0.8})
        else:
            axes.plot([a[0], b[0]], [a[1], b[1]], style, linewidth=0.8, color="black")
        if edge.label:
            axes.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, edge.label, fontsize=6, color="darkblue")
    return _png(figure)


def render_dxf(document) -> bytes | None:
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    modelspace = document.modelspace()
    if not len(modelspace):
        return None
    figure = _figure(1000, 700)
    axes = figure.add_axes((0, 0, 1, 1))
    Frontend(RenderContext(document), MatplotlibBackend(axes)).draw_layout(modelspace, finalize=True)
    return _png(figure)


def _length(value: str | None) -> float | None:
    import re

    match = re.match(r"\s*([\d.]+)\s*(px|pt|mm|cm|in)?\s*$", value or "")
    if not match:
        return None
    factor = {"px": 1.0, None: 1.0, "pt": 96 / 72, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0}[
        match.group(2)
    ]
    return float(match.group(1)) * factor


def svg_size(root) -> tuple[float, float] | None:
    width, height = _length(root.get("width")), _length(root.get("height"))
    if width and height:
        return width, height
    box = (root.get("viewBox") or "").replace(",", " ").split()
    if len(box) == 4:
        try:
            return float(box[2]), float(box[3])
        except ValueError:
            return None
    return None


def render_svg(data: bytes, size: tuple[float, float] | None) -> bytes | None:
    import resvg_py

    width, height = size or (800.0, 600.0)
    longest = max(width, height, 1.0)
    pixels = min(longest * RENDER_DPI / 60, MAX_SIDE_INCHES * RENDER_DPI)
    pixels = max(pixels, 4.0 * RENDER_DPI)
    zoom = pixels / longest
    with tempfile.TemporaryDirectory() as empty:  # relative image links resolve to nothing on the worker
        try:
            png = resvg_py.svg_to_bytes(
                svg_string=data.decode("utf-8", errors="replace"),
                background="#ffffff",
                zoom=zoom,
                languages=["en"],
                resources_dir=empty,
            )
        except ValueError:
            return None
    return bytes(png) if png else None
