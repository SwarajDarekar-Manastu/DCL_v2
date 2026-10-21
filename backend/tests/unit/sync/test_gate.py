"""Gate tiers 1–3 and the download scope, against the file 02 §4 lists and §9 edge cases."""

from pathlib import Path

import pytest

from backend.postgres.enums import DriveItemStatus as S
from backend.sync.gate import GateConfig, GateInput, folder_flags, gate_item
from backend.sync.scope import HELD_BY_DOWNLOAD_SCOPE, in_scope

CONFIG = GateConfig.load(Path(__file__).with_name("gate_test_config.yaml"))
TEAM = ["APU Injector", "Test Plan 30", "Pressure_Data_Files"]
GB = 1024**3


def verdict(name, folders=TEAM, size=1000, **flags):
    result = gate_item(GateInput(name=name, size_bytes=size, folder_names=folders, **flags), CONFIG)
    return None if result is None else (result.status, result.gate_reason)


@pytest.mark.parametrize(
    "name",
    [
        "TP30_T01.dat",
        "TP30_T02.dat_fail",
        "run.csv",
        "FMEA.xlsx",
        "ECSS-M-50B.xsd",
        "Thruster config Rev C.drawio",
        "model.wbpz",
        "part.scdoc",
        "t02_00",
        "run_test.bat",
        "notes.txt",
        "README.md",
        "11bar_10sec.dat.gz",
        "arr.npy",
        "photo.png",
        "sample.mat",
        "data.pkl",
        "report.pdf",
        "macro.xlsm",
    ],
)
def test_team_folder_files_are_accepted(name):
    assert verdict(name) is None


@pytest.mark.parametrize(
    ("folders", "segment"),
    [
        (["APU", "tools", ".venv", "Lib"], ".venv"),
        (["APU", "tools", "venv", "lib", "site-packages", "numpy"], "venv"),
        (["APU", "pkg", "dcl_tools.egg-info"], "dcl_tools.egg-info"),
        (["APU", "gui", "__pycache__"], "__pycache__"),
        (["APU", "Build"], "Build"),
    ],
)
def test_tier1_path_segments_reject_everything_below_them(folders, segment):
    assert verdict("sample.csv", folders) == (S.SKIPPED_JUNK, f"T1:{segment}")
    assert verdict("photo.png", folders) == (S.SKIPPED_JUNK, f"T1:{segment}")


@pytest.mark.parametrize(
    ("folders", "segment"),
    [
        (["APU", "_to_delete"], "_to_delete"),
        (["APU", "Old", "TP07"], "Old"),
        (["APU", "TP30 (old)"], "TP30 (old)"),
    ],
)
def test_quarantine_paths_are_quarantined_with_metadata_kept(folders, segment):
    assert verdict("run.dat", folders) == (S.QUARANTINED, f"T1:quarantine:{segment}")


def test_junk_wins_over_quarantine():
    assert verdict("a.py", ["APU", "_to_delete", ".venv"]) == (S.SKIPPED_JUNK, "T1:.venv")


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("main.aux", "T2:.aux"),
        ("main.synctex.gz", "T2:.synctex.gz"),
        ("main.synctex(busy)", "T2:.synctex(busy)"),
        ("diagram.drawio.bkp", "T2:.bkp"),
        ("run.tdms_index", "T2:.tdms_index"),
        ("module.cpython-312.pyc", "T2:.pyc"),
        ("~$report.docx", "T2:~$"),
        (".DS_Store", "T2:.DS_Store"),
        ("THUMBS.DB", "T2:THUMBS.DB"),
        ("download.crdownload", "T2:.crdownload"),
        ("Setup.EXE", "T2:.exe"),
    ],
)
def test_tier2_names_and_extensions(name, reason):
    assert verdict(name) == (S.SKIPPED_JUNK, reason)


def test_conditional_extension_is_junk_only_under_its_folder():
    assert verdict("macro.xlsm", ["APS - Library", "tools", "Lib"]) == (S.SKIPPED_JUNK, "T2:.xlsm")
    assert verdict("Sizing_Calculator.xlsm", ["APS - Library", "Vendor tools"]) is None
    assert verdict("macro.xlsm") is None


def test_numeric_looking_endings_are_matched_as_text():
    assert verdict("numpy.1") == (S.SKIPPED_JUNK, "T2:.1")


def test_a_pattern_that_is_not_a_string_is_refused():
    with pytest.raises(ValueError, match="quote it in the YAML"):
        GateConfig.from_mapping({"junk_extensions": [0.1], "max_download_bytes": 1})


def test_tier3_size_and_type_sanity():
    assert verdict("empty.csv", size=0) == (S.SKIPPED_EMPTY, "T3:empty")
    assert verdict("Notebook", is_package=True) == (S.SKIPPED_UNSUPPORTED_PACKAGE, "T3:package")
    assert verdict("link.url") == (S.SKIPPED_SHORTCUT, "T3:shortcut")
    assert verdict("Shared thing", is_shortcut=True) == (S.SKIPPED_SHORTCUT, "T3:shortcut")
    assert verdict("firing.mp4", size=5 * GB) == (S.HELD_LARGE_FILE, "T3:size")
    assert verdict("firing.mp4", size=4 * GB) is None


def test_folder_flags_follow_the_path():
    assert folder_flags(["APU", "tools", ".venv", "Lib"], CONFIG) == (True, False)
    assert folder_flags(["APU", "_to_delete", "x"], CONFIG) == (False, True)
    assert folder_flags(TEAM, CONFIG) == (False, False)


# ---------- download scope ----------


def test_empty_scope_holds_nothing():
    assert in_scope([], "APU", set(), "APU/anything/x.dat")


@pytest.mark.parametrize(
    "scope",
    [["APU Injector"], ["FOLDER-TP30"], ["APU Injector/Test Plan 30/*"], ["apu injector/test plan 30/*"]],
)
def test_root_folder_id_and_glob_entries_match(scope):
    assert in_scope(scope, "APU Injector", {"ROOT-1", "FOLDER-TP30"}, "APU Injector/Test Plan 30/run.dat")


def test_outside_the_scope_is_held_with_the_scope_reason():
    assert not in_scope(["APU Heater", "FOLDER-TP31"], "APU", {"ROOT-2", "FOLDER-TP30"}, "APU/TP30/run.dat")
    assert HELD_BY_DOWNLOAD_SCOPE.status == S.HELD_BY_SCOPE
    assert HELD_BY_DOWNLOAD_SCOPE.gate_reason == "SCOPE:not_in_download_scope"


def test_root_name_entry_does_not_match_a_prefix_root():
    assert not in_scope(["APU"], "APU Heater", {"ROOT-3"}, "APU Heater/x.dat")
