"""A1.0 visual twin: page map for A2's headings, PDF-only pages run through A1 as an appendix."""

import io

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("docling")

from backend.postgres.enums import AssetKind  # noqa: E402
from backend.routes.a1_office.route import Stores, process_pdf  # noqa: E402
from backend.routes.a1_office.twin import page_map, pdf_only_pages, process_twin  # noqa: E402

from .test_route import SHA, docling_models, fixture, folder, triage  # noqa: E402

PAGES = [
    "Test Report 37\n1 Introduction\nThe thruster was fired in vacuum.",
    "2 Test Setup\nThe catalyst bed and the injector were instrumented.\n3 Results\nChamber pressure rose.",
    "Figure 4 continues",
    "4 Conclusions\nThe design meets the requirement.",
]


def test_headings_map_to_pages_in_order_and_a_miss_keeps_the_previous_page():
    headings = ["1 Introduction", "2 Test Setup", "3 Results", "3.1 Not in the PDF", "4. Conclusions"]
    assert page_map(headings, PAGES) == {0: 1, 1: 2, 2: 2, 3: 2, 4: 4}
    # order constraint: a later heading never maps before an earlier one
    assert page_map(["3 Results", "1 Introduction"], PAGES) == {0: 2, 1: 2}


def test_pdf_only_pages_are_the_ones_the_source_does_not_contain():
    source = " ".join(PAGES[:2] + PAGES[3:])
    appendix = "Approval signatures quality manager stamped released document control archive copy " * 2
    pages = [*PAGES, appendix, ""]
    assert pdf_only_pages(pages, source, image_pages={6}) == [5, 6]


@docling_models
def test_process_twin_renders_every_page_and_runs_the_appendix_through_a1(fake_vision, memory_store):
    name, data = fixture("german_datasheet")
    pdf = pikepdf.new()
    with pikepdf.open(io.BytesIO(data)) as source:
        pdf.pages.append(source.pages[0])
        pdf.pages.append(source.pages[0])
    twin = io.BytesIO()
    pdf.save(twin)
    assets, cir = memory_store("s3://dcl-assets/"), memory_store(f"s3://dcl-cir/{SHA}/A2/v1/")

    def appendix(pdf_bytes, put_asset, put_cir):
        return process_pdf(
            pdf_bytes,
            blob_sha256=SHA,
            file_name=name,
            folder=folder("APU", "Reports", name),
            vision=fake_vision(triage_page=triage(language="de")),
            stores=Stores(put_cir=put_cir, put_asset=put_asset),
        )

    result = process_twin(
        twin.getvalue(),
        ["Introduction"],
        "Introduction only, nothing of the datasheet",
        blob_sha256=SHA,
        title="Report 37",
        put_asset=assets,
        put_cir=cir,
        appendix=appendix,
    )
    assert result.pdf_only_pages == [1, 2]
    assert [a.page_no for a in result.assets if a.kind is AssetKind.PAGE_RENDER] == [1, 2]
    assert "page_map.json" in cir.objects and any(k.startswith("appendix/") for k in cir.objects)
    assert result.appendix_nodes and {n.page_no for n in result.appendix_nodes} <= {1, 2}
    assert all(n.breadcrumb.startswith("Report 37 › Appendix (PDF-only)") for n in result.appendix_nodes)
    assert all(n.ref.startswith("appendix/") for n in result.appendix_nodes)
    assert sorted(k for k in assets.objects if k.startswith("pages/")) == [
        f"pages/{SHA}/0001.png",
        f"pages/{SHA}/0002.png",
    ]


def text_pdf(pages: list[list[str]]) -> bytes:
    """A PDF with a real text layer (Helvetica), one list of lines per page."""
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
        )
    )
    for lines in pages:
        ops = ["BT", "/F1 12 Tf", "14 TL", "72 760 Td"]
        for line in lines:
            ops.append(f"({line}) Tj T*")
        ops.append("ET")
        page = pdf.add_blank_page(page_size=(595, 842))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream("\n".join(ops).encode())
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def test_a_text_table_of_contents_does_not_capture_the_headings():
    from backend.routes.a1_office.twin import page_texts

    pdf = text_pdf(
        [
            ["Test Report 37"],
            [
                "Contents",
                "1 Introduction ..... 3",
                "2 Test Setup ..... 4",
                "2.1 Instrumentation ..... 4",
                "3 Results ..... 5",
            ],
            ["1 Introduction", "The thruster was fired in vacuum."],
            ["2 Test Setup", "The stand.", "2.1 Instrumentation", "Pressure transducers."],
            ["3 Results", "Chamber pressure rose."],
        ]
    )
    headings = ["1 Introduction", "2 Test Setup", "2.1 Instrumentation", "3 Results"]
    assert page_map(headings, page_texts(pdf)) == {0: 3, 1: 4, 2: 4, 3: 5}


def test_a_body_page_mentioning_short_titles_is_not_a_contents_page():
    from backend.routes.a1_office.twin import page_texts

    pdf = text_pdf(
        [
            ["TP12 Test Report", "Valve, Test and Procedure records are kept with the build log."],
            ["Contents", "1 Overview ..... 3", "2 Valve ..... 3", "3 Test ..... 4", "4 Procedure ..... 4"],
            [
                "1 Overview",
                "Valve, test and procedure were checked.",
                "2 Valve",
                "The valve opened in 12 ms.",
            ],
            ["3 Test", "Test 4 ran 20 s.", "4 Procedure", "The procedure was followed."],
        ]
    )
    headings = ["1 Overview", "2 Valve", "3 Test", "4 Procedure"]
    # pages 1 and 3 name Valve, Test and Procedure in prose but are not contents pages; page 2 is
    assert page_map(headings, page_texts(pdf)) == {0: 3, 1: 3, 2: 4, 3: 4}
