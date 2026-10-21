import pytest

from backend.llm_engine.engine.verifier import check_numeric_claims, numeric_values

TOOL = [
    '{"peak_raw": "52.4 bar(a)", "t_peak": "+12 ms", "steady_mean": "12.4 bar(a)", "sampling": "1 kHz",'
    ' "peak_50ms": {"label": "50 ms peak", "value": "38.1 bar(a)"}, "window": "+1.0 s to +9.8 s"}',
    "Test report table 3: steady state 12.5 bar",
]


def test_claims_that_copy_tool_strings_pass():
    claims = [
        "Instantaneous peak 52.4 bar(a) at +12 ms; 50 ms peak 38.1 bar(a).",
        "Steady-state mean 12.4 bar(a) over +1.0 to +9.8 s, sampled at 1 kHz.",
        "The report lists 12.5 bar for steady state.",
    ]
    assert check_numeric_claims(claims, TOOL) == []


@pytest.mark.parametrize(
    ("claim", "value", "reason"),
    [
        ("Steady-state mean 12 bar(a).", "12", "value not in any tool result"),
        ("Steady-state mean 12.40 bar(a).", "12.40", "value not in any tool result"),
        ("Steady-state mean 12.4 bar.", "12.4", "value appears with another unit"),
        ("Peak 53 bar(a) at ignition.", "53", "value not in any tool result"),
        ("Bed temperature reached 600 °C.", "600", "value not in any tool result"),
    ],
)
def test_rounded_reunited_or_invented_numbers_are_reported(claim, value, reason):
    (mismatch,) = check_numeric_claims([claim], TOOL)
    assert (mismatch.value, mismatch.reason) == (value, reason)


def test_value_unit_pairs_read_function_words_as_no_unit():
    assert numeric_values("12.4 bar(a) over +1.0 to +9.8 s, 600 °C, 5 %") == [
        ("12.4", "bar(a)"),
        ("+1.0", None),
        ("+9.8", "s"),
        ("600", "°C"),
        ("5", "%"),
    ]
