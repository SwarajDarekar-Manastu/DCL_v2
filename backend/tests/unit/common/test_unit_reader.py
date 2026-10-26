"""The shared unit reader (plan step B): what a column measures first, then a unit that agrees with it."""

import pytest

from backend.common.unit_reader import ColumnKind, closest_word, edit_distance, read_unit

Q, UNITLESS, NOT_MEASUREMENT, UNKNOWN = (
    ColumnKind.QUANTITY,
    ColumnKind.UNITLESS,
    ColumnKind.NOT_MEASUREMENT,
    ColumnKind.UNKNOWN,
)


@pytest.mark.parametrize(
    ("label", "same_name", "kind", "unit", "basis", "settled"),
    [
        # a symbol is read through what the column measures: not coulomb, not siemens x litre
        ("Pre Heat Temperature [ C ]", None, Q, "degC", "read_by_meaning", True),
        ("Max Firing Temeprature [ C ]", None, Q, "degC", "read_by_meaning", True),  # typo in the file
        ("Risk Score\n(S × L)", None, UNITLESS, None, "unitless", True),
        ("Something [ C ]", None, UNKNOWN, None, "none", False),
        ("Mean (N)", None, Q, "N", "stated", True),
        # units written in other ways
        ("Preheat (\\textdegree C) [T4]", None, Q, "°C", "stated", True),
        ("Temperature in Celsius", None, Q, "celsius", "stated", True),
        ("Tank Pressure [gauge] (bar)", None, Q, "bar", "stated", True),
        ("Pressure Rating (bar)", None, Q, "bar", "stated", True),
        ("Efficiency (%)", None, UNITLESS, "%", "stated", True),
        # columns that take no unit
        ("Likelihood\n(1-5)", None, UNITLESS, None, "unitless", True),
        ("C_F", None, UNITLESS, None, "unitless", True),
        ("Pressure Ratio", None, UNITLESS, None, "unitless", True),
        ("Date of Test", None, NOT_MEASUREMENT, None, "not_measurement", True),
        ("Temperature Sensor ID", None, NOT_MEASUREMENT, None, "not_measurement", True),
        ("Exists? (Y/N)", None, NOT_MEASUREMENT, None, "not_measurement", True),
        # the same column name elsewhere, when every table agrees
        ("Thrust", {"thrust": ["N", "N"]}, Q, "N", "same_name", True),
        ("Thrust", {"thrust": ["N", "lbf"]}, Q, "N", "usual", False),
        ("column 5", {"column 5": ["s"]}, UNKNOWN, None, "none", False),
        # only the words: a guess for a person
        ("Chamber PT 1", None, Q, "bar", "usual", False),
        ("Part Temperature", None, Q, "degC", "usual", False),
        ("Valve Signal", None, UNKNOWN, None, "none", False),
    ],
)
def test_read_unit(label, same_name, kind, unit, basis, settled):
    reading = read_unit(label, same_name=same_name)
    assert (reading.kind, reading.unit, reading.basis, reading.settled) == (kind, unit, basis, settled)


def test_a_guess_stays_below_the_threshold_and_a_stated_unit_above_it():
    assert read_unit("Chamber PT 1").confident_unit is None
    assert read_unit("Thrust (N)").confident_unit == "N"


def test_a_misspelt_name_is_read_as_the_word_it_nearly_spells_and_says_so():
    stated = read_unit("Thurst (N)")
    assert (stated.unit, stated.confidence, stated.settled) == ("N", 0.79, True)
    assert stated.explained == "stated; read 'thurst' as 'thrust' (0.83)"
    guessed = read_unit("Chamber Presure")
    assert (guessed.unit, guessed.confidence, guessed.settled) == ("bar", 0.44, False)
    assert "read 'presure' as 'pressure' (0.88)" in guessed.explained


def test_short_words_are_never_corrected():
    assert closest_word("pres") is None and read_unit("Pres").kind == UNKNOWN
    assert closest_word("mass") is None  # a real word, not "pass"


def test_a_swap_of_two_letters_is_one_edit():
    assert edit_distance("temeprature", "temperature") == 1
    assert closest_word("temeprature") == ("temperature", 0.91)


def test_a_symbol_the_unit_list_does_not_know_is_named_for_the_reviewer():
    reading = read_unit("Pressure [kgcm]")
    assert (reading.unit, reading.basis, reading.unread) == ("bar", "usual", ("kgcm",))
    assert "not a known unit: 'kgcm'" in reading.explained


def test_a_persons_answer_on_the_same_name_elsewhere_is_learned():
    assert read_unit("Valve Signal", same_name={"valve signal": ["V"]}).confident_unit == "V"
    no_unit = read_unit("Error", same_name={"error": ["", ""]})
    assert (no_unit.kind, no_unit.settled) == (UNITLESS, True)
    assert not read_unit("Error", same_name={"error": ["", "%"]}).settled  # people disagree: ask again
