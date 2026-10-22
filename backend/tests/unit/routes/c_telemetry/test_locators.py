"""Stable anchors for Route C table and row nodes (file 04 §4.4): sheet + one-row cell_range for workbook
tables, file lines for CSV tables (the header and preamble counted, a units row skipped)."""

from backend.routes.c_telemetry.delimited import as_table, read_delimited
from backend.routes.c_telemetry.tables import Table, table_nodes
from backend.routes.c_telemetry.workbook import read_workbook
from backend.tests.unit.routes.c_telemetry.test_adapters import analysis_workbook, daqami_csv


def _locators(table: Table):
    return [
        (n.node_type, n.sheet_name, n.cell_range, n.line_start, n.line_end)
        for n in table_nodes(table, "t1", 0, "")
    ]


def test_csv_rows_carry_their_file_lines():
    table = as_table(read_delimited(daqami_csv(3)), "Analog.csv")  # 6 preamble lines, header on line 7
    assert _locators(table) == [
        ("table", None, None, 7, 10),
        ("table_row", None, None, 8, 8),
        ("table_row", None, None, 9, 9),
        ("table_row", None, None, 10, 10),
    ]


def test_quoted_newline_record_spans_two_lines():
    data = b'Name,Value (bar)\n"two\nlines",1.5\nplain,2.5\n'
    assert _locators(as_table(read_delimited(data), "x.csv"))[1:] == [
        ("table_row", None, None, 2, 3),
        ("table_row", None, None, 4, 4),
    ]


def test_workbook_rows_carry_a_one_row_cell_range():
    tables = {t.cell_range: t for t in read_workbook(analysis_workbook()).tables}
    assert _locators(tables["A2:C4"]) == [
        ("table", "Performance Parameters", "A2:C4", None, None),
        ("table_row", "Performance Parameters", "A3:C3", None, None),
        ("table_row", "Performance Parameters", "A4:C4", None, None),
    ]
    assert _locators(tables["F8:G9"])[1] == ("table_row", "Performance Parameters", "F9:G9", None, None)


def test_a_units_row_is_not_a_data_row_and_keeps_the_numbering():
    table = Table(rows=[["P", "T"], ["bar", "K"], [1.0, 300.0]], row_lines=[(1, 1), (2, 2), (3, 3)])
    assert _locators(table)[1:] == [("table_row", None, None, 3, 3)]
