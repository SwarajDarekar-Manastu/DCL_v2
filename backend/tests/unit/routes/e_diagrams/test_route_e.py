# ruff: noqa: E501 — the draw.io and Visio fixtures are XML whose line numbers the tests assert
"""Route E (file 03 §9 and the 2026-10-23 ruling) on synthetic diagrams and the real/web samples."""

import base64
import hashlib
import io
import json
import zipfile
import zlib
from pathlib import Path
from urllib.parse import quote

import pytest

pytest.importorskip("ezdxf")  # parse dependency group

from backend.dispatcher.contract import ProcessedDocument  # noqa: E402
from backend.dispatcher.folder_context import FolderContext  # noqa: E402
from backend.indexing.anchors import make_anchor  # noqa: E402
from backend.indexing.chunker import chunk_document  # noqa: E402
from backend.llm_engine.vision import schemas  # noqa: E402
from backend.llm_engine.vision.service import VisionOutput  # noqa: E402
from backend.postgres.enums import DocKind, FlagSeverity, FlagType, NodeType  # noqa: E402
from backend.routes.e_diagrams.route import Stores, can_handle, process_diagram  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[5] / "data" / "samples"
WEB = SAMPLES / "web"


def _sample(path: Path) -> bytes:
    """A real or web sample's bytes; skips the test when the file is not exported in this checkout."""
    if not path.is_file():
        pytest.skip(f"{path} not exported locally")
    return path.read_bytes()


FOLDER = FolderContext(root_name="APU", breadcrumb=["APU", "Test Plan 22"], path_cached="APU/Test Plan 22")

PID = """<mxfile host="test">
  <diagram name="Feed" id="p1">
    <mxGraphModel><root>
      <mxCell id="0"/>
      <mxCell id="1" parent="0"/>
      <mxCell id="grp" value="Propellant feed" style="swimlane;" vertex="1" parent="1">
        <mxGeometry x="0" y="0" width="600" height="200" as="geometry"/></mxCell>
      <mxCell id="tank" value="Tank T-1" style="shape=mxgraph.pid.vessels.tank;" vertex="1" parent="grp">
        <mxGeometry x="10" y="50" width="60" height="80" as="geometry"/></mxCell>
      <mxCell id="f" value="Filter F-101" style="shape=mxgraph.pid.filters.filter;" vertex="1" parent="grp">
        <mxGeometry x="120" y="70" width="40" height="40" as="geometry"/></mxCell>
      <UserObject label="&lt;b&gt;SV-1&lt;/b&gt;" id="sv"><mxCell style="shape=mxgraph.pid.valves.solenoid_valve;" vertex="1" parent="grp">
        <mxGeometry x="220" y="70" width="40" height="40" as="geometry"/></mxCell></UserObject>
      <mxCell id="pt" value="PT-101 (0–250 bar)" style="ellipse;" vertex="1" parent="1">
        <mxGeometry x="300" y="0" width="40" height="40" as="geometry"/></mxCell>
      <mxCell id="psu" value="PSU-2" style="rounded=0;" vertex="1" parent="1">
        <mxGeometry x="220" y="160" width="40" height="30" as="geometry"/></mxCell>
      <mxCell id="note" value="All lines 1/4 inch" style="text;html=1;" vertex="1" parent="1">
        <mxGeometry x="400" y="150" width="100" height="20" as="geometry"/></mxCell>
      <mxCell id="e1" value="" style="endArrow=classic;" edge="1" parent="1" source="tank" target="f"/>
      <mxCell id="e2" value="" style="endArrow=classic;" edge="1" parent="1" source="f" target="sv">
        <mxGeometry relative="1" as="geometry"/></mxCell>
      <mxCell id="e2l" value="1/4 in" style="edgeLabel;html=1;" vertex="1" connectable="0" parent="e2">
        <mxGeometry x="0.1" relative="1" as="geometry"/></mxCell>
      <mxCell id="e3" value="24 V" style="dashed=1;endArrow=classic;" edge="1" parent="1" source="psu" target="sv"/>
      <mxCell id="e4" value="sense" style="endArrow=none;" edge="1" parent="1" source="pt" target="sv"/>
    </root></mxGraphModel>
  </diagram>
  <diagram name="Spare" id="p2">COMPRESSED</diagram>
</mxfile>"""

SPARE = (
    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="a" value="Heater HPC-1" vertex="1" parent="1"><mxGeometry x="0" y="0" width="40" height="40" '
    'as="geometry"/></mxCell></root></mxGraphModel>'
)


def _compressed(xml: str) -> str:
    deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = deflate.compress(quote(xml).encode()) + deflate.flush()
    return base64.b64encode(raw).decode()


def _pid() -> bytes:
    return PID.replace("COMPRESSED", _compressed(SPARE)).encode()


