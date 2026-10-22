"""Route C adapters on synthetic files in the layouts of the corpus (no services): DAQami CSV exports,
LabVIEW TDMS without units, analysis workbooks, LabJack/INI/JSON configuration files."""

import io
import json
from datetime import datetime

import numpy as np
import openpyxl
import pyarrow as pa
import pytest
from nptdms import ChannelObject, GroupObject, RootObject, TdmsWriter
from openpyxl.styles import Font

from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import TelemetrySourceFormat
from backend.routes.c_telemetry import config_file, delimited, tdms, workbook
from backend.routes.c_telemetry.series import entry_from_unit, resolve_channels, slug, source_from_schema
from backend.routes.c_telemetry.tables import Table, header_unit, table_nodes, unit_flags

CONTEXT = FolderContext(root_name="APU", breadcrumb=["APU", "Test Plan 7"], path_cached="APU/Test Plan 7")


def daqami_csv(rows: int, quoted: bool = True, clock: bool = False) -> bytes:
    q = '"' if quoted else ""
    preamble = [
        f"{q}Device: USB-TC{q}",
        f"{q}Serial Number: 2168D9C{q}",
        f"{q}Channel Count: 2{q}",
        f"{q}Sample Count: {rows}{q}",
        f"{q}Start Time: 04-12-2025 13:25:17.6{q}",
        f"{q}Scan Rate: 2{q}",
    ]
    header = f"{q}Sample{q},{q}Date/Time{q},{q}T1 - Upper Thermal Stdoff (°C){q},{q}T2 - CW flange  (°C){q}"
    lines = [*preamble, header]
    for i in range(rows):
        seconds = 17.6 + i * 0.5
        stamp = (
            f"25:{seconds:04.1f}"
            if clock
            else f"04-12-2025 13:25:{seconds:04.1f}"
            if seconds < 60
            else (f"04-12-2025 13:{25 + int(seconds // 60)}:{seconds % 60:04.1f}")
        )
        lines.append(f"{q}{i}{q},{q}{stamp}{q},{q}{30 + i * 0.1:.3f}{q},{q}{40 + i * 0.2:.3f}{q}")
    return ("﻿" + "\r\n".join(lines) + "\r\n").encode()


# ---------------------------------------------------------------- CSV


def test_a_daqami_export_with_enough_rows_is_a_series_with_units_from_the_header():
    table = delimited.read_delimited(daqami_csv(120))
    assert table.preamble[0] == "Device: USB-TC" and len(table.preamble) == 6
    assert table.header[2] == "T1 - Upper Thermal Stdoff (°C)"
    plan = delimited.series_plan(table)
    assert plan is not None and plan.channels == [2, 3]
    assert plan.time[:3].tolist() == pytest.approx([0.0, 0.5, 1.0])
    source = delimited.delimited_source(table, plan, "Analog - 04-12-2025 13-25-17.6.csv")
    assert source.columns == ["time_s", "T1 - Upper Thermal Stdoff (°C)", "T2 - CW flange  (°C)"]
    assert source.units == {"T1 - Upper Thermal Stdoff (°C)": "°C", "T2 - CW flange  (°C)": "°C"}
    assert source.started_at.isoformat() == "2025-12-04T13:25:17.600000+05:30"
    batch = next(source.open_batches())
    assert batch.num_rows == 120 and batch.column(1)[0].as_py() == pytest.approx(30.0)


def test_clock_times_unwrap_and_a_short_export_is_a_table():
    long = delimited.read_delimited(daqami_csv(140, quoted=False, clock=True))
    plan = delimited.series_plan(long)
    assert plan is not None and np.all(np.diff(plan.time) > 0)  # 25:59.6 → 26:00.1 does not go backwards
    short = delimited.read_delimited(daqami_csv(22, quoted=False))
    assert delimited.series_plan(short) is None
    as_table = delimited.as_table(short, "Analog.csv")
    assert as_table.header[0] == "Sample" and len(as_table.body) == 22


def test_decimal_comma_and_footer_rows():
    text = "time;p (bar)\n" + "\n".join(
        f"{i * 0.01:.2f}".replace(".", ",") + f";{1 + i / 100:.2f}".replace(".", ",") for i in range(150)
    )
    text += "\nmax;2,49\naverage;1,745\n"
    table = delimited.read_delimited(text.encode())
    assert table.delimiter == ";" and table.decimal_comma
    assert [r[0] for r in table.footer] == ["max", "average"]
    plan = delimited.series_plan(table)
    source = delimited.delimited_source(table, plan, "run.csv")
    values = next(source.open_batches()).column(1).to_pylist()
    assert values[1] == pytest.approx(1.01) and source.units == {"p (bar)": "bar"}


# ---------------------------------------------------------------- TDMS


