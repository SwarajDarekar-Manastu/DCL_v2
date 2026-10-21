import hashlib

import pytest

from backend.llm_engine.engine.sanitizer import SanitizerRefused, sanitize_query

PROPRIETARY = ["GreenBlend-7", "Project Garuda"]
PUBLIC = ["C-103", "ADN", "LMP-103S", "HTP"]

LEAKS = [
    ("why did INJ-14 fail in TP37 run 3", ["INJ-14", "TP37", "run 3"]),
    ("chamber pressure 12.37 bar in Test Plan 7 hot fire 2", ["12.37", "Test Plan 7", "hot fire 2"]),
    ("Manastu Space catalyst preheat data", ["Manastu"]),
    ("GreenBlend-7 decomposition rate for Project Garuda", ["GreenBlend-7", "Garuda"]),
    ("results in TP37_report.pdf and APU/TP37/runs/t02", ["TP37_report.pdf", "APU/TP37", "t02"]),
    (
        "ask ai@manastuspace.com about PT-101 calibration https://manastu.sharepoint.com/x",
        ["@", "PT-101", "sharepoint"],
    ),
    ("Dr. Asha Rao notes on catalyst poisoning", ["Asha Rao"]),
    ("drawing MS-DWG-0042 rev B injector plate", ["MS-DWG-0042"]),
    ("valve SV 1 response time", ["SV 1"]),
]


@pytest.mark.parametrize(("query", "secrets"), LEAKS, ids=[q for q, _ in LEAKS])
def test_internal_material_never_survives(query, secrets):
    """Either the query is refused outright or nothing internal is left in it."""
    try:
        result = sanitize_query(
            query, proprietary_terms=PROPRIETARY, people=["Asha Rao"], public_terms=PUBLIC
        )
    except SanitizerRefused:
        return
    for secret in secrets:
        assert secret.lower() not in result.text.lower()
    assert result.removed


@pytest.mark.parametrize(
    "query",
    [
        "space-grade solenoid valve 1/4 inch 300 bar",
        "low-power catalyst preheat for 5 N ADN-class thruster",
        "ECSS-E-ST-35C thermal margin for C-103 nozzles",
        "LMP-103S monopropellant thruster Isp",
    ],
)
def test_generic_needs_public_standards_and_class_sizes_survive(query):
    result = sanitize_query(query, public_terms=PUBLIC)
    assert result.text == query
    assert result.removed == {}


def test_original_is_logged_only_as_a_hash():
    result = sanitize_query("why did INJ-14 crack the catalyst bed", public_terms=PUBLIC)
    assert result.original_sha256 == hashlib.sha256(b"why did INJ-14 crack the catalyst bed").hexdigest()
    assert "INJ-14" not in result.text


@pytest.mark.parametrize("query", ["TP37 INJ-14 12.4 bar", "what about Manastu at 3.2 s", "INJ-14 in TP37"])
def test_query_with_nothing_generic_left_is_refused(query):
    with pytest.raises(SanitizerRefused):
        sanitize_query(query)
