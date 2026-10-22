"""The deterministic planner: intents of the analysis become tool calls with filters."""

from backend.indexing.retrieval import Scope
from backend.llm_engine.engine.analysis import QueryAnalysis, resolve
from backend.llm_engine.engine.playbooks import UNAVAILABLE, build_plan
from backend.llm_engine.enrichment.entities import AliasIndex


def plan_for(**raw):
    analysis = resolve(QueryAnalysis(**raw), AliasIndex(), user_groups=[], external_allowed_groups=[])
    return build_plan("question", analysis)


def test_telemetry_without_route_c_falls_back_to_report_tables_and_says_so():
    plan = plan_for(intents=["telemetry_metric"], test_plan_ids=["TP7"])
    tools = [c.tool for c in plan.calls]
    assert tools == ["catalog_lookup", "search_documents", "search_documents"]
    assert plan.calls[0].args.test_plan_id == "TP07"
    assert plan.calls[1].args.scope == Scope.TABLES_ONLY
    assert plan.calls[1].args.filters.test_plan_ids == ["TP07"]
    assert plan.caveats == [UNAVAILABLE["query_telemetry"]]


def test_failure_investigation_searches_reports_figures_and_diagram_neighbors():
    plan = plan_for(intents=["failure_investigation"], hardware_items=["Injector 14"])
    kinds = [c.args.filters.doc_kinds for c in plan.calls if c.tool == "search_documents"]
    assert ["test_report", "failure_report"] in kinds
    assert any(c.tool == "search_documents" and c.args.scope == Scope.FIGURES_ONLY for c in plan.calls)
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
