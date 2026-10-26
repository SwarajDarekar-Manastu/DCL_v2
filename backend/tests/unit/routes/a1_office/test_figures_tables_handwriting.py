import io

import pytest

pytest.importorskip("pypdfium2")
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from backend.dispatcher.contract import PageBox, ProcessedNode  # noqa: E402
from backend.llm_engine.vision.schemas import PageType, SchematicReading, Script  # noqa: E402
from backend.postgres.enums import AssetKind, FlagSeverity, FlagType, NodeSource, NodeType  # noqa: E402
from backend.routes.a1_office.figures import read_figures, render_schematic  # noqa: E402
from backend.routes.a1_office.handwriting import nearest_label, region_box, transcribe_regions  # noqa: E402
from backend.routes.a1_office.tables_qa import (  # noqa: E402
    agreement,
    check_tables,
    grid,
    parse_cells,
    qa_reasons,
    units_by_column,
)
from backend.routes.a1_office.triage import PageDecision  # noqa: E402
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


# ---------------------------------------------------------------- handwriting

LABELS = [
    node("t0", NodeType.CHILD, "TEST CELL RUN SHEET", (0.1, 0.10, 0.45, 0.13), ordinal=0),
    node("t1", NodeType.CHILD, "Injector orifice dia (mm):", (0.1, 0.22, 0.40, 0.25), ordinal=1),
    node("t2", NodeType.CHILD, "Tare weight (g):", (0.1, 0.34, 0.30, 0.37), ordinal=2),
]


def triage(regions):
    return [
        PageDecision(
            page_no=1,
            page_type=PageType.SCANNED_FORM_WITH_HANDWRITING,
            language="en",
            script=Script.LATIN,
            is_rotated=False,
            image_only=True,
            ocr_engine="tesseract",
            handwriting_regions=regions,
        )
    ]


def region(ymin, xmin, ymax, xmax, kind="value"):
    from backend.llm_engine.vision.schemas import HandwritingRegion

    return HandwritingRegion(box_2d=[ymin, xmin, ymax, xmax], kind=kind)


def test_nearest_label_left_on_the_line_then_above():
    assert nearest_label(region_box(1, [220, 420, 250, 520]), LABELS).ref == "t1"
    assert nearest_label(region_box(1, [380, 100, 400, 300]), LABELS).ref == "t2"
    assert nearest_label(region_box(1, [800, 600, 850, 900]), LABELS) is None


def reading(value, confidence, illegible=False):
    return {
        "field_label": "x",
        "value_raw": value,
        "value_number": None,
        "unit": None,
        "confidence": confidence,
        "alternatives": ["0.86"],
        "illegible": illegible,
        "notes": None,
    }


def run_hw(fake_vision, memory_store, readings, regions, critical=()):
    vision = fake_vision(transcribe_handwriting=lambda kw: readings[kw["field_label"]])
    return transcribe_regions(
        LABELS,
        triage(regions),
        pdf_bytes=PDF,
        blob_sha256=SHA,
        vision=vision,
        context="APU / TP07",
        test_plan_id="TP07",
        doc_id="d1",
        cloud_allowed=True,
        critical_field_patterns=critical,
        put_asset=memory_store("s3://dcl-assets/"),
    ), vision


def test_handwritten_value_lands_after_its_label_with_confidence(fake_vision, memory_store):
    result, vision = run_hw(
        fake_vision,
        memory_store,
        {"Injector orifice dia (mm):": reading("0.85", 0.92)},
        [region(220, 420, 250, 520)],
    )
    assert [n.ref for n in result.nodes] == ["t0", "t1", "hw/p1_hw0", "t2"]
    hw = result.nodes[2]
    assert hw.content == "Injector orifice dia (mm): [HW 0.85 | conf 0.92]"
    assert (hw.source, hw.confidence, hw.breadcrumb) == (NodeSource.VLM, 0.92, "Run sheet")
    assert vision.calls[0][1]["allowed_units"] == ["g", "mm"]
    assert result.flags == [] and result.assets[0].kind is AssetKind.HANDWRITING_CROP


def test_low_confidence_is_soft_and_a_critical_field_is_hard(fake_vision, memory_store):
    readings = {
        "Injector orifice dia (mm):": reading("0.8?", 0.6),
        "Tare weight (g):": reading(None, 0.2, True),
    }
    result, _ = run_hw(
        fake_vision,
        memory_store,
        readings,
        [region(220, 420, 250, 520), region(340, 320, 370, 420)],
        critical=[r"tare\s+weight"],
    )
    severities = sorted(f.severity for f in result.flags)
    assert severities == [FlagSeverity.HARD, FlagSeverity.SOFT]
    hard = next(f for f in result.flags if f.severity == FlagSeverity.HARD)
    assert hard.evidence.crops[0].printed_label == "Tare weight (g):"
    assert hard.suggested_resolution.resolution.illegible is True
    assert any(n.content == "Tare weight (g): [HW illegible]" for n in result.nodes)


def test_signatures_are_not_transcribed(fake_vision, memory_store):
    result, vision = run_hw(fake_vision, memory_store, {}, [region(900, 100, 950, 400, kind="signature")])
    assert vision.calls == [] and [n.ref for n in result.nodes] == ["t0", "t1", "t2"]


def test_slivers_and_table_cells_are_not_handwriting(fake_vision, memory_store):
    import dataclasses

    from backend.dispatcher.contract import PageBox, ProcessedNode

    sliver = region(500, 400, 560, 408)  # 8/1000 of the width: a cell border
    in_table = region(620, 300, 680, 500)
    table = ProcessedNode(
        ref="tab1",
        ordinal=9,
        source=NodeSource.PRINTED,
        node_type=NodeType.TABLE,
        content="| a | b |",
        page_no=1,
        bboxes=[PageBox(page_no=1, x0=0.1, y0=0.6, x1=0.9, y1=0.8)],
    )
    vision = fake_vision(transcribe_handwriting=lambda kw: pytest.fail("no call for a rejected candidate"))
    decisions = [dataclasses.replace(triage([sliver, in_table])[0], has_handwriting=False)]
    result = transcribe_regions(
        [*LABELS, table],
        decisions,
        pdf_bytes=PDF,
        blob_sha256=SHA,
        vision=vision,
        context="ECSS",
        test_plan_id=None,
        doc_id="d1",
        cloud_allowed=True,
        critical_field_patterns=(),
        put_asset=memory_store("s3://dcl-assets/"),
    )
    reasons = [r["reason"] for r in result.rejected]
    assert len(reasons) == 2 and "px" in reasons[0] and "table" in reasons[1]
    assert result.assets == [] and vision.calls == []
