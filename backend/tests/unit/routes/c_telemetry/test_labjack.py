"""LJStreamM header parsing and Arrow batch reading (no services needed)."""

import io

import numpy as np
import pyarrow as pa

from backend.routes.c_telemetry.labjack import can_handle, is_voltage, parse_header, read_batches
from backend.tests.unit.routes.c_telemetry.conftest import CHANNELS, labjack_bytes


def test_header_has_columns_start_time_and_verbatim_lines():
    raw, _ = labjack_bytes()
    header = parse_header(raw[:4096].decode())
    assert header is not None
    assert header.columns == ["Time", *CHANNELS]
    assert (header.time_column, header.channels) == ("Time", CHANNELS)
    assert header.header_lines == ["29-12-2025", "14:18:41", "", "", "Time\tv0\tv1\ty0\ty1"]
    assert header.data_start_line == 5
    assert header.started_at.isoformat() == "2025-12-29T14:18:41+05:30"


def test_can_handle_needs_the_extension_and_the_layout():
    raw, _ = labjack_bytes()
    assert can_handle(raw[:4096], "INJ10_T01.dat")
    assert can_handle(raw[:4096], "INJ10_T02.DAT_FAIL")
    assert not can_handle(raw[:4096], "INJ10_T01.csv")
    assert not can_handle(b"time\tAIN0\n0.000\t1.20\n", "TP12_T01.dat")
    assert not can_handle(b"[LJM]\nDevice=T7\n", "setup.dat")


def test_voltage_columns():
    assert [is_voltage(c) for c in ("v0", "v12", "y0", "Time", "v")] == [True, True, False, False, False]


def test_batches_cover_every_row_as_float64_for_both_newlines():
    for newline in ("\r\n", "\n"):
        raw, data = labjack_bytes(newline=newline)
        header = parse_header(raw[:4096].decode())
        table = pa.Table.from_batches(list(read_batches(io.BytesIO(raw), header)))
        assert table.column_names == header.columns
        assert all(field.type == pa.float64() for field in table.schema)
        np.testing.assert_allclose(table.column("y0").to_numpy(), data[:, 3], atol=1e-6)
        assert table.num_rows == len(data)
