"""LJStreamM .cfg parsing on the layouts found in the crawl (no services needed)."""

import pytest

from backend.routes.c_telemetry.ljstream_cfg import LinearScaling, parse_ljstream_cfg

CFG = """[Main]
FilePrefix=Test_02_08_Bar_Tube_collection_ii
ScanRate=1000.000000
NumChan=8
DisableScaling=FALSE
ChP=AIN0#!#AIN1#!#AIN2#!#AIN3#!#AIN4#!#AIN5#!#AIN6#!#AIN7#!#AIN8#!#
Scaling=y=a*24.943-12.385#!#y=b*25.014-12.539#!#y=c*24.984-12.417#!#y=d*2.9951+0.0004#!#y=e*#!#y=f*120.00+0.721#!#y=g*50.044#!#y=h*10#!#y=i#!#y=j#!#
"""


def test_equations_follow_the_channel_count_and_letters():
    config = parse_ljstream_cfg(CFG)
    assert (config.scan_rate_hz, config.num_channels, config.scaling_disabled) == (1000.0, 8, False)
    assert list(config.equations) == [f"y{i}" for i in range(8)]
    assert config.equations["y0"] == "y=a*24.943-12.385"


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("y0", LinearScaling(24.943, -12.385)),
        ("y3", LinearScaling(2.9951, 0.0004)),
        ("y5", LinearScaling(120.0, 0.721)),
        ("y6", LinearScaling(50.044, 0.0)),
        ("y7", LinearScaling(10.0, 0.0)),
        ("y4", None),  # "y=e*": incomplete, kept as text only
        ("y9", None),  # beyond NumChan
    ],
)
def test_linear_form(channel, expected):
    assert parse_ljstream_cfg(CFG).linear(channel) == expected


def test_other_files_are_not_ljstream_configs():
    assert parse_ljstream_cfg("[Main]\nDeviceType=ANY\nConnectionType=ANY\n") is None
    assert parse_ljstream_cfg("key=value without a section") is None
    assert parse_ljstream_cfg('{"json": true}') is None
    disabled = parse_ljstream_cfg(CFG.replace("DisableScaling=FALSE", "DisableScaling=TRUE"))
    assert disabled.scaling_disabled
