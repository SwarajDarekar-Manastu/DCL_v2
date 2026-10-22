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
    assert tools == ["catalog_lookup", "search_documents", "search_documents"]
    assert plan.calls[0].args.test_plan_id == "TP07"
    assert plan.calls[1].args.scope == Scope.TABLES_ONLY
    assert plan.calls[1].args.filters.test_plan_ids == ["TP07"]
    assert plan.caveats == []
    assert plan_for(intents=["failure_investigation"], test_plan_ids=["TP7"]).needs_telemetry_args
    assert not plan_for(intents=["failure_investigation"]).needs_telemetry_args


def test_failure_investigation_searches_reports_figures_and_diagram_neighbors():
    plan = plan_for(intents=["failure_investigation"], hardware_items=["Injector 14"])
    kinds = [c.args.filters.doc_kinds for c in plan.calls if c.tool == "search_documents"]
    assert ["test_report", "failure_report"] in kinds
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
