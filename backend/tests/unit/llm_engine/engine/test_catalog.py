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


def _files_of(monkeypatch, *files):
    """`subject_files` from the given files, by owner and run (no database)."""
    from backend.llm_engine.engine import catalog

    monkeypatch.setattr(
        catalog,
        "subject_files",
        lambda session, owner, run, folder: [f for f in files if f.owner == owner and f.test_run_id == run],
    )


def test_an_ambiguous_reading_goes_on_with_both_close_subjects_and_says_so(monkeypatch):
    files = [
        _file("a", "Test 04 Data Analysis", plan="TP12", run="T04", kind="engineering_table", score=0.3),
        _file("c", "Test_04_04Bar_ii_0", hardware="INJ14", run="T04", kind="telemetry_run", score=0.29),
    ]
    _files_of(monkeypatch, *files)
    catalog = CatalogResult("peak pressure in the fourth run", Labels(), group(files), [], [])
    decision = decide(None, catalog, resolution="ambiguous", subject_ids=[], intents=["telemetry_metric"])
    assert (decision.kind, decision.doc_ids, decision.pinned) == ("go", ["a", "c"], False)
    assert decision.caveats == ["Assumed: the question is about TP12 · Test 04 and INJ14 · Test 04."]


def test_copies_of_one_file_under_three_plans_answer_from_the_likeliest_and_name_the_others(monkeypatch):
    files = [
        _file("p7", "Test_plan_creator.py", plan="TP07", kind="code", score=0.5),
        _file("p12", "Test_plan_creator.py", plan="TP12", kind="code", score=0.4),
        _file("i10", "Test_plan_creator.py", hardware="INJ10", kind="code", score=0.38),
    ]
    _files_of(monkeypatch, *files)
    question = "What makes the test-plan creator script run pdflatex again?"
    catalog = CatalogResult(question, question_labels(question), group(files), [], [])
    decision = decide(None, catalog, resolution="ambiguous", subject_ids=[], intents=["code_walkthrough"])
    assert (decision.kind, decision.doc_ids, decision.pinned) == ("go", ["p7"], False)
    assert decision.caveats == ["Assumed: the question is about TP07; other matches: TP12, INJ10."]


def test_a_subject_the_model_picked_for_an_ambiguous_question_is_stated_too(monkeypatch):
    files = [
        _file("p7", "Test_plan_creator.py", plan="TP07", kind="code", score=0.5),
        _file("p12", "Test_plan_creator.py", plan="TP12", kind="code", score=0.4),
    ]
    _files_of(monkeypatch, *files)
    catalog = CatalogResult("what does the script write", Labels(), group(files), [], [])
    decision = decide(None, catalog, resolution="ambiguous", subject_ids=["S2"], intents=["code_walkthrough"])
    assert (decision.doc_ids, decision.pinned) == (["p12"], False)
    assert decision.caveats == ["Assumed: the question is about TP12; other matches: TP07."]


def test_a_typed_plan_pins_its_files(monkeypatch):
    files = [
        _file("a", "Test 04 Data Analysis", plan="TP12", run="T04", kind="engineering_table", score=0.29),
        _file("c", "Test_04_04Bar_ii_0", hardware="INJ14", run="T04", kind="telemetry_run", score=0.3),
    ]
    _files_of(monkeypatch, *files)
    question = "peak pressure in TP12 test 4"
    catalog = CatalogResult(question, question_labels(question), group(files), [], [])
    decision = decide(None, catalog, resolution="ambiguous", subject_ids=[], intents=["telemetry_metric"])
    assert (decision.kind, decision.doc_ids, decision.pinned, decision.caveats) == ("go", ["a"], True, [])