def write_tdms(path, with_units: bool) -> None:
    group = GroupObject(
        "Analog", properties={"StartTime": np.datetime64("2025-12-04T06:15:10.642204"), "ScanRate": 2.0}
    )
    channels = [ChannelObject("Analog", "TimeStamps", np.arange(30) * 0.5, properties={"unit_string": ""})]
    for i in range(3):
        unit = "Deg C" if with_units else ""
        channels.append(
            ChannelObject("Analog", f"AI{i}", 25 + i + np.arange(30) * 0.1, properties={"unit_string": unit})
        )
    with TdmsWriter(str(path)) as writer:
        writer.write_segment([RootObject(properties={"name": "Temperature"}), group, *channels])


def test_tdms_time_channel_properties_and_missing_units(tmp_path):
    path = tmp_path / "Temperature.tdms"
    write_tdms(path, with_units=False)
    source = tdms.tdms_source(path, "Temperature.tdms")
    assert source.source_format == TelemetrySourceFormat.TDMS
    assert source.columns == ["TimeStamps", "AI0", "AI1", "AI2"]
    assert source.units == {} and "group: Analog" in source.header_lines
    assert source.started_at.isoformat().startswith("2025-12-04T06:15:10")
    table = pa.Table.from_batches(list(source.open_batches()))
    assert table.num_rows == 30 and table.column("AI2")[0].as_py() == pytest.approx(27.0)
    resolution = resolve_channels(source.channels, [], {}, None, source.units)
    assert resolution.unresolved == ["AI0", "AI1", "AI2"]
    assert resolution.notes["AI0"] == "the file states no unit"


def test_tdms_unit_strings_resolve_channels(tmp_path):
    path = tmp_path / "Temperature.tdms"
    write_tdms(path, with_units=True)
    source = tdms.tdms_source(path, "Temperature.tdms")
    resolution = resolve_channels(source.channels, [], {}, None, source.units)
    assert resolution.unresolved == [] and resolution.from_file == {"AI0", "AI1", "AI2"}
    assert (
        resolution.mapped["AI0"].canonical_name == "ai0_k"
        and resolution.mapped["AI0"].physical_quantity == "temperature"
    )


# ---------------------------------------------------------------- header-derived entries


def test_units_stated_in_a_file_map_channels_and_pressure_needs_a_reference():
    assert entry_from_unit("T1 - flange (°C)", "°C").canonical_name == "t1_flange_k"
    assert entry_from_unit("P tank", "psig").canonical_name == "p_tank_bar_g"
    assert entry_from_unit("P tank", "bar").canonical_name == "p_tank_bar"  # gauge/abs unknown: plan flags it
    assert entry_from_unit("Thrust", "N").canonical_name == "thrust_n"
    assert isinstance(entry_from_unit("x", "furlongs per fortnight squared kelvin"), str)
    assert slug("T5 - CW 82mm Adj to SP  (°C)") == "t5_cw_82mm_adj_to_sp"
    assert header_unit("Feedline Pressure (Bar) [Gauge]") == "bar" and header_unit("Roughness") is None


# ---------------------------------------------------------------- workbooks


def analysis_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Performance Parameters"
    ws["A1"] = "Performance summary"
    ws["A1"].font = Font(bold=True)
    ws.append(["Parameter", "Value", "Unit"])
    ws.append(["Peak chamber pressure", 12.4, "bar"])
    ws.append(["Mean thrust", 18.2, "N"])
    ws["A8"], ws["B8"], ws["C8"] = "Failure mode", "Severity", "RPN"
    ws["A9"], ws["B9"], ws["C9"] = "Bed erosion", 7, 140
    ws["F8"], ws["G8"] = "Duration", "Efficiency"  # two blank columns separate islands (C.4 step 3)
    ws["F9"], ws["G9"] = 41.5, 0.93
    ws["G9"].number_format = "0%"
    ws.merge_cells("A12:C12")
    ws["A12"] = "merged note"
    ws["A13"], ws["B13"] = "x", "y"
    ws["A14"], ws["B14"] = "#DIV/0!", 2
    hidden = wb.create_sheet("Lookup")
    hidden.sheet_state = "hidden"
    hidden.append(["Key", "Value (bar)"])
    hidden.append(["max", 150])
    series = wb.create_sheet("Raw")
    series.append(["Time (s)", "Pc (bar)", "Tc (K)"])
    for i in range(120):
        series.append([i * 0.01, 1 + i * 0.05, 300 + i])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_workbook_islands_captions_merged_hidden_percent_and_series():
    book = workbook.read_workbook(analysis_workbook())
    by = {(t.sheet, t.cell_range): t for t in book.tables}
    summary = by[("Performance Parameters", "A2:C4")]
    assert summary.caption == "Performance summary" and summary.has_unit_column()
    fmea = next(t for t in book.tables if t.header[:2] == ["Failure mode", "Severity"])
    assert unit_flags(fmea) == []  # Severity and RPN are dimensionless
    duration = next(t for t in book.tables if t.header == ["Duration", "Efficiency"])
    assert duration.body[0] == [41.5, "93%"]
    (flag,) = unit_flags(duration)
    assert (flag.severity, flag.anchor.column, flag.anchor.sheet) == (
        "SOFT",
        "Duration",
        "Performance Parameters",
    )
    merged = next(t for t in book.tables if t.caption == "merged note")
    assert merged.error_cells == ["A14"]
    assert book.error_sheets == {"Performance Parameters": ["A14"]}
    lookup = next(t for t in book.tables if t.sheet == "Lookup")
    assert lookup.hidden and lookup.column_units() == {1: "bar"}
    (island,) = book.series
    assert (island.sheet, island.cell_range, len(island.rows)) == ("Raw", "A1:C121", 120)
    source = workbook.island_source(island, "Test 01_Data_Analysis.xlsx")
    assert source.columns == ["time_s", "Pc (bar)", "Tc (K)"] and source.units == {
        "Pc (bar)": "bar",
        "Tc (K)": "K",
    }


