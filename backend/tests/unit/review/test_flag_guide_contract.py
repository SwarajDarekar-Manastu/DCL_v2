"""The Console's help text (frontend/console/.../flag_guide.ts) may only name actions the server allows.

The guide is TypeScript, ALLOWED_ACTIONS is Python: this reads the one from the other so a help line that
promises an action the server refuses (or the console cannot carry out) fails here, not before a reviewer.
"""

import re
from pathlib import Path

from backend.dispatcher.contract import ALLOWED_ACTIONS
from backend.postgres.enums import FlagType

CONSOLE = (
    Path(__file__).resolve().parents[4] / "frontend" / "console" / "src" / "lib" / "components" / "review"
)
GUIDE = (CONSOLE / "flag_guide.ts").read_text(encoding="utf-8")


def guide_actions() -> dict[str, set[str]]:
    entries = re.split(r"\n\t([A-Z_]+): \{", GUIDE.split("export const FLAG_GUIDE", 1)[1])
    return {
        entries[i]: set(re.findall(r"action: '([a-z_]+)'", entries[i + 1].split("\n\t},")[0]))
        for i in range(1, len(entries), 2)
    }


def test_the_guide_covers_every_flag_type_and_the_two_other_readings_of_a_conflict():
    assert set(guide_actions()) == {t.value for t in FlagType} | {"CONFLICT_CHECK", "CONFLICT_NOTE"}


def test_every_action_a_guide_names_is_allowed_for_that_flag_type():
    for key, actions in guide_actions().items():
        flag_type = FlagType("CONFLICT" if key.startswith("CONFLICT") else key)
        assert actions <= ALLOWED_ACTIONS[flag_type], (key, actions - ALLOWED_ACTIONS[flag_type])
