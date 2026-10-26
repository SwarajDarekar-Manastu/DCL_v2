"""Route C table units through the shared reader (plan step B), on the shapes of the real workbooks."""

from backend.routes.c_telemetry.tables import Table, table_nodes, unit_flags


def test_a_statistics_sheet_whose_rows_state_their_units_raises_no_flag():
    table = Table(
        rows=[
            ["Parameter", "Mean", "Roughness", "Max", "Min", "Std"],
            ["Pressure Suppy N2 [barg]", 10.41, 2.58, 11.02, 10.03, 0.27],
            ["Thrust [N]", 30.46, 69.18, 76.19, -0.29, 21.07],
            ["Mass Flow Rate [grams/s]", 90.12, 32.14, 112.31, 0, 28.96],
        ],
        sheet="Valve_on_off",
    )
    assert unit_flags(table) == []
    (node, *_) = table_nodes(table, "t0", 0, "Test 02 › Valve_on_off")
    assert node.metadata["row_units"] == {
        "Pressure Suppy N2 [barg]": "barg",
        "Thrust [N]": "N",
        "Mass Flow Rate [grams/s]": "grams/s",
    }


def test_a_bracketed_c_under_a_temperature_is_degc_not_coulomb():
    table = Table(
        rows=[["Location", "Pre Heat Temperature [ C ]"], ["CW near Flange", 348.5]], sheet="Temperature"
    )
    (node, *_) = table_nodes(table, "t0", 0, "Test 02 › Temperature")
    assert node.metadata["units"] == {"Pre Heat Temperature [ C ]": "degC"}
    assert node.metadata["unit_basis"] == {"Pre Heat Temperature [ C ]": "read_by_meaning 0.90"}


def test_a_units_row_is_read_with_its_column_name():
    table = Table(rows=[["Time", "Temperature"], ["s", "C"], [0, 300], [1, 310]])
    assert table.column_units() == {0: "s", 1: "degC"}


def test_a_register_of_files_and_scales_raises_no_flag():
    table = Table(
        rows=[
            ["Sr No.", "Part Number", "Date of Test", "Likelihood\n(1-5)"],
            [1, 1001, 1, 2],
            [2, 1002, 5, 4],
        ],
        sheet="Setup",
    )
    assert unit_flags(table) == []


def test_columns_named_elsewhere_with_one_unit_take_it_and_the_rest_carry_a_guess():
    table = Table(
        rows=[
            ["Tank Pressure", "Thrust", "Chamber PT 1", "Valve Signal"],
            [3.96, -7.3, 1.13, 5.85],
            [9.51, -4.5, 2.78, 5.92],
        ],
        sheet="Injector 10",
    )
    flags = unit_flags(table, {"tank pressure": ["bar", "bar"], "thrust": ["N"]})
    by_column = {f.anchor.column: f.evidence for f in flags}
    assert set(by_column) == {"Chamber PT 1", "Valve Signal"}
    pt = by_column["Chamber PT 1"]
    assert (pt.quantity_guess, [(c.unit, c.score, c.reason) for c in pt.candidate_units]) == (
        "pressure",
        [("bar", 0.5, "usual")],
    )
    assert by_column["Valve Signal"].candidate_units == []
    assert "may need no unit" in by_column["Valve Signal"].note