class FakeVision:
    def __init__(self, tags=("SV-1",)):
        self.tags, self.calls = tags, 0

    def read_schematic(self, image, **kw):
        self.calls += 1
        reading = schemas.SchematicReading.model_validate(
            {
                "components": [{"tag": t, "type": "valve", "label": None} for t in self.tags],
                "connections": [],
                "notes": None,
            }
        )
        return VisionOutput(reading, "gemini-3.8-flash", "read_schematic.v1", "h", False)


def _run(name, data, cir=None, assets=None, **kwargs) -> ProcessedDocument:
    cir = {} if cir is None else cir
    assets = {} if assets is None else assets
    processed = process_diagram(
        data,
        blob_sha256=hashlib.sha256(data).hexdigest(),
        file_name=name,
        folder=FOLDER,
        stores=Stores(
            put_cir=lambda k, v: cir.setdefault(k, v) and k,
            put_asset=lambda k, v: assets.setdefault(k, v) and f"s3://dcl-assets/{k}",
        ),
        **kwargs,
    )
    assert ProcessedDocument.model_validate_json(processed.model_dump_json()) == processed
    for node in chunk_document(processed, count_tokens=lambda texts: [len(t) // 4 + 1 for t in texts]):
        make_anchor("00000000-0000-0000-0000-000000000001", node)
    return processed


def _component(processed, label):
    return next(
        n
        for n in processed.nodes
        if n.node_type == NodeType.DIAGRAM_COMPONENT and n.content.startswith(label)
    )


def test_drawio_graph_catalog_and_pages():
    cir = {}
    processed = _run("Thruster config - Rev C.drawio", _pid(), cir)
    catalog = processed.document.catalog

    assert processed.document.doc_kind == DocKind.DIAGRAM and processed.document.revision_marker == "Rev C"
    assert [p["name"] for p in catalog["pages"]] == ["Feed", "Spare"]
    assert {n["label"] for n in catalog["nodes"]} == {
        "Tank T-1",
        "Filter F-101",
        "SV-1",
        "PT-101 (0–250 bar)",
        "PSU-2",
        "Propellant feed",
        "Heater HPC-1",
    }
    assert catalog["groups"][0]["label"] == "Propellant feed"
    assert set(catalog["groups"][0]["members"]) == {"tank", "f", "sv"}
    assert {(e["source"], e["target"], e.get("label", "")) for e in catalog["edges"]} >= {
        ("f", "sv", "1/4 in"),
        ("psu", "sv", "24 V"),
    }
    assert json.loads(cir["graph.json"])["diagram_format"] == "drawio"
    spare = next(n for n in processed.nodes if n.node_type == NodeType.DIAGRAM_SUMMARY and n.page_no == 2)
    assert "Heater HPC-1" in spare.content and spare.line_start == 29


def test_component_nodes_carry_their_neighbourhood_and_tags():
    processed = _run("pid.drawio", _pid())
    valve = _component(processed, "SV-1")

    assert valve.content.startswith("SV-1 (valve: solenoid valve): from Filter F-101 (1/4 in) [fluid]")
    assert "from PSU-2 (24 V) [electrical]" in valve.content
    assert "connected to PT-101 (0–250 bar) (sense)" in valve.content
    assert valve.content.endswith(". Part of Propellant feed")
    assert valve.page_no == 1 and valve.line_start == 12
    mentions = {(m.kind, m.surface) for m in processed.mentions}
    assert {("tag", "SV-1"), ("tag", "F-101"), ("tag", "PT-101"), ("quantity", "0–250 bar")} <= mentions
    summary = processed.nodes[0]
    assert "Tank T-1 → Filter F-101" in summary.content and "Notes: All lines 1/4 inch" in summary.content


def test_render_and_read_schematic_cross_check(tmp_path):
    assets = {}
    vision = FakeVision(tags=("SV-1", "SV-9"))
    processed = _run("pid.drawio", _pid(), assets=assets, vision=vision, cloud_allowed=True)

    renders = [a for a in processed.assets if a.kind == "diagram_render"]
    assert [a.page_no for a in renders] == [1, 2] and vision.calls == 2
    assert assets[renders[0].minio_uri.removeprefix("s3://dcl-assets/")].startswith(b"\x89PNG")
    assert processed.nodes[0].asset_ref == "render:1"
    conflict = next(f for f in processed.flags if f.flag_type == FlagType.CONFLICT and f.anchor.page == 1)
    assert conflict.severity == FlagSeverity.SOFT and conflict.evidence.b.value == "SV-9"
    assert any(n.node_type == NodeType.FIGURE and n.source == "vlm" for n in processed.nodes)


def test_no_vision_without_cloud_permission():
    vision = FakeVision()
    _run("pid.drawio", _pid(), vision=vision, cloud_allowed=False)
    assert vision.calls == 0


def test_invalid_xml_is_a_hard_parse_failure():
    processed = _run("broken.drawio", b"<mxfile><diagram><mxGraphModel>")
    assert processed.flags[0].flag_type == FlagType.PARSE_FAILURE and processed.has_hard_flags


def test_mostly_unlabeled_edges_mark_the_graph_incomplete():
    cells = "".join(
        f'<mxCell id="v{i}" value="N{i}" vertex="1" parent="1"/><mxCell id="e{i}" edge="1" parent="1" '
        f'source="v{i}" target="v{i + 1}"/>'
        for i in range(5)
    )
    xml = f'<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>{cells}<mxCell id="v5" value="N5" vertex="1" parent="1"/></root></mxGraphModel>'
    processed = _run("chain.drawio", xml.encode())
    subjects = [f.evidence.subject for f in processed.flags]

    assert subjects == ["diagram graph incomplete: unlabeled edges"]
    assert processed.flags[0].evidence.relation == "check_failed"
    assert processed.flags[0].severity == FlagSeverity.SOFT


def test_xsd_sections_and_enumerations():
    xsd = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="TestProcedure">
    <xs:annotation><xs:documentation>One ECSS-M-50B test procedure.</xs:documentation></xs:annotation>
    <xs:complexType>
      <xs:sequence><xs:element name="Step" type="xs:string" maxOccurs="unbounded"/></xs:sequence>
      <xs:attribute name="status" type="StatusType" use="required"/>
    </xs:complexType>
  </xs:element>
  <xs:simpleType name="StatusType">
    <xs:restriction base="xs:string">
      <xs:enumeration value="draft"/><xs:enumeration value="approved"/>
    </xs:restriction>
  </xs:simpleType>
</xs:schema>"""
    processed = _run("ECSS-M-50B.xsd", xsd)

    assert processed.document.doc_kind == DocKind.SCHEMA
    first, second = processed.nodes
    assert first.breadcrumb == "ECSS-M-50B › element TestProcedure"
    assert (
        "One ECSS-M-50B test procedure." in first.content and "status (StatusType, required)" in first.content
    )
    assert "Step (xs:string) [1..unbounded]" in first.content
    assert second.content.endswith("Allowed values: draft, approved") and second.line_start == 10
    assert [m.surface for m in processed.mentions if m.kind == "enumeration"] == ["draft", "approved"]


def test_svg_english_variant_and_layers():
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
  <title>Feed schematic</title>
  <g id="layer1" inkscape:label="Labels">
    <switch>
      <text systemLanguage="de" x="1" y="2">Ventil</text>
      <text systemLanguage="en" x="1" y="2"><tspan>Main</tspan><tspan>valve</tspan></text>
      <text x="1" y="2">fallback</text>
    </switch>
    <text x="5" y="6">PT-101</text>
  </g>
</svg>"""
    processed = _run("feed.svg", svg)
    labels = [n["label"] for n in processed.document.catalog["nodes"]]

    assert labels == ["Main valve", "PT-101"]
    assert processed.flags == []
    assert "Notes: Feed schematic" in processed.nodes[0].content
    assert _component(processed, "Main valve").content == "Main valve (text label). Part of Labels"


def test_svg_is_rendered_and_read_by_read_schematic():
    pytest.importorskip("resvg_py")
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" width="300" height="120" viewBox="0 0 300 120">
  <rect x="10" y="10" width="80" height="40" fill="none" stroke="black"/>
  <text x="20" y="35">SV-1</text>
  <image href="../../etc/secret.png" x="0" y="0" width="10" height="10"/>
</svg>"""
    assets = {}
    vision = FakeVision(tags=("SV-1",))
    processed = _run("valve.svg", svg, assets=assets, vision=vision, cloud_allowed=True)

    render = next(a for a in processed.assets if a.kind == "diagram_render")
    png = assets[render.minio_uri.removeprefix("s3://dcl-assets/")]
    assert png.startswith(b"\x89PNG") and render.page_no == 1
    from PIL import Image

    assert Image.open(io.BytesIO(png)).size == (550, 220)  # 300 units / 60 per inch at 110 dpi
    assert vision.calls == 1 and processed.nodes[0].asset_ref == "render:1"
    assert not any(f.flag_type == FlagType.CONFLICT for f in processed.flags)


def _vsdx(pages: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    ns = "http://schemas.microsoft.com/office/visio/2012/main"
    rns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "visio/pages/pages.xml",
            f"<Pages xmlns='{ns}' xmlns:r='{rns}'>"
            + "".join(
                f"<Page ID='{i}' NameU='{name}'><Rel r:id='rId{i}'/></Page>"
                for i, name in enumerate(pages, 1)
            )
            + "</Pages>",
        )
        archive.writestr(
            "visio/pages/_rels/pages.xml.rels",
            "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
            + "".join(f"<Relationship Id='rId{i}' Target='page{i}.xml'/>" for i in range(1, len(pages) + 1))
            + "</Relationships>",
        )
        archive.writestr(
            "visio/masters/masters.xml",
            f"<Masters xmlns='{ns}'><Master ID='2' NameU='Dynamic connector'/><Master ID='5' NameU='Valve'/></Masters>",
        )
        for i, body in enumerate(pages.values(), 1):
            archive.writestr(f"visio/pages/page{i}.xml", f"<PageContents xmlns='{ns}'>{body}</PageContents>")
    return buffer.getvalue()


def test_visio_connector_ends():
    page = (
        "<Shapes><Shape ID='1' Master='5'><Text>Valve V-1</Text></Shape><Shape ID='2'><Text>Tank</Text></Shape>"
        "<Shape ID='3' Master='2'><Text>feed line</Text></Shape></Shapes>"
        "<Connects><Connect FromSheet='3' FromCell='BeginX' ToSheet='2'/><Connect FromSheet='3' FromCell='EndX' ToSheet='1'/></Connects>"
    )
    processed = _run("plant.vsdx", _vsdx({"Plant": page}))
    edges = processed.document.catalog["edges"]

    assert [(e["source"], e["target"], e["label"]) for e in edges] == [("1:2", "1:1", "feed line")]
    assert "Tank → Valve V-1 (feed line)" in processed.nodes[0].content
    assert _component(processed, "Valve V-1").content == "Valve V-1 (Valve): from Tank (feed line)"


def test_dxf_layers_texts_dimensions():
    import ezdxf

    document = ezdxf.new("R2018", setup=True)
    document.header["$INSUNITS"] = 4
    document.layers.add("NOZZLE")
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (50, 0), dxfattribs={"layer": "NOZZLE"})
    modelspace.add_text("Throat Ø 3.2", dxfattribs={"layer": "NOZZLE"}).set_placement((10, 5))
    dimension = modelspace.add_linear_dim(base=(0, -10), p1=(0, 0), p2=(50, 0), dxfattribs={"layer": "DIMS"})
    dimension.render()
    stream = io.StringIO()
    document.write(stream)
    processed = _run("nozzle.dxf", stream.getvalue().encode())
    summary = processed.nodes[0].content

    assert "Drawing units: mm" in summary
    assert "NOZZLE: 1 LINE, 1 TEXT" in summary
    assert "Dimensions: 50 mm (layer DIMS)" in summary
    assert _component(processed, "Throat Ø 3.2").content == "Throat Ø 3.2 (text). Part of Layer NOZZLE"
    assert [a.kind for a in processed.assets] == ["diagram_render"]


def test_can_handle():
    assert can_handle(b"<mxfile host=", "x.xml")
    assert can_handle(b"PK\x03\x04", "a.vsdx") and can_handle(b"  0\nSECTION", "a.dxf")
    assert not can_handle(b"PK\x03\x04", "a.zip")


# ---------------------------------------------------------------- real and web samples

REV_C = SAMPLES / "E6" / "Test Plan 22" / "THruster config - Rev C.drawio"


def test_thruster_config_rev_c():
    processed = _run(REV_C.name, _sample(REV_C))

    assert processed.document.revision_marker == "Rev C" and len(processed.document.catalog["pages"]) == 2
    text = "\n".join(n.content for n in processed.nodes)
    for label in (
        "Injector Flange",
        "Retainer Plate",
        "Mesh (Monel 400)",
        "Catalyst 5% Pt on Al (La Stabilised)",
        "60 mm",
    ):
        assert label in text
    assert all(f.severity == FlagSeverity.SOFT for f in processed.flags)


def test_web_samples_line_tags_svg_visio_dxf():
    pid = _run("pid_1.drawio", _sample(WEB / "drawio" / "pid_1.drawio"))
    assert {"N-OZ-301", "N-WC-303", "N-RO-302"} <= {m.surface for m in pid.mentions if m.kind == "tag"}

    svg = _run("V-2.svg", _sample(WEB / "svg" / "V-2_rocket_diagram_English_labels.svg"))
    labels = [n["label"] for n in svg.document.catalog["nodes"]]
    assert "Liquid oxygen" in labels and "Alcohol-water mixture" in labels
    assert not any("oxigén" in label for label in labels)

    visio = _run("test4_connectors.vsdx", _sample(WEB / "vsdx" / "test4_connectors.vsdx"))
    assert "Shape A → Shape B (A to B)" in "\n".join(n.content for n in visio.nodes)

    dxf = _run("three_layers.dxf", _sample(WEB / "dxf" / "three_layers.dxf"))
    assert "Layer1: 1 LWPOLYLINE; Layer2: 1 LWPOLYLINE; Layer3: 1 LWPOLYLINE" in dxf.nodes[0].content
