"""The catalog step (engine/catalog.py): labels read from a question, the conflict signals, the ask-back and
the answer to it, and the check that a reframed question names nothing the catalog does not hold."""

from datetime import date

from backend.llm_engine.engine.catalog import (
    CatalogFile,
    CatalogResult,
    Labels,
    Option,
    chosen_option,
    decide,
    group,
    question_labels,
    reframing_ok,
    same_name_options,
)


def _file(doc, title, plan=None, run=None, hardware=None, folder="APU", kind="hardware_photo", score=0.1):
    return CatalogFile(
        doc_id=doc,
        title=title,
        doc_kind=kind,
        status="ACTIVE",
        route="D",
        doc_date=None,
        test_plan_id=plan,
        test_run_id=run,
        hardware_item=hardware,
        folder=folder,
        summary="",
        card=title,
        source_origin="internal",
        score=score,
    )


def test_labels_in_questions():
    assert question_labels("peak pressure in test 4").runs == ["T04"]
    assert question_labels("TP7 run 4").plans == ["TP07"] and question_labels("TP7 run 4").runs == ["T04"]
    plan_only = question_labels("What is in Test Plan 12?")
    assert (plan_only.plans, plan_only.runs) == (["TP12"], [])  # "Test Plan 12" is not run 12
    assert question_labels("Injector 14 test 3 pressure").hardware == ["INJ14"]
    assert question_labels("the firing of 13 Jan 2026").dates == [date(2026, 1, 13)]
    assert not question_labels("how does a catalyst bed work").named


def test_files_group_by_owner_and_run_or_by_folder():
    subjects = group(
        [
            _file("a", "Test 04 Pressure", plan="TP12", run="T04", score=0.3),
            _file("b", "Test 04 Data Analysis", plan="TP12", run="T04", score=0.2),
            _file("c", "Injector 14 - Test04", hardware="INJ14", run="T04", score=0.25),
            _file("d", "Clamp Heater 1", folder="APU Heater › 450W Heater", score=0.1),
        ]
    )
    assert [(s.id, s.label, len(s.files)) for s in subjects] == [
        ("S1", "TP12 · Test 04", 2),
        ("S2", "INJ14 · Test 04", 1),
        ("S3", "APU Heater › 450W Heater", 1),
    ]


def test_same_name_files_in_different_folders_conflict_unless_the_question_tells_them_apart():
    files = [
        _file("1", "Inj CC", plan="TP12", folder="APU › Test Plan 12 › Figures › Integration"),
        _file("2", "Inj CC", plan="TP12", folder="APU › Test Plan 12 › Figures › De-Integration"),
        _file("3", "Inj CC", plan="TP09", folder="APU › Test Plan 9 › Figures › De-Integration"),
    ]
    title, options = same_name_options(files, "show the inj cc photo", Labels())
    assert (title, [o.doc_ids for o in options]) == ("Inj CC", [["3"], ["2"], ["1"]])  # by plan, then folder
    _, narrowed = same_name_options(
        files, "show the TP09 inj cc photo", question_labels("show the TP09 inj cc photo")
    )
    assert narrowed == []  # one file left: nothing to ask
    _, by_folder = same_name_options(files, "the integration inj cc photo", Labels())
    assert [o.doc_ids for o in by_folder] == []


def test_an_ambiguous_reading_asks_with_the_real_subjects_and_no_database():
    subjects = group(
        [
            _file("a", "Test 04 Data Analysis", plan="TP12", run="T04", kind="engineering_table", score=0.3),
            _file("c", "Test_04_04Bar_ii_0", hardware="INJ14", run="T04", kind="telemetry_run", score=0.29),
        ]
    )
    catalog = CatalogResult(
        "peak pressure in test 4", question_labels("peak pressure in test 4"), subjects, [], []
    )
    decision = decide(None, catalog, resolution="ambiguous", subject_ids=[], intents=["telemetry_metric"])
    assert decision.kind == "ask"
    assert "1. TP12 · Test 04: 1 engineering table" in decision.text
    assert "2. INJ14 · Test 04: 1 telemetry run" in decision.text


def test_a_question_that_needs_no_particular_file_goes_on_unfiltered():
    catalog = CatalogResult("what is a catalyst bed", Labels(), [], [], [])
    decision = decide(None, catalog, resolution="clear", subject_ids=[], intents=["fact_lookup"])
    assert (decision.kind, decision.doc_ids, decision.subject) == ("go", [], None)


def test_the_answer_to_an_ask_back_picks_its_option():
    options = [
        Option("1", "TP12 · Test 04: 4 files", "TP12", "T04", None, ["a"]),
        Option("2", "INJ14 · Test 04: 1 telemetry_run", "INJ14", "T04", None, ["c"]),
    ]
    previous = {"ask": {"question": "peak pressure in test 4", "options": [o.__dict__ for o in options]}}
    assert chosen_option(previous, "TP12")["owner"] == "TP12"
    assert chosen_option(previous, "injector 14 please")["owner"] == "INJ14"
    assert chosen_option(previous, "2")["owner"] == "INJ14"
    assert chosen_option(previous, "the first one")["owner"] == "TP12"
    assert chosen_option(previous, "what is a catalyst bed?") is None
    assert chosen_option({"ask": None}, "TP12") is None


def test_a_reframed_question_may_only_name_known_identifiers():
    allowed = "peak pressure in test 4\nS1 TP12 · Test 04: 4 files"
    assert reframing_ok("Peak pressure in TP12 Test 04", allowed)
    assert not reframing_ok("Peak pressure in TP31 Test 04", allowed)


def test_a_numbered_name_is_the_same_name_and_a_bare_word_needs_a_kind_of_file():
    files = [
        _file("7", "03 VF Gasket", plan="TP07", folder="APU › Test Plan 7 › De-Integration › Initial"),
        _file("9", "VF Gasket", plan="TP09", folder="APU › Test Plan 9 › De-Integration"),
        _file("12", "VF Gasket", plan="TP12", folder="APU › Test Plan 12 › Integration"),
        _file("t7", "Thruster", plan="TP07", folder="APU › Test Plan 7 › De-Integration"),
        _file("t9", "Thruster", plan="TP09", folder="APU › Test Plan 9 › De-Integration"),
    ]
    title, options = same_name_options(files, "show the VF gasket photo", Labels())
    assert [o.owner for o in options] == ["TP07", "TP09", "TP12"]
    assert same_name_options(files, "what happened to the thruster", Labels()) == ("", [])
    _, photos = same_name_options(files, "show the thruster photo", Labels())
    assert [o.doc_ids for o in photos] == [["t7"], ["t9"]]
