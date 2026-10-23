"""The Console's unit list (channel_map.ts UNIT_GROUPS) may only name quantities the backend knows.

A name the backend refuses (the list once said ``mass_flow``, the enum says ``mass_flow_rate``) makes "Apply"
fail only for that unit, so it is checked here against ``Quantity`` instead of by a reviewer.
"""

import re
from pathlib import Path

from backend.postgres.enums import Quantity

SOURCE = (
    Path(__file__).resolve().parents[4]
    / "frontend"
    / "console"
    / "src"
    / "lib"
    / "components"
    / "review"
    / "channel_map.ts"
).read_text(encoding="utf-8")


def test_every_quantity_in_the_unit_list_is_a_backend_quantity():
    groups = SOURCE.split("export const UNIT_GROUPS", 1)[1].split("const ALL", 1)[0]
    quantities = set(re.findall(r"quantity: '([a-z_]+)', gauge_or_abs", groups))
    assert {"pressure", "temperature", "mass_flow_rate", "force", "voltage", "current"} <= quantities
    assert quantities <= {q.value for q in Quantity}, quantities - {q.value for q in Quantity}
