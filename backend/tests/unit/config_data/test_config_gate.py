"""config/gate.yaml loads in the GateConfig schema, equals the file 02 §4 lists, and decides the
edge cases correctly. Behavior cases run through the documented matching rule and, once
backend/sync/gate.py (S1) is on main, through the real gate as well."""

import importlib.util
from fnmatch import fnmatchcase

import jsonschema
import pytest

STRINGS = {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}
SCHEMA = {
    "type": "object",
    "required": ["junk_path_segments", "quarantine_path_patterns", "junk_extensions", "junk_names",
                 "junk_name_prefixes", "junk_extensions_under", "shortcut_extensions", "max_download_bytes"],
    "additionalProperties": False,
    "properties": {
        "junk_path_segments": STRINGS,
        "quarantine_path_patterns": STRINGS,
        "junk_extensions": STRINGS,
        "junk_names": STRINGS,
        "junk_name_prefixes": STRINGS,
        "junk_extensions_under": {"type": "object", "additionalProperties": STRINGS},
        "shortcut_extensions": STRINGS,
        "max_download_bytes": {"type": "integer", "minimum": 1},
    },
}

# Literal lists of docs/architecture/02_phase1_ingestion_sync.md §4.
MANUAL_TIER1 = [".venv", "venv", "env", "site-packages", "__pycache__", ".git", ".idea", ".vscode",
                "build", "dist", "node_modules", ".ipynb_checkpoints", ".mypy_cache", ".pytest_cache",
                ".tox", ".eggs", "*.egg-info"]
MANUAL_QUARANTINE = ["_to_delete", "old", "archive_old", "backup"]
MANUAL_TIER2 = (
    ".pyc .pyi .pyd .typed .dll .exe .lib .a .so .o .qml .qmltypes .qm .pak .metainfo .mesh .frag .bin "
    ".h .c .cpp .pxd .pyx .f90 .f .f95 .pyf .inc .f2py_f2cmap .afm .ttf .mplstyle .ico .icns .ani .cls "
    ".bas .xlam .applescript .asp .pys .vbs .sct .idl .rc .chm .pyw .tab .zi .tpl .tmpl .template .build "
    ".cmake .toml .pc .pth .spec .whl .rst .apache .bsd .python .external .ps1 .fish .pem .lua "
    ".xrc .al .g4 .lark .gitignore .iml "
    ".aux .log .toc .lof .lot .out .fls .fdb_latexmk .synctex .synctex(busy) .synctex.gz .bbl .blg .nav "
    ".snm .vrb .bkp .tdms_index .tmp .crdownload .part"
).split()


@pytest.fixture(scope="module")
def gate(load_config):
    return load_config("gate.yaml")


def reference_decision(cfg, name, folders, size=1000):
    """The matching rule documented in config/gate.yaml and backend/sync/gate.py."""
    fold = [f.casefold() for f in folders]
    low = name.casefold()

    def hit(globs):
        return any(fnmatchcase(f, g.casefold()) for f in fold for g in globs)

    if hit(cfg["junk_path_segments"]):
        return "SKIPPED_JUNK"
    if hit(cfg["quarantine_path_patterns"]):
        return "QUARANTINED"
    if low in {n.casefold() for n in cfg["junk_names"]} \
            or any(low.startswith(p.casefold()) for p in cfg["junk_name_prefixes"]) \
            or any(low.endswith(e.casefold()) for e in cfg["junk_extensions"]) \
            or any(low.endswith(e.casefold()) and hit(g) for e, g in cfg["junk_extensions_under"].items()):
        return "SKIPPED_JUNK"
    if any(low.endswith(e.casefold()) for e in cfg["shortcut_extensions"]):
        return "SKIPPED_SHORTCUT"
    if not size:
        return "SKIPPED_EMPTY"
    if size > cfg["max_download_bytes"]:
        return "HELD_LARGE_FILE"
    return "ACCEPTED"


def s1_decision(_cfg, name, folders, size=1000):
    from pathlib import Path

    from backend.sync.gate import GateConfig, GateInput, gate_item

    config = GateConfig.load(Path(__file__).resolve().parents[4] / "config" / "gate.yaml")
    verdict = gate_item(GateInput(name=name, size_bytes=size, folder_names=folders), config)
    return "ACCEPTED" if verdict is None else str(verdict.status)


DECIDERS = [pytest.param(reference_decision, id="documented_rule"),
            pytest.param(s1_decision, id="s1_gate", marks=pytest.mark.skipif(
                importlib.util.find_spec("backend.sync.gate") is None,
                reason="backend/sync/gate.py not on main yet"))]

