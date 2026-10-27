"""The page check's reading (review/page_reading.py): blocks of plain text the console can draw safely."""

from pathlib import Path

from backend.review.page_reading import block_key, locate, parse_reading, set_cell, set_text

# A made-up page shaped like a real hand-filled test sheet: a heading, three tables, a list (the repository is
# public: real pages never go into it, see tests/fixtures/README.md)
SAMPLE_PAGE = (Path(__file__).parents[2] / "fixtures" / "review" / "sample_page.txt").read_text()


def test_a_reading_splits_into_headings_text_and_tables_with_stable_keys():
    source = (
        '### Bench Heater Trial\n<table><tr><td>Trial Name</td><td colspan="3">Trial 7.1</td></tr></table>'
    )
    (block,) = parse_reading(source)
    heading, table = block.parts
    assert (heading.kind, heading.text, block.key) == ("heading", "Bench Heater Trial", block_key(source))
    assert [[(c.text, c.span_of) for c in row] for row in table.rows] == [
        [("Trial Name", None), ("Trial 7.1", None), ("", (0, 1)), ("", (0, 1))]
    ]


def test_crossed_out_text_is_kept_apart_and_markup_is_never_passed_on():
    (block,) = parse_reading(
        "<table><tr><td>~~old note~~ 42.0 Ω</td><td><img src=x onerror=alert(1)>a<br>b</td></tr></table>"
    )
    struck, unsafe = block.parts[0].rows[0]
    assert (struck.text, struck.struck) == ("old note 42.0 Ω", ["old note"])
    assert unsafe.text == "a\nb"


def test_the_sample_page_has_its_heading_three_tables_and_list():
    (block,) = parse_reading(SAMPLE_PAGE)
    assert [p.kind for p in block.parts] == ["heading", "table", "table", "table", "text"]
    assert block.parts[0].text == "Bench Heater Trial"


def test_an_unsure_entry_is_found_in_its_labels_row():
    blocks = parse_reading(SAMPLE_PAGE)
    found = locate(blocks, "Trial Name", "Trial 7.1 (warm-up run")
    (block,) = blocks
    row = block.parts[2].rows[found["cell"][0]]  # parts[2] is the second table, tables index 1
    assert (found["table"], found["cell"][1], row[0].text) == (1, 1, "Trial Name")
    assert locate(blocks, "Sample Name", "Sample B-12 (lot 4")["cell"] == [7, 1]
    assert locate(blocks, "Nothing", "not on this page") is None


TABLE = "<table><tr><td>Time</td><td>T2 [C]</td></tr><tr><td>09:10</td><td>40.25</td></tr></table>"


def test_a_cell_correction_rewrites_that_cell_only_and_never_one_that_changed():
    assert set_cell(TABLE, 0, 1, 1, "40.25", "40.52") == TABLE.replace("40.25", "40.52")
    assert set_cell(TABLE, 0, 1, 1, "280.00", "40.52") is None  # the reading no longer says 280.00
    assert set_cell(TABLE, 1, 0, 0, "Time", "t") is None  # there is no second table
    assert set_cell(TABLE, 0, 0, 0, "Time", "<b>t</b>") == TABLE.replace(">Time<", ">&lt;b&gt;t&lt;/b&gt;<")


def test_a_spanned_cell_on_the_sample_page_is_corrected_at_its_origin():
    (block,) = parse_reading(SAMPLE_PAGE)
    old = "Trial 7.1 (warm-up run"
    (again,) = parse_reading(set_cell(block.source, 1, 0, 1, old, old + ")"))
    row = again.parts[2].rows[0]
    assert (row[1].text, row[2].span_of) == (old + ")", (0, 1))


def test_a_text_line_is_replaced_and_a_heading_stays_a_heading():
    source = "### Bench Heater Trial\n<table><tr><td>a</td></tr></table>\n- Heater off at 10:20."
    assert set_text(source, "- Heater off at 10:20.", "- Heater switched off here.") == source.replace(
        "- Heater off at 10:20.", "- Heater switched off here."
    )
    assert set_text(source, "Bench Heater Trial", "Bench Heater Trial 2").startswith(
        "### Bench Heater Trial 2\n"
    )
    assert set_text(source, "not on the page", "x") is None