def test_formulas_without_cached_values_are_recalculated():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["a", "b", "sum"])
    ws.append([2, 3, "=A2+B2"])
    buffer = io.BytesIO()
    wb.save(buffer)  # openpyxl writes no cached value for the formula
    calls = []

    def recalc(data: bytes) -> bytes:
        calls.append(len(data))
        fixed = openpyxl.load_workbook(io.BytesIO(data))
        fixed.active["C2"] = 5  # what LibreOffice would compute
        out = io.BytesIO()
        fixed.save(out)
        return out.getvalue()

    book = workbook.read_workbook(buffer.getvalue(), recalc=recalc)
    assert calls and book.recalculated
    assert book.tables[0].body[0] == [2, 3, 5]


def test_table_nodes_repeat_the_header_in_every_row():
    table = Table(
        rows=[["Requirement", "Text", "Status"], ["R-12", "Cooling duct shall …", "open"]], sheet="FMEA"
    )
    table_node, row = table_nodes(table, "t1", 0, "APU › TP23")
    assert table_node.node_type == "table" and "<th>Requirement</th>" in table_node.content
    assert (
        row.parent_ref == "t1"
        and row.content == "FMEA | Requirement: R-12 | Text: Cooling duct shall … | Status: open"
    )


# ---------------------------------------------------------------- configuration files


@pytest.mark.parametrize(
    ("text", "kind", "line"),
    [
        (
            "[Main]\nScanRate=1000.000000\nScaling=y=a*24.9-12.3#!#y=b#!#\n",
            "ini",
            "Main.ScanRate = 1000.000000",
        ),
        ('{"daq": {"rate_hz": 1000, "channels": ["AIN0", "AIN1"]}}', "json", "daq.channels.1 = AIN1"),
        ("rate = 1000\n# comment\nunits: bar\n", "key_value", "units = bar"),
    ],
)
def test_configuration_files(text, kind, line):
    puts = {}
    doc = config_file.process_config(
        text.encode(), "a" * 64, "LJStreamM.cfg", CONTEXT, lambda key, data: puts.setdefault(key, data)
    )
    (node,) = doc.nodes
    assert doc.document.doc_kind == "config" and doc.document.catalog["config_format"] == kind
    assert line in node.content and node.node_type == "config"
    assert json.loads(puts[f"{'a' * 64}/C/v1/config.json"])["format"] == kind
    assert config_file.can_handle(text.encode(), "x.cfg") and not config_file.can_handle(b"\x00\x01", "x.cfg")


def test_the_scaling_line_is_readable_in_the_config_node():
    doc = config_file.process_config(
        b"[Main]\nScaling=y=a*24.943-12.385#!#y=b*25.014-12.539#!#\n",
        "b" * 64,
        "LJStreamM.cfg",
        CONTEXT,
        lambda *_: None,
    )
    assert "Main.Scaling = y=a*24.943-12.385 | y=b*25.014-12.539" in doc.nodes[0].content


def test_a_schema_rebuilds_the_series_source_for_resume():
    legacy = {"header_lines": ["29-12-2025", "14:18:41", "Time\tv0\ty0"], "columns": ["Time", "v0", "y0"],
              "started_at": datetime(2025, 12, 29, 14, 18, 41).isoformat()}  # fmt: skip
    source = source_from_schema(legacy, "run.dat_fail")
    assert source.source_format == "labjack_dat" and source.voltage == {"v0"} and source.failed
    modern = {
        **legacy,
        "source_format": "csv",
        "stated_units": {"y0": "degC"},
        "channels": {},
        "failed": False,
    }
    assert source_from_schema(modern, "x.csv").units == {"y0": "degC"}
