"""The deterministic planner: intents of the analysis become tool calls with filters."""

from backend.indexing.retrieval import Scope
from backend.llm_engine.engine.analysis import QueryAnalysis, resolve
from backend.llm_engine.engine.playbooks import build_plan
from backend.llm_engine.enrichment.entities import AliasIndex


def plan_for(**raw):
    analysis = resolve(QueryAnalysis(**raw), AliasIndex(), user_groups=[], external_allowed_groups=[])
    return build_plan("question", analysis)


def test_telemetry_asks_for_t2_arguments_and_cross_checks_report_tables():
    plan = plan_for(intents=["telemetry_metric"], test_plan_ids=["TP7"])
    tools = [c.tool for c in plan.calls]
    assert plan.needs_telemetry_args is True
    assert tools == ["search_documents", "search_documents"]  # which runs exist: the catalog step, before
    assert plan.calls[0].args.scope == Scope.TABLES_ONLY
    assert plan.calls[0].args.filters.test_plan_ids == ["TP07"]
    assert plan.caveats == []
    assert plan_for(intents=["failure_investigation"], test_plan_ids=["TP7"]).needs_telemetry_args
    assert not plan_for(intents=["failure_investigation"]).needs_telemetry_args


def test_failure_investigation_searches_reports_figures_and_diagram_neighbors():
    plan = plan_for(intents=["failure_investigation"], hardware_items=["Injector 14"])
    searches = [c.args.filters for c in plan.calls if c.tool == "search_documents"]
    assert ["test_report", "failure_report"] in [f.prefer_doc_kinds for f in searches]  # ranks them higher
    assert all(f.doc_kinds == [] for f in searches)  # a guessed kind hides nothing
    [photos] = [c for c in plan.calls if c.tool == "inspect_visuals"]
    assert photos.args.kinds == ["hardware_photo"] and photos.args.relook_question is None
    assert "INJ14" in photos.args.components or "Injector 14" in photos.args.components
    [diagram] = [c for c in plan.calls if c.tool == "inspect_code_and_diagrams"]
    assert diagram.args.mode == "diagram_neighbors" and diagram.args.from_tag == "INJ14"


def test_internal_only_scope_and_duplicate_calls():
    plan = plan_for(intents=["fact_lookup", "navigational"], source_scope="internal_only")
    searches = [c for c in plan.calls if c.tool == "search_documents"]
    assert len(searches) == 1  # the navigational search equals the fact search and is not repeated
    assert searches[0].args.filters.source_origins == ["internal"]


def test_physics_and_summary_flags_and_chitchat_plans_nothing():
    assert plan_for(intents=["physics_calc"]).needs_physics_args is True
    assert plan_for(intents=["physics_calc"]).calls == []
    summary = plan_for(intents=["document_summary"])
    assert summary.read_top_document and summary.calls[0].args.scope == Scope.PARENT
    assert plan_for(intents=["chitchat_or_out_of_scope"]).calls == []


def external_plan(groups, **raw):
    analysis = resolve(
        QueryAnalysis(**raw), AliasIndex(), user_groups=groups, external_allowed_groups=["ext"]
    )
    return build_plan("question", analysis)


def test_external_search_follows_the_policy():
    assert external_plan(["ext"], intents=["fact_lookup"], external_requested=True).external == "yes"
    assert external_plan(["ext"], intents=["design_synthesis"]).external == "if_gap"
    assert external_plan(["ext"], intents=["fact_lookup"]).external == "no"
    internal = external_plan(
        ["ext"], intents=["fact_lookup"], external_requested=True, source_scope="internal_only"
    )
    assert internal.external == "no"
    refused = external_plan(["eng"], intents=["fact_lookup"], external_requested=True)
    assert refused.external == "no" and any("not enabled for your groups" in c for c in refused.caveats)


def test_visual_lookup_plans_inspect_visuals_with_a_relook():
    plan = plan_for(intents=["visual_lookup"], test_plan_ids=["TP7"])
    [visuals] = [c for c in plan.calls if c.tool == "inspect_visuals"]
    assert visuals.args.test_plan_ids == ["TP07"]
    assert visuals.args.relook_question == "question"
    assert not any("photo similarity" in c for c in plan.caveats)


def test_the_models_passage_words_become_stored_node_types_and_unknown_kinds_are_dropped():
    from backend.llm_engine.engine.analysis import Filters

    filters = Filters(
        node_types=["tables", "Photos", "code", "spreadsheets"], doc_kinds=["test_plan", "sheet"]
    )
    assert filters.node_types == ["table", "table_row", "photo", "code_symbol", "module_header", "config"]
    assert filters.doc_kinds == ["test_plan"]


def test_searches_stay_inside_the_files_the_question_was_resolved_to():
    analysis = resolve(
        QueryAnalysis(intents=["fact_lookup", "standards_compliance"]),
        AliasIndex(),
        user_groups=[],
        external_allowed_groups=[],
    )
    doc = "00000000-0000-4000-8000-000000000012"
    analysis.catalog = {"chosen": {"owner": "TP12", "run": "T04"}, "doc_ids": [doc]}
    plan = build_plan("Peak pressure in TP12 Test 04", analysis)
    filters = {c.reason: c.args.filters for c in plan.calls if c.tool == "search_documents"}
    assert [str(d) for d in filters["the passages that state it"].doc_ids] == [doc]
    assert filters["the requirement clause"].doc_ids == []  # a standard is never inside the test's files


def test_photos_ask_for_hardware_photos_only_and_no_kind_asks_for_all():
    photos = plan_for(intents=["visual_lookup"], filters={"node_types": ["photos"]})
    [call] = [c for c in photos.calls if c.tool == "inspect_visuals"]
    assert call.args.kinds == ["hardware_photo"]
    [call] = [c for c in plan_for(intents=["visual_lookup"]).calls if c.tool == "inspect_visuals"]
    assert call.args.kinds == []
