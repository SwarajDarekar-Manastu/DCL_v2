"""Which flags a re-run may close: the route's own, whatever they point at (2026-10-26)."""

from types import SimpleNamespace

from backend.review.staged import own_flags


def test_a_routes_own_flags_include_table_column_flags_but_not_assembler_notes():
    own = own_flags("C")
    table = SimpleNamespace(route="C", anchor={"sheet": "Valve_on_off", "column": "Mean"}, evidence={})
    channel = SimpleNamespace(route="C", anchor={"channel": "y0"}, evidence={})
    note = SimpleNamespace(route="C", anchor={}, evidence={"a": {"label": "assembler"}})
    other = SimpleNamespace(route="A1", anchor={}, evidence={})
    assert [own(f) for f in (table, channel, note, other)] == [True, True, False, False]