def test_a_run_under_two_owners_still_asks():
    options = [
        Option("1", "TP12 · Test 04: 1 engineering table", "TP12", "T04", None, ["a"]),
        Option("2", "INJ14 · Test 04: 1 telemetry run", "INJ14", "T04", None, ["c"]),
    ]
    question = "peak pressure in test 4"
    catalog = CatalogResult(question, question_labels(question), [], [], options)
    decision = decide(None, catalog, resolution="clear", subject_ids=[], intents=["telemetry_metric"])
    assert decision.kind == "ask"
    assert "1. TP12 · Test 04: 1 engineering table" in decision.text


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


def test_halted_measured_data_is_named_the_way_the_benchmark_checks_it(monkeypatch):
    from backend.benchmark import metrics
    from backend.benchmark.catalog import ExpectedBehavior
    from backend.llm_engine.engine import catalog

    run = _file("c", "Test_08_06Bar_iii_0", hardware="INJ14", run="T08", kind="telemetry_run")
    run.status, run.case_keys = "HALTED", ["22563376-b405-4e43-98a8-0264f4a0b09b:"]
    monkeypatch.setattr(catalog, "subject_files", lambda session, owner, run_, folder: [run])
    found = CatalogResult("chamber pressure in Injector 14 Test 08", Labels(), [], [], [])
    decision = decide(
        None,
        found,
        resolution="clear",
        subject_ids=[],
        intents=["telemetry_metric"],
        forced={"owner": "INJ14", "run": "T08", "folder": None, "label": "INJ14 · Test 08"},
    )
    assert decision.kind == "halted"
    observed = metrics.Observed(
        answer=decision.text, mode="insufficient_evidence", tools=[], tool_warnings=[], tool_displays=[],
        citations=[], claims=[], verdicts=[],
    )  # fmt: skip
    checks = metrics.behaviour([ExpectedBehavior.MUST_MENTION_HALTED_CASE], observed)["checks"]
    assert checks["must_mention_halted_case"]["passed"]


def test_a_longer_name_and_a_longer_folder_word_win():
    files = [
        _file("cfg", "Thruster Configuration", plan="TP23", folder="APU › Test Plan 23", kind="diagram"),
        _file("t7", "Thruster", plan="TP07", folder="APU › Test Plan 7 › De-Integration"),
        _file("t9", "Thruster", plan="TP09", folder="APU › Test Plan 9 › De-Integration"),
        _file("m1", "Catalyst Monolith", plan="TP12", folder="APU › Test Plan 12 › Figures › Integration"),
        _file("m2", "Catalyst Monolith", plan="TP12", folder="APU › Test Plan 12 › Figures › De-Integration"),
    ]
    drawing = "What material is the mesh made of in the thruster configuration Rev C drawing?"
    assert same_name_options(files, drawing, Labels()) == ("", [])
    photo = "What damage does the Test Plan 12 de-integration photo of the catalyst monolith show?"
    assert same_name_options(files, photo, question_labels(photo)) == ("", [])


def test_the_answer_picks_the_option_whose_folder_it_names_most_precisely():
    previous = {
        "ask": {
            "question": "Which injector number is on the Test Plan 12 Inj VF photo?",
            "options": [
                {"id": "1", "owner": "TP12", "folder": "APU › Test Plan 12 › Figures › De-Integration"},
                {"id": "2", "owner": "TP12", "folder": "APU › Test Plan 12 › Figures › Integration"},
            ],
        }
    }
    assert chosen_option(previous, "The de-integration photo.")["id"] == "1"
    assert chosen_option(previous, "the integration one")["id"] == "2"
    assert chosen_option(previous, "TP12") is None  # both are TP12: still open


def test_each_file_the_analysis_reads_names_its_answer_route():
    photo = _file("a", "Inj VF")
    code = _file("b", "Test_plan_creator.py", kind="code")
    code.route = "B"
    book = _file("c", "ECSS-E-ST-35-10C", kind="standard")
    book.route, book.folder_kind = "A1", "library"
    assert [f.line() for f in (photo, code, book)] == [
        "Inj VF (hardware_photo, route visual) in APU",
        "Test_plan_creator.py (code, route source) in APU",
        "ECSS-E-ST-35-10C (standard, route library) in APU",
    ]
