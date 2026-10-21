"""Folder context: id inference with provenance, conflicts, folder kind, origin and trust tier."""

from backend.dispatcher.folder_context import build_folder_context
from backend.postgres.enums import SourceOrigin


def test_plan_run_and_hardware_ids_with_their_source():
    ctx = build_folder_context(
        "APU Injector", ["APU Injector", "Injector 14", "Test Plan 30", "Pressure_Data_Files"], "TP30_T01.dat"
    )
    assert (ctx.test_plan_id, ctx.test_run_id, ctx.hardware_item) == ("TP30", "T01", "INJ14")
    assert [i.source for i in ctx.inferences["test_plan_id"]] == ["folder[2]", "filename"]
    assert ctx.inferences["hardware_item"][0].source == "folder[1]"
    assert ctx.folder_kind == "pressure_data_files"
    assert ctx.conflicts == []
    assert ctx.path_cached == "APU Injector/Injector 14/Test Plan 30/Pressure_Data_Files/TP30_T01.dat"


def test_two_plan_ids_in_one_path_are_a_conflict_but_plan_plus_run_is_not():
    ctx = build_folder_context("APU", ["APU", "Test Plan 30"], "TP31_report.pdf")
    assert ctx.conflicts == ["two test plan ids in one path: TP30, TP31"]
    assert build_folder_context("APU", ["APU", "TP30"], "T02.dat").conflicts == []


def test_words_that_look_like_ids_are_not_ids():
    ctx = build_folder_context("APU", ["APU", "APS - AIT", "Test Campaign 2"], "Table1.csv")
    assert (ctx.test_plan_id, ctx.test_run_id, ctx.hardware_item) == (None, None, None)


def test_library_root_defaults_to_external_kept_with_a_lower_trust_tier():
    ctx = build_folder_context(
        "APS - Library", ["APS - Library", "Preheat"], "paper.pdf", root_origin=SourceOrigin.EXTERNAL_KEPT
    )
    assert (ctx.source_origin, ctx.trust_tier, ctx.folder_kind) == (SourceOrigin.EXTERNAL_KEPT, 4, "library")
    override = build_folder_context(
        "APU", ["APU", "Vendor"], "x.pdf", folder_origin_override=SourceOrigin.EXTERNAL_KEPT
    )
    assert override.source_origin == SourceOrigin.EXTERNAL_KEPT