CASES = [
    ("report.synctex.gz", ["APU", "Test Plan 37", "report"], "SKIPPED_JUNK"),
    ("11bar_10sec.dat.gz", ["APU Injector", "Pressure_Data_Files"], "ACCEPTED"),
    ("T01.dat_fail", ["APU", "Test Plan 07"], "ACCEPTED"),
    ("run.tdms_index", ["APU Heater", "Test Plan 30"], "SKIPPED_JUNK"),
    ("report_v1.1", ["APU", "Test Plan 37"], "ACCEPTED"),
    ("LabJack_stream.ini", ["APU Injector", "Pressure_Data_Files"], "ACCEPTED"),
    ("setup.ini", ["APU", "tools", ".venv", "Lib"], "SKIPPED_JUNK"),
    ("Thruster Config Rev C.drawio", ["APU", "Diagrams"], "ACCEPTED"),
    ("Thruster Config Rev C.drawio.bkp", ["APU", "Diagrams"], "SKIPPED_JUNK"),
    ("~$Test_Report_37.docx", ["APU", "Test Plan 37"], "SKIPPED_JUNK"),
    ("Thumbs.db", ["APU", "photos"], "SKIPPED_JUNK"),
    ("data.csv", ["APU", "Test Plan 37"], "ACCEPTED"),
    ("data.csv", ["APU", "tools", ".venv", "Lib", "site-packages", "pandas", "tests"], "SKIPPED_JUNK"),
    ("T01.npy", ["APU Heater", "Test Plan 30"], "ACCEPTED"),
    ("T01.dat", ["APU Heater", "TP30 (old)"], "QUARANTINED"),
    ("T01.dat", ["APU Heater", "_to_delete", "Test Plan 30"], "QUARANTINED"),
    ("Sizing_Calculator.xlsm", ["APS - Library", "Vendor tools"], "ACCEPTED"),
    ("sample.xlsm", ["APU", "tools", "Library", "openpyxl"], "SKIPPED_JUNK"),
    ("report.xlsx", ["APU", "Test Plan 37"], "ACCEPTED"),
    ("OneDrive link.url", ["APU"], "SKIPPED_SHORTCUT"),
    ("Workshop.lnk", ["APU"], "SKIPPED_SHORTCUT"),
]


def test_schema(gate):
    jsonschema.validate(gate, SCHEMA)


def test_no_duplicates_after_casefold(gate):
    for key in ("junk_path_segments", "quarantine_path_patterns", "junk_extensions", "junk_names"):
        folded = [v.casefold() for v in gate[key]]
        assert len(folded) == len(set(folded)), key


def test_lists_equal_the_manual(gate):
    assert gate["junk_path_segments"] == MANUAL_TIER1
    assert gate["quarantine_path_patterns"] == MANUAL_QUARANTINE + ["* (old)"]  # S5 judgment call 2
    assert gate["junk_extensions"] == MANUAL_TIER2
    assert gate["junk_names"] == [".DS_Store", "Thumbs.db", "desktop.ini"]
    assert gate["junk_name_prefixes"] == ["~$"]
    assert list(gate["junk_extensions_under"]) == [".xlsm"]  # "(when under library)", judgment call 1
    assert gate["shortcut_extensions"] == [".url", ".lnk"]
    assert gate["max_download_bytes"] == 4 * 1024**3


def test_manual_not_rejected_list_survives(gate):
    # 02 §4 "What is deliberately not rejected"
    for name in ("run.dat_fail", "a.csv", "a.xlsx", "t02_00", "a.png", "a.jpg", "a.bat", "a.txt", "a.md",
                 "a.xsd", "a.drawio", "a.wbpz", "a.scdoc"):
        assert reference_decision(gate, name, ["APU", "Test Plan 37"]) == "ACCEPTED", name


@pytest.mark.parametrize("decide", DECIDERS)
@pytest.mark.parametrize("name, folders, expected", CASES, ids=[c[0] + "@" + "/".join(c[1]) for c in CASES])
def test_gate_decisions(gate, decide, name, folders, expected):
    assert decide(gate, name, folders) == expected


@pytest.mark.parametrize("decide", DECIDERS)
def test_size_tier(gate, decide):
    assert decide(gate, "long_test.mp4", ["APU", "videos"], size=5 * 1024**3) == "HELD_LARGE_FILE"
    assert decide(gate, "empty.txt", ["APU"], size=0) == "SKIPPED_EMPTY"
