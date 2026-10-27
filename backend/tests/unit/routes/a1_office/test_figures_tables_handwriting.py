import io
import re

import pytest

pytest.importorskip("pypdfium2")
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from backend.dispatcher.contract import PageBox, ProcessedNode  # noqa: E402
from backend.llm_engine.vision.schemas import HandwritingDoubt, SchematicReading  # noqa: E402
from backend.postgres.enums import AssetKind, FlagSeverity, FlagType, NodeSource, NodeType  # noqa: E402
from backend.routes.a1_office.figures import read_figures, render_schematic  # noqa: E402
from backend.routes.a1_office.handwriting import page_doubts  # noqa: E402
from backend.routes.a1_office.tables_qa import (  # noqa: E402
    agreement,
    check_tables,
    grid,
    parse_cells,
    qa_reasons,
    units_by_column,
)
from backend.tests.unit.routes.vision_readings import with_image_metadata  # noqa: E402

SHA = "c" * 64


def one_page_pdf(lines: list[tuple[float, float, str]]) -> bytes:
    """lines: (x_pt, y_pt from the top, text) on an A4 page."""
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    for x, y, text in lines:
        page.drawString(x, A4[1] - y, text)
    page.save()
    return buffer.getvalue()


PDF = one_page_pdf(
    [(60, 100, "TEST CELL RUN SHEET"), (60, 200, "Injector orifice dia (mm):"), (60, 300, "Tare weight (g):")]
)


def node(ref, node_type, content="", box=(0.1, 0.1, 0.5, 0.2), page=1, **kw):
    return ProcessedNode(
        ref=ref,
        node_type=node_type,
        ordinal=kw.pop("ordinal", 0),
        breadcrumb=kw.pop("breadcrumb", "Run sheet"),
        content=content,
        page_no=page,
        bboxes=[PageBox(page_no=page, x0=box[0], y0=box[1], x1=box[2], y1=box[3])],
        source=kw.pop("source", NodeSource.PRINTED),
        **kw,
    )


# ---------------------------------------------------------------- tables

SPANNED = (
    '<table><thead><tr><th rowspan="2">Run</th><th colspan="2">Pressure (bar)</th><th>Thrust [N]</th></tr>'
    "<tr><th>peak</th><th>steady</th><th>mean</th></tr></thead>"
    "<tbody><tr><td>T01</td><td>52.4</td><td>12.4</td><td>1.0</td></tr></tbody></table>"
)


def test_grid_expands_row_and_column_spans():
    assert grid(parse_cells(SPANNED)) == [
        ["Run", "Pressure (bar)", "Pressure (bar)", "Thrust [N]"],
        ["Run", "peak", "steady", "mean"],
        ["T01", "52.4", "12.4", "1.0"],
    ]


def test_units_by_column_from_header_cells():
    assert units_by_column(parse_cells(SPANNED)) == [None, "bar", "bar", "N"]


@pytest.mark.parametrize(
    ("html", "ocr", "reasons"),
    [
        (SPANNED, None, []),
        (
            "<table><tr><td>1</td><td>2</td></tr><tr><td>3</td></tr></table>",
            None,
            ["ragged_rows", "numeric_without_header"],
        ),
        (
            "<table><tr><th>a</th><th>b</th></tr><tr><td></td><td></td></tr><tr><td></td><td></td></tr></table>",
            None,
            ["mostly_empty"],
        ),
        (SPANNED, 0.6, ["low_ocr_page"]),
    ],
)
def test_table_qa_reasons(html, ocr, reasons):
    assert qa_reasons(html, ocr) == reasons


def test_agreement_on_shape_and_numeric_cells():
    other = SPANNED.replace("12.4", "12.9")
    assert agreement(SPANNED, SPANNED) == (True, 1.0)
    same_shape, share = agreement(SPANNED, other)
    assert same_shape and share == pytest.approx(2 / 3)


def table_reading(html, confidence):
    return {
        "html_table": html,
        "n_rows": 3,
        "n_cols": 4,
        "header_rows": 2,
        "units_by_column": [],
        "confidence": confidence,
    }


