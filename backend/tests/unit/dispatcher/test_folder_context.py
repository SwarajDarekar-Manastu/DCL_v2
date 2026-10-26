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


def test_test_numbers_in_real_file_names_are_runs():
    plots = ["APU", "Test Campaign 1", "Test Plan 12", "APU - Firing", "Test_plots"]
    injector = [
        "APU Injector",
        "Injector 14",
        "13012026 - Flow Test (No Mesh) Injector 14",
        "Pressure_Data_Files",
    ]
    cold_flow = ["APU Injector", "29122025 - Injector 10 Cold flow test", "Tables", "Observations_Test"]
    runs = {
        build_folder_context("APU", plots, "Test 04_Pressure_and_MFR_vs_Time.png").test_run_id,
        build_folder_context("APU Injector", injector, "Injector 14 - Test04.png").test_run_id,
        build_folder_context("APU Injector", cold_flow, "Test4_preheat.tex").test_run_id,
    }
    assert runs == {"T04"}


def test_plan_campaign_and_folder_words_are_not_runs():
    for name in (
        "Test_plan_creator.py",
        "Test_Input_Parameters.xlsx",
        "Thruster_DE_Integration_Sheet_TC_2_Test_Plan_07.pdf",
    ):
        assert (
            build_folder_context(
                "APU", ["APU", "Test Campaign 2", "Test Plan 7", "Test_setup"], name
            ).test_run_id
            is None
        )


def test_dates_in_folder_and_file_names():
    def dated(folders, name):
        return str(build_folder_context(folders[0], folders, name).doc_date)

    assert dated(["APU Injector", "29122025 - Injector 10 Cold flow test"], "Setup.xlsx") == "2025-12-29"
    assert dated(["APU", "30052025 - Test Videos"], "WIN_20250530_14_01_51_Pro.mp4") == "2025-05-30"
    assert (
        dated(["APU Heater", "450W Heater"], "2026.06.18 - Duct Cooling 450W - 280HT-14-10102025.docx")
        == "2026-06-18"
    )
    assert dated(["APU", "Temperature"], "Analog - 04-12-2025 13-25-17.6.csv") == "2025-12-04"
    assert dated(["APU", "De-Integration"], "WhatsApp Video 2025-12-04 at 18.13.13.mp4") == "2025-12-04"
    assert dated(["APU", "De-Integration"], "20251209_151812000_iOS.MOV") == "2025-12-09"


def test_long_digit_runs_and_library_files_get_no_date():
    assert build_folder_context("APU", ["APU", "Patents"], "DE102019119598A1.pdf").doc_date is None
    library = build_folder_context("APS - Library", ["APS - Library", "Preheat"], "2019.03.12 paper.pdf")
    assert library.doc_date is None


def test_a_date_the_route_read_wins_over_the_path_date():
    from datetime import date

    from backend.dispatcher.contract import DocumentFields, ProcessedDocument
    from backend.dispatcher.folder_context import with_folder_labels

    folder = build_folder_context(
        "APU Injector", ["APU Injector", "Injector 14", "13012026 - Flow Test"], "Injector 14 - Test03.png"
    )
    blank = ProcessedDocument(
        blob_sha256="0" * 64,
        route="D",
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{'0' * 64}/D/v1/",
        document=DocumentFields(title="Injector 14 - Test03"),
    )
    filled = with_folder_labels(blank, folder).document
    assert (filled.test_run_id, filled.hardware_item, str(filled.doc_date), filled.date_source) == (
        "T03",
        "INJ14",
        "2026-01-13",
        "path",
    )
    read = blank.model_copy(
        update={"document": DocumentFields(title="x", doc_date=date(2026, 1, 14), date_source="exif")}
    )
    assert (
        with_folder_labels(read, folder).document.doc_date,
        with_folder_labels(read, folder).document.date_source,
    ) == (
        date(2026, 1, 14),
        "exif",
    )
