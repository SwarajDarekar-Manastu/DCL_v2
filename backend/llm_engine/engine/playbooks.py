"""Step 2 of the workflow, the planner (file 07 §5): playbooks turn the analysis into tool calls.

The plan is deterministic: each intent of the analysis selects its playbook, and the playbook fills the tool
arguments from the analysis (test plans, runs, hardware, entities, document kinds, source scope).
Sub-questions
add searches. Only the physics calculator needs free parameters from the question; they come from one
structured extraction call (`physics_args.v1`). Tools that are not available yet (T2 telemetry, T3 visuals,
T6 external) are planned as fallbacks — tables-only or figures-only searches — and the plan says so.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel

from backend.indexing.retrieval import Scope, SearchFilters
from backend.llm_engine.engine.analysis import Analysis, Intent, SourceScope
from backend.llm_engine.engine.tools.code_diagrams import CodeDiagramArgs
from backend.llm_engine.engine.tools.documents import CatalogArgs, GetDocumentArgs
from backend.llm_engine.engine.tools.search import SearchDocumentsArgs
from backend.postgres.enums import EntityType, SourceOrigin

FAILURE_KINDS = ["test_report", "failure_report"]
PROCEDURE_KINDS = ["procedure", "test_plan", "calibration"]
UNAVAILABLE = {
    "query_telemetry": (
        "telemetry statistics (Route C) are not available yet; numbers come from report tables"
    ),
    "inspect_visuals": "photo similarity search is not available yet; figures come from document search",
    "external_search": "external search is not available yet; only internal and library material was used",
}


@dataclass(frozen=True)
class PlannedCall:
    tool: str
    args: BaseModel | None
    reason: str


@dataclass
class Plan:
    calls: list[PlannedCall] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    needs_physics_args: bool = False
    read_top_document: bool = False

    def add(self, tool: str, args: BaseModel | None, reason: str) -> None:
        key = (tool, args.model_dump_json() if args is not None else None)
        if all((c.tool, c.args.model_dump_json() if c.args is not None else None) != key for c in self.calls):
            self.calls.append(PlannedCall(tool, args, reason))

    def note_unavailable(self, tool: str) -> None:
        if UNAVAILABLE[tool] not in self.caveats:
            self.caveats.append(UNAVAILABLE[tool])


def _origins(analysis: Analysis) -> list[str]:
    if analysis.raw.source_scope == SourceScope.INTERNAL_ONLY:
        return [SourceOrigin.INTERNAL]
    return []


def _filters(analysis: Analysis, **overrides) -> SearchFilters:
    raw = analysis.raw.filters
    values = {
        "doc_kinds": raw.doc_kinds,
        "test_plan_ids": analysis.test_plan_ids,
        "source_origins": _origins(analysis),
        "include_superseded": raw.include_superseded,
        "node_types": raw.node_types,
    }
    values.update(overrides)
    return SearchFilters(**values)


def _search(
    analysis: Analysis, query: str, *, scope: Scope = Scope.CHILD, k: int = 8, **filters
) -> SearchDocumentsArgs:
    return SearchDocumentsArgs(
        query=query,
        filters=_filters(analysis, **filters),
        entity_ids=analysis.entity_ids,
        k=k,
        scope=scope,
        user_language=analysis.raw.language,
    )


def _tags(analysis: Analysis) -> list[str]:
    tag_types = {EntityType.SENSOR_TAG, EntityType.PART_NUMBER, EntityType.COMPONENT}
    return [e.surface for e in analysis.raw.entities if e.type in tag_types] + analysis.hardware_items


def build_plan(question: str, analysis: Analysis) -> Plan:
    plan = Plan()
    intents = set(analysis.raw.intents)
    if intents == {Intent.CHITCHAT}:
        return plan
    if intents & {Intent.TELEMETRY_METRIC, Intent.RUN_COMPARISON}:
        plan.note_unavailable("query_telemetry")
        plan.add(
            "catalog_lookup",
            CatalogArgs(test_plan_id=(analysis.test_plan_ids or [None])[0]),
            "which runs and reports exist for the plan",
        )
        plan.add(
            "search_documents",
            _search(analysis, question, scope=Scope.TABLES_ONLY),
            "report tables with the values",
        )
        plan.add("search_documents", _search(analysis, question), "report text about the runs")
    if intents & {Intent.FACT_LOOKUP, Intent.PROCEDURE_LOOKUP}:
        kinds = analysis.raw.filters.doc_kinds or (
            PROCEDURE_KINDS if Intent.PROCEDURE_LOOKUP in intents else []
        )
        plan.add(
            "search_documents", _search(analysis, question, doc_kinds=kinds), "the passages that state it"
        )
    if Intent.FAILURE_INVESTIGATION in intents:
        plan.add("search_documents", _search(analysis, question, doc_kinds=FAILURE_KINDS), "failure reports")
        plan.add(
            "search_documents", _search(analysis, question, scope=Scope.FIGURES_ONLY), "photos of the damage"
        )
        plan.note_unavailable("inspect_visuals")
        for tag in _tags(analysis)[:2]:
            plan.add(
                "inspect_code_and_diagrams",
                CodeDiagramArgs(mode="diagram_neighbors", from_tag=tag),
                f"what is connected to {tag}",
            )
    if Intent.STANDARDS_COMPLIANCE in intents:
        plan.add(
            "search_documents",
            _search(analysis, question, doc_kinds=["standard"], test_plan_ids=[]),
            "the requirement clause",
        )
        plan.add(
            "search_documents", _search(analysis, question, scope=Scope.TABLES_ONLY), "our values in tables"
        )
    if Intent.CODE_WALKTHROUGH in intents:
        symbols = [e.surface for e in analysis.raw.entities if e.type == EntityType.TOOL_SOFTWARE]
        if symbols:
            plan.add(
                "inspect_code_and_diagrams",
                CodeDiagramArgs(mode="callers_callees", symbol=symbols[0]),
                "the named symbol and its callers",
            )
        plan.add(
            "search_documents",
            _search(analysis, question, node_types=["code_symbol", "module_header"]),
            "code that implements it",
        )
    if Intent.DIAGRAM_TRAVERSAL in intents:
        tags = _tags(analysis)
        if len(tags) >= 2:
            plan.add(
                "inspect_code_and_diagrams",
                CodeDiagramArgs(mode="diagram_path", from_tag=tags[0], to_tag=tags[1]),
                "path between the tags",
            )
        elif tags:
            plan.add(
                "inspect_code_and_diagrams",
                CodeDiagramArgs(mode="diagram_path", from_tag=tags[0]),
                "upstream and downstream of the tag",
            )
        plan.add("search_documents", _search(analysis, question, doc_kinds=["diagram"]), "the diagram text")
    if Intent.DESIGN_SYNTHESIS in intents:
        plan.add(
            "search_documents",
            _search(analysis, question, source_origins=[SourceOrigin.INTERNAL]),
            "internal baselines",
        )
        plan.add(
            "search_documents",
            _search(analysis, question, source_origins=[SourceOrigin.EXTERNAL_KEPT]),
            "kept library: datasheets and papers",
        )
        plan.needs_physics_args = True
        if analysis.external_allowed:
            plan.note_unavailable("external_search")
    if Intent.PHYSICS_CALC in intents:
        plan.needs_physics_args = True
    if Intent.DOCUMENT_SUMMARY in intents:
        plan.add(
            "search_documents", _search(analysis, question, scope=Scope.PARENT, k=3), "find the document"
        )
        plan.read_top_document = True
    if Intent.NAVIGATIONAL in intents:
        plan.add(
            "catalog_lookup",
            CatalogArgs(
                doc_kinds=analysis.raw.filters.doc_kinds,
                test_plan_id=(analysis.test_plan_ids or [None])[0],
                entity_ids=analysis.entity_ids,
            ),
            "what exists",
        )
        plan.add("search_documents", _search(analysis, question), "where it is discussed")
    if Intent.VISUAL_LOOKUP in intents or analysis.raw.needs_visuals:
        plan.add(
            "search_documents", _search(analysis, question, scope=Scope.FIGURES_ONLY), "photos and plots"
        )
        plan.note_unavailable("inspect_visuals")
    for sub in analysis.raw.sub_questions:
        if sub.tool in (None, "search_documents"):
            plan.add("search_documents", _search(analysis, sub.text), f"sub-question: {sub.text}")
    if not plan.calls and not plan.needs_physics_args:
        plan.add("search_documents", _search(analysis, question), "general search")
    return plan


def read_document_call(doc_id) -> PlannedCall:
    return PlannedCall("get_document", GetDocumentArgs(doc_id=doc_id), "read the document found")