def test_clean_table_is_not_sent_to_the_vlm(fake_vision):
    vision = fake_vision()
    result = check_tables(
        [node("tab1", NodeType.TABLE, SPANNED)],
        pdf_bytes=PDF,
        page_ocr={1: None},
        vision=vision,
        context="x",
        doc_id=None,
        cloud_allowed=True,
    )
    assert vision.calls == [] and result.flags == []
    assert result.nodes[0].metadata["units_by_column"] == [None, "bar", "bar", "N"]


def test_agreeing_vlm_table_with_higher_confidence_replaces_a_low_ocr_table(fake_vision):
    vision = fake_vision(read_table_image=table_reading(SPANNED.replace("T01", "T01 "), 0.95))
    result = check_tables(
        [node("tab1", NodeType.TABLE, SPANNED)],
        pdf_bytes=PDF,
        page_ocr={1: 0.6},
        vision=vision,
        context="x",
        doc_id=None,
        cloud_allowed=True,
    )
    (table,) = result.nodes
    assert (table.source, table.metadata["chosen"], result.flags) == (NodeSource.VLM, "vlm", [])


def test_disagreeing_versions_raise_a_soft_flag_with_both_tables(fake_vision):
    wrong = SPANNED.replace("52.4", "5.24").replace("12.4", "1.24")
    vision = fake_vision(read_table_image=table_reading(wrong, 0.9))
    result = check_tables(
        [node("tab1", NodeType.TABLE, SPANNED)],
        pdf_bytes=PDF,
        page_ocr={1: 0.6},
        vision=vision,
        context="x",
        doc_id=None,
        cloud_allowed=True,
    )
    (flag,) = result.flags
    assert (flag.flag_type, flag.severity) == (FlagType.LOW_CONFIDENCE_EXTRACTION, FlagSeverity.SOFT)
    assert flag.evidence.table_a_html == SPANNED and flag.evidence.table_b_html == wrong
    assert result.nodes[0].content == SPANNED


# ---------------------------------------------------------------- figures

PLOT = {
    "plot_type": "line",
    "x_axis": {"label": "t", "unit": "s", "range": [0, 10]},
    "y_axes": [{"label": "Pc", "unit": "bar", "range": [0, 15]}],
    "series": [{"name": "PT-101", "key_points": [{"x": 1.0, "y": 12.4}], "trend": "plateau"}],
    "annotations": [],
    "confidence": 0.8,
}
PHOTO = {
    "components_visible": ["injector"],
    "failure_modes": [{"mode": "erosion", "location": "face", "severity": "moderate", "confidence": 0.4}],
    "visible_text": [],
    "test_stage_hint": "post_test",
    "description": "Eroded injector face, scale unknown.",
}


def test_figures_route_by_class_and_become_readings_with_assets(fake_vision, memory_store):
    vision = fake_vision(
        digitize_plot=PLOT, inspect_hardware_photo=PHOTO, read_table_image=table_reading(SPANNED, 0.9)
    )
    assets = memory_store("s3://dcl-assets/")
    nodes = [
        node("t1", NodeType.CHILD, "As Figure 4 shows, the pressure settles."),
        node(
            "fig1",
            NodeType.FIGURE,
            "Figure 4: Pc trace",
            metadata={"class": "line_chart", "caption": "Figure 4: Pc trace"},
        ),
        node("fig2", NodeType.FIGURE, "", metadata={"class": "photograph", "caption": None}),
        node("fig3", NodeType.FIGURE, "", metadata={"class": "logo", "caption": None}),
        node("fig4", NodeType.FIGURE, "", metadata={"class": "table", "caption": None}),
    ]
    result = read_figures(
        nodes,
        pdf_bytes=PDF,
        blob_sha256=SHA,
        vision=vision,
        context="APU / TP07",
        doc_id="d1",
        cloud_allowed=True,
        put_asset=assets,
    )
    by_ref = {n.ref: n for n in result.nodes}
    assert result.skipped == ["fig3"] and "fig3" not in by_ref
    plot = by_ref["fig1"]
    assert "Series PT-101: (1.0, 12.4)" in plot.content and "As Figure 4 shows" in plot.content
    assert (plot.source, plot.metadata["capability"], plot.confidence) == (
        NodeSource.VLM,
        "digitize_plot",
        0.8,
    )
    assert by_ref["fig4"].node_type is NodeType.TABLE and by_ref["fig4"].content == SPANNED
    kinds = {a.ref: a.kind for a in result.assets}
    assert kinds["asset:fig2"] is AssetKind.PHOTO_IN_DOC and kinds["asset:fig1"] is AssetKind.FIGURE_CROP
    assert f"figures/{SHA}/fig1.png" in assets.objects
    (flag,) = result.flags  # photo top failure-mode confidence 0.4 < 0.5
    assert flag.flag_type is FlagType.LOW_CONFIDENCE_EXTRACTION


