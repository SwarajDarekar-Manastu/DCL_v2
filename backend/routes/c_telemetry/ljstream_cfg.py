"""LabJack LJStreamM ``.cfg`` (file 03 §C.0): the folder's stream configuration.

    [Main]
    ScanRate=1000.000000
    NumChan=8
    DisableScaling=FALSE
    Scaling=y=a*24.943-12.385#!#y=b*25.014-12.539#!#…   one equation per channel, letters a, b, c…

The ``.dat`` column ``yN`` is the equation with letter N applied to ``vN``. The file states the scaling
only, never the quantity or the unit, so it is evidence for a ``UNIT_AMBIGUITY`` flag and not a
channel map on its own.
"""

import configparser
import re
from dataclasses import dataclass, field

SEPARATOR = "#!#"
LINEAR = re.compile(
    r"^y\s*=\s*(?P<var>[a-p])(?:\s*\*\s*(?P<slope>[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?))?"
    r"(?:\s*(?P<sign>[-+])\s*(?P<offset>\d+(?:\.\d*)?(?:[eE][-+]?\d+)?))?\s*$"
)


@dataclass(frozen=True)
class LinearScaling:
    slope: float
    offset: float


@dataclass(frozen=True)
class LJStreamConfig:
    scan_rate_hz: float | None
    num_channels: int | None
    scaling_disabled: bool
    equations: dict[str, str] = field(default_factory=dict)  # "y0" → "y=a*24.943-12.385"

    def linear(self, channel: str) -> LinearScaling | None:
        """``slope``/``offset`` when the channel's equation is linear in its own letter, else None."""
        equation = self.equations.get(channel)
        match = LINEAR.match(equation.replace(" ", "")) if equation else None
        if match is None or ord(match["var"]) - ord("a") != int(channel[1:]):
            return None
        offset = float(match["offset"]) if match["offset"] else 0.0
        return LinearScaling(
            slope=float(match["slope"]) if match["slope"] else 1.0,
            offset=-offset if match["sign"] == "-" else offset,
        )


def parse_ljstream_cfg(text: str) -> LJStreamConfig | None:
    """The configuration, or None when the text is not an LJStreamM ``[Main]`` file with ``Scaling``."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # keep key case
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    if not parser.has_section("Main") or not parser.has_option("Main", "Scaling"):
        return None
    main = parser["Main"]
    count = _int(main.get("NumChan"))
    parts = [p.strip() for p in main.get("Scaling", "").split(SEPARATOR)]
    parts = [p for p in parts if p][: count if count else None]
    return LJStreamConfig(
        scan_rate_hz=_float(main.get("ScanRate")),
        num_channels=count,
        scaling_disabled=main.get("DisableScaling", "FALSE").strip().upper() == "TRUE",
        equations={f"y{i}": equation for i, equation in enumerate(parts)},
    )


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
