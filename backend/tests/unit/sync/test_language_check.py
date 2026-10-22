"""Library language/DOI check: language from script census or function words; S5's synthetic PDFs."""

from pathlib import Path

import pytest

from backend.sync.language_check import check_pdf, detect_language, summarize

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "a1_office"


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("The thrust of the engine is measured with a load cell and the data are logged at 1 kHz.", "en"),
        (
            "Der Schub des Triebwerks wird mit einer Kraftmessdose gemessen und die Daten werden erfasst.",
            "de",
        ),
        (
            "La poussée du moteur est mesurée par une cellule de charge et les données sont enregistrées.",
            "fr",
        ),
        ("スラスタの推力はロードセルで測定され、データは1kHzで記録されます。推進剤は過酸化水素です。", "ja"),
        ("Тяга двигателя измеряется тензодатчиком, данные записываются с частотой один килогерц.", "ru"),
        (
            "(19) United States (12) Patent Application Publication (10) Pub. No.: US 2015/0121843 A1 "
            "a e o; the system and method for a valve in which the seat of the o-ring is e.g. a cone",
            "en",
        ),
        ("", "no_text"),
        ("Fig. 3 Tab. 4 kN bar K", "und"),
    ],
)
def test_detect_language(text, language):
    assert detect_language(text).language == language


def test_synthetic_library_pdfs():
    pytest.importorskip("pypdfium2")
    german = check_pdf((FIXTURES / "german_datasheet" / "MT-1_Datenblatt_DE.pdf").read_bytes())
    paper = check_pdf((FIXTURES / "doi_paper" / "preheat_paper_synthetic.pdf").read_bytes())
    scan = check_pdf((FIXTURES / "japanese_scanned_page" / "thruster_spec_ja_scan.pdf").read_bytes())
    assert (german.language, german.doi) == ("de", None)
    assert paper.language == "en" and paper.doi is not None and paper.doi.startswith("10.")
    assert scan.language == "no_text"
    assert check_pdf(b"not a pdf").language == "error"


def test_summary_lists_only_folders_with_foreign_files():
    rows = [
        {"folder": "Lib/A", "language": "en", "doi": "10.1/x"},
        {"folder": "Lib/B", "language": "de", "doi": ""},
        {"folder": "Lib/B", "language": "en", "doi": ""},
    ]
    assert summarize(rows) == (
        "3 PDFs; languages: {'en': 2, 'de': 1}\nwith a DOI on page 1-2: 1\n  Lib/B: {'de': 1, 'en': 1}"
    )