def test_the_model_is_told_where_a_figure_sits_and_a_product_picture_raises_no_flag(
    fake_vision, memory_store
):
    # plan step D2: a brochure's product shot came back with "discoloration 0.85" (26 Oct)
    vision = fake_vision(digitize_plot=PLOT, inspect_hardware_photo={**PHOTO, "photo_kind": "product_image"})
    crumb = "Moog brochure › WHAT WE DO IN PROPULSION"
    nodes = [
        node("t1", NodeType.CHILD, "As Figure 4 shows, the pressure settles.", breadcrumb=crumb),
        node(
            "fig1",
            NodeType.FIGURE,
            "Figure 4: Pc trace",
            metadata={"class": "line_chart", "caption": "Figure 4: Pc trace"},
            breadcrumb=crumb,
            page=1,
        ),
        node(
            "fig2", NodeType.FIGURE, "", metadata={"class": "photograph", "caption": None}, breadcrumb=crumb
        ),
    ]
    result = read_figures(
        nodes,
        pdf_bytes=PDF,
        blob_sha256=SHA,
        vision=vision,
        context="APS - Library / moog.pdf",
        doc_id="d1",
        cloud_allowed=True,
        put_asset=memory_store("s3://dcl-assets/"),
    )
    assert result.flags == []
    calls = dict(vision.calls)
    assert calls["digitize_plot"]["context"] == (
        "APS - Library / moog.pdf · page 1 · section: WHAT WE DO IN PROPULSION"
        " · the text says: As Figure 4 shows, the pressure settles."
    )
    assert calls["inspect_hardware_photo"]["folder_context"] == (
        "APS - Library / moog.pdf · page 1 · section: WHAT WE DO IN PROPULSION · no caption"
    )
    photo = next(n for n in result.nodes if n.ref == "fig2")
    assert photo.content.startswith("Photo (product image): Eroded injector face")


def test_a_flowchart_is_read_as_its_steps_and_arrows():
    reading = SchematicReading.model_validate(
        with_image_metadata(
            SchematicReading,
            {
                "drawing_kind": "flowchart",
                "steps": ["Structural design", "Is leak hazardous?", "Proof test"],
                "connections": [
                    {"from": "Structural design", "to": "Is leak hazardous?"},
                    {"from": "Is leak hazardous?", "to": "Proof test", "label": "yes"},
                ],
            },
        )
    )
    assert render_schematic(reading).splitlines() == [
        "Flowchart steps: Structural design; Is leak hazardous?; Proof test",
        "Structural design → Is leak hazardous?",
        "Is leak hazardous? → Proof test yes",
    ]


def test_figures_without_cloud_keep_their_caption_and_make_no_call(fake_vision, memory_store):
    vision = fake_vision()
    nodes = [
        node("fig1", NodeType.FIGURE, "Figure 2", metadata={"class": "line_chart", "caption": "Figure 2"})
    ]
    result = read_figures(
        nodes,
        pdf_bytes=PDF,
        blob_sha256=SHA,
        vision=vision,
        context="x",
        doc_id=None,
        cloud_allowed=False,
        put_asset=memory_store("s3://dcl-assets/"),
    )
    assert vision.calls == [] and result.nodes[0].content == "Caption: Figure 2"


def test_an_unusable_reading_keeps_the_figure_with_its_caption_and_flags_it(fake_vision, memory_store):
    from backend.llm_engine.gemini_types import StructuredOutputError

    def unusable(kwargs):
        raise StructuredOutputError("response does not match the schema: ValidationError", raw_text="{}")

    vision = fake_vision(digitize_plot=unusable, inspect_hardware_photo=PHOTO)
    nodes = [
        node("fig1", NodeType.FIGURE, "Figure 7", metadata={"class": "line_chart", "caption": "Figure 7"}),
        node("fig2", NodeType.FIGURE, "", metadata={"class": "photograph", "caption": None}),
    ]
    result = read_figures(
        nodes,
        pdf_bytes=PDF,
        blob_sha256=SHA,
        vision=vision,
        context="APU",
        doc_id="d1",
        cloud_allowed=True,
        put_asset=memory_store("s3://dcl-assets/"),
    )
    by_ref = {n.ref: n for n in result.nodes}
    assert by_ref["fig1"].content == "Caption: Figure 7"  # the document goes on
    assert "Eroded injector face" in by_ref["fig2"].content  # and so do the other figures
    unusable_flags = [f for f in result.flags if f.evidence.crops[0].confidence is None]
    assert len(unusable_flags) == 1 and unusable_flags[0].flag_type is FlagType.LOW_CONFIDENCE_EXTRACTION


# ---------------------------------------------------------------- handwritten pages

PAGE_URI = f"s3://dcl-assets/pages/{SHA}/0002.png"
PAGE_NODES = [
    node("vlm/p2/0", NodeType.CHILD, "### Post analysis of Catalyst", page=2, source=NodeSource.VLM),
    node(
        "vlm/p2/1",
        NodeType.CHILD,
        "<table><tr><td>Loss % of Catalyst</td><td>6.8%</td></tr>"
        "<tr><td>Tare weight (g)</td><td>[illegible]</td></tr></table>",
        page=2,
        source=NodeSource.VLM,
    ),
]


def doubt(label, value, confidence=0.85, illegible=False, alternatives=()):
    return HandwritingDoubt(
        field_label=label,
        value_raw=value,
        confidence=confidence,
        illegible=illegible,
        alternatives=list(alternatives),
    )


def test_each_doubtful_entry_is_one_flag_that_shows_the_page():
    nodes, flags = page_doubts(
        PAGE_NODES,
        2,
        [
            doubt("Loss % of Catalyst", "6.8%", alternatives=["6.81 %"]),
            doubt("Tare weight (g)", None, 0.3, True),
        ],
        page_uri=PAGE_URI,
        critical=[re.compile(r"tare\s+weight", re.IGNORECASE)],
    )
    assert [(f.flag_type, f.severity, f.anchor.page) for f in flags] == [
        (FlagType.LOW_CONFIDENCE_EXTRACTION, FlagSeverity.SOFT, 2),
        (FlagType.LOW_CONFIDENCE_EXTRACTION, FlagSeverity.HARD, 2),
    ]
    shown = flags[0].evidence.crops[0]
    assert (shown.crop_uri, shown.printed_label, shown.model_value, shown.alternatives) == (
        PAGE_URI,
        "Loss % of Catalyst",
        "6.8%",
        ["6.81 %"],
    )
    assert flags[1].suggested_resolution.resolution.illegible is True
    assert [e["label"] for e in nodes[1].metadata["handwriting"]] == ["Loss % of Catalyst", "Tare weight (g)"]
    assert [e["key"] for e in nodes[1].metadata["handwriting"]] == [f.anchor.content_sha256 for f in flags]
    assert nodes[0].metadata == {}


def test_an_entry_keeps_its_anchor_on_a_rebuild_and_a_repeated_label_gets_its_own():
    entries = [doubt("Date", "30/05/2026"), doubt("Date", "31/05/2026")]
    first = page_doubts(PAGE_NODES, 2, entries, page_uri=PAGE_URI, critical=[])[1]
    again = page_doubts(PAGE_NODES, 2, entries, page_uri=PAGE_URI, critical=[])[1]
    assert [f.fingerprint for f in first] == [f.fingerprint for f in again]
    assert first[0].fingerprint != first[1].fingerprint


def test_an_entry_whose_text_is_not_on_the_page_is_kept_on_its_first_node():
    nodes, _ = page_doubts(PAGE_NODES, 2, [doubt("Remark", "see log")], page_uri=PAGE_URI, critical=[])
    assert [e["value_raw"] for e in nodes[0].metadata["handwriting"]] == ["see log"]
