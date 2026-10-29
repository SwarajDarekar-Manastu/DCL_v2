"""Step 2 of the workflow, the planner (file 07 §5): playbooks turn the analysis into tool calls.

The plan is deterministic: each answer route the analysis names (the kind of data that holds the answer,
user 2026-10-29) runs its own search method, and the method fills the tool arguments from the analysis (test
plans, runs, hardware, entities, document kinds, source scope). A route prefers its own kinds of files and
pieces and excludes nothing. Intents add only what changes how the answer is built.
Sub-questions
add searches. Only the physics calculator needs free parameters from the question; they come from one
structured extraction call (`physics_args.v1`). Tools that are not available yet (T2 telemetry, T3 visuals,
T6 external) are planned as fallbacks — tables-only or figures-only searches — and the plan says so.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from backend.indexing.retrieval import Scope, SearchFilters
from backend.llm_engine.engine.analysis import Analysis, Intent, SourceScope
from backend.llm_engine.engine.answer_routes import SOURCE_KINDS, AnswerRoute
from backend.llm_engine.engine.tools.code_diagrams import CodeDiagramArgs
from backend.llm_engine.engine.tools.documents import GetDocumentArgs
from backend.llm_engine.engine.tools.search import SearchDocumentsArgs
from backend.llm_engine.engine.tools.visuals import InspectVisualsArgs
from backend.postgres.enums import EntityType, SourceOrigin

EXTERNAL_NOT_ALLOWED = (
    "external search is not enabled for your groups; only internal and library material was used"
)


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
    needs_telemetry_args: bool = False
    read_top_document: bool = False
    external: Literal["no", "if_gap", "yes"] = "no"

    def add(self, tool: str, args: BaseModel | None, reason: str) -> None:
        key = (tool, args.model_dump_json() if args is not None else None)
        if all((c.tool, c.args.model_dump_json() if c.args is not None else None) != key for c in self.calls):
            self.calls.append(PlannedCall(tool, args, reason))


def _origins(analysis: Analysis) -> list[str]:
    if analysis.raw.source_scope == SourceScope.INTERNAL_ONLY:
        return [SourceOrigin.INTERNAL]
    return []


def _settled(analysis: Analysis) -> list[str]:
    """The files the catalog step settled the question on (engine/catalog.py); empty when it settled none."""
    return list(analysis.catalog.get("doc_ids") or []) if analysis.catalog.get("chosen") else []


def _files(analysis: Analysis) -> dict[str, list[str]]:
    """The settled files as the only ones searched when the user typed or picked the subject, else ranked
    higher (PLAN_query_routing.md step 1)."""
    if analysis.catalog.get("pinned"):
        return {"doc_ids": _settled(analysis), "prefer_doc_ids": []}
    return {"doc_ids": [], "prefer_doc_ids": _settled(analysis)}


def _filters(analysis: Analysis, **overrides) -> SearchFilters:
    raw = analysis.raw.filters
    values = {
        # the files the question was resolved to (a pinned search widens when they hold nothing)
        **_files(analysis),
        "test_plan_ids": analysis.test_plan_ids,
        "source_origins": _origins(analysis),
        "include_superseded": raw.include_superseded,
        # the model's kinds are guesses: they rank matching passages higher and hide nothing
        "prefer_doc_kinds": raw.doc_kinds,
        "prefer_node_types": raw.node_types,
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


VISUAL_KINDS = {
    "photo": "hardware_photo",
    "figure": "plot_figure",
    "diagram_summary": "diagram",
    "video_event": "video_frame",
}


def _visuals(analysis: Analysis, question: str, *, kinds=(), relook: str | None = None) -> InspectVisualsArgs:
    """The visual kinds the question asks for ("photos": hardware photos only); all when it names none."""
    asked = [VISUAL_KINDS[t] for t in analysis.raw.filters.node_types if t in VISUAL_KINDS]
    return InspectVisualsArgs(
        query=question,
        kinds=list(kinds) or list(dict.fromkeys(asked)),
        test_plan_ids=analysis.test_plan_ids,
        components=_tags(analysis)[:3],
        **_files(analysis),
        relook_question=relook,
        user_language=analysis.raw.language,
    )


def similar_photos(analysis: Analysis, question: str, vector: list[float]) -> InspectVisualsArgs:
    """T3 for a photo the user attached (file 07 §9.7): nearest hardware photos by image embedding."""
    return _visuals(analysis, question, kinds=["hardware_photo"]).model_copy(
        update={"similar_to_vector": vector, "query": ""}
    )


def _tags(analysis: Analysis) -> list[str]:
    tag_types = {EntityType.SENSOR_TAG, EntityType.PART_NUMBER, EntityType.COMPONENT}
    return [e.surface for e in analysis.raw.entities if e.type in tag_types] + analysis.hardware_items


# A search-only intent (a reply without routes, an Open WebUI skill's hint) stands for the routes its
# playbook always searched.
INTENT_ROUTES: dict[Intent, tuple[AnswerRoute, ...]] = {
    Intent.FACT_LOOKUP: (AnswerRoute.DOCUMENT,),
    Intent.PROCEDURE_LOOKUP: (AnswerRoute.DOCUMENT,),
    Intent.FAILURE_INVESTIGATION: (AnswerRoute.DOCUMENT, AnswerRoute.VISUAL, AnswerRoute.DIAGRAM),
    Intent.STANDARDS_COMPLIANCE: (AnswerRoute.LIBRARY, AnswerRoute.TABLE),
    Intent.CODE_WALKTHROUGH: (AnswerRoute.SOURCE,),
    Intent.DIAGRAM_TRAVERSAL: (AnswerRoute.DIAGRAM,),
    Intent.VISUAL_LOOKUP: (AnswerRoute.VISUAL,),
    Intent.TELEMETRY_METRIC: (AnswerRoute.MEASURED,),
    Intent.RUN_COMPARISON: (AnswerRoute.MEASURED,),
}
LIBRARY_KINDS = [
    "standard", "datasheet", "vendor_brochure", "academic_paper", "conference_paper", "book_excerpt"
]  # fmt: skip


def apply_hint(analysis: Analysis, hint: str | None) -> Analysis:
    """An explicitly mentioned playbook (DECISIONS 2026-10-23, option c): its intent joins the analysed ones,
    its route joins the routes, and a question read as chit-chat is answered with the playbook instead."""
    if not hint:
        return analysis
    intents = [i for i in analysis.raw.intents if i != Intent.CHITCHAT]
    if Intent(hint) not in intents and Intent(hint) != Intent.CHITCHAT:
        intents.append(Intent(hint))
    analysis.raw.intents = intents or [Intent.CHITCHAT]
    added = [r for r in _stood_for([Intent(hint)], analysis) if r not in analysis.raw.routes]
    analysis.raw.routes = [*added, *analysis.raw.routes]
    return analysis


def _stood_for(intents, analysis: Analysis) -> list[AnswerRoute]:
    routes = [r for i in intents for r in INTENT_ROUTES.get(i, ())]
    if Intent.FAILURE_INVESTIGATION in intents and (analysis.test_plan_ids or analysis.test_run_ids):
        routes.append(AnswerRoute.MEASURED)  # the anomaly in the named test's run data
    return list(dict.fromkeys(routes))


def routes_of(analysis: Analysis) -> list[AnswerRoute]:
    """The routes the planner named; for a reply without them, the routes its intents stand for. Telemetry
    statistics always need the measured route."""
    intents = analysis.raw.intents
    routes = list(analysis.raw.routes) or _stood_for(intents, analysis)
    telemetry = {Intent.TELEMETRY_METRIC, Intent.RUN_COMPARISON} & set(intents)
    if telemetry and AnswerRoute.MEASURED not in routes:
        routes.append(AnswerRoute.MEASURED)
    return routes


def _document(plan: Plan, analysis: Analysis, question: str) -> None:
    plan.add("search_documents", _search(analysis, question), "the passages that state it")


def _library(plan: Plan, analysis: Analysis, question: str) -> None:
    # library files belong to no test plan or settled subject: those filters would hide them
    plan.add(
        "search_documents",
        _search(analysis, question, prefer_doc_kinds=LIBRARY_KINDS, test_plan_ids=[], doc_ids=[]),
        "the library: standards, datasheets and papers",
    )


def _table(plan: Plan, analysis: Analysis, question: str) -> None:
    plan.add("search_documents", _search(analysis, question, scope=Scope.TABLES_ONLY), "the values in tables")


def _measured(plan: Plan, analysis: Analysis, question: str) -> None:
    plan.needs_telemetry_args = True
    plan.add(
        "search_documents",
        _search(analysis, question, scope=Scope.TABLES_ONLY),
        "report tables to cross-check the measured values",
    )
    plan.add(
        "search_documents",
        _search(analysis, question, prefer_node_types=["run_summary"]),
        "the run summaries and report text about the runs",
    )


def _source(plan: Plan, analysis: Analysis, question: str) -> None:
    symbols = [e.surface for e in analysis.raw.entities if e.type == EntityType.TOOL_SOFTWARE]
    if symbols:
        plan.add(
            "inspect_code_and_diagrams",
            CodeDiagramArgs(mode="callers_callees", symbol=symbols[0]),
            "the named symbol and its callers",
        )
    # every piece of a source file: a requirements line or a logger setting is plain text, not a code symbol
    plan.add(
        "search_documents",
        _search(
            analysis,
            question,
            prefer_doc_kinds=[str(k) for k in SOURCE_KINDS],
            prefer_node_types=["code_symbol", "module_header", "config"],
        ),
        "code, requirements and configuration files",
    )


def _visual(plan: Plan, analysis: Analysis, question: str) -> None:
    plan.add(
        "inspect_visuals", _visuals(analysis, question, relook=question), "photos, plots and video frames"
    )
    # the readings of photos and figures and the report text around them are searchable text too
    plan.add(
        "search_documents",
        _search(analysis, question, prefer_node_types=["photo", "figure", "video_event"]),
        "what the photos, plots and reports say",
    )


def _meeting(plan: Plan, analysis: Analysis, question: str) -> None:
    plan.add(
        "search_documents",
        _search(
            analysis, question, prefer_doc_kinds=["video_transcript"], prefer_node_types=["transcript_window"]
        ),
        "what was said in the recordings",
    )


def _diagram(plan: Plan, analysis: Analysis, question: str) -> None:
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
    plan.add(
        "search_documents",
        _search(
            analysis,
            question,
            prefer_doc_kinds=["diagram"],
            prefer_node_types=["diagram_summary", "figure", "photo"],
        ),
        "the drawings",
    )


def _archive(plan: Plan, analysis: Analysis, question: str) -> None:
    plan.add(
        "search_documents",
        _search(analysis, question, prefer_doc_kinds=["cae_package", "cad_reference"]),
        "the archive's card",
    )


ROUTE_METHODS = {
    AnswerRoute.DOCUMENT: _document,
    AnswerRoute.LIBRARY: _library,
    AnswerRoute.TABLE: _table,
    AnswerRoute.MEASURED: _measured,
    AnswerRoute.SOURCE: _source,
    AnswerRoute.VISUAL: _visual,
    AnswerRoute.MEETING: _meeting,
    AnswerRoute.DIAGRAM: _diagram,
    AnswerRoute.ARCHIVE: _archive,
}


def build_plan(question: str, analysis: Analysis) -> Plan:
    """Each route the planner named searches its own way (`ROUTE_METHODS`); intents add only what changes
    how the answer is built: a calculation, a whole-document summary, a design synthesis, what exists."""
    plan = Plan()
    intents = set(analysis.raw.intents)
    routes = routes_of(analysis)
    if intents == {Intent.CHITCHAT} and not routes:
        return plan
    for route in routes:
        ROUTE_METHODS[route](plan, analysis, question)
    if Intent.DESIGN_SYNTHESIS in intents:
        plan.add(
            "search_documents",
            _search(analysis, question, source_origins=[SourceOrigin.INTERNAL]),
            "internal baselines",
        )
        plan.add(
            "search_documents",
            _search(analysis, question, source_origins=[SourceOrigin.EXTERNAL_KEPT], doc_ids=[]),
            "kept library: datasheets and papers",
        )
        plan.needs_physics_args = True
    if Intent.PHYSICS_CALC in intents:
        plan.needs_physics_args = True
    if Intent.DOCUMENT_SUMMARY in intents:
        plan.add(
            "search_documents", _search(analysis, question, scope=Scope.PARENT, k=3), "find the document"
        )
        plan.read_top_document = True
    if Intent.NAVIGATIONAL in intents:  # what exists comes from the catalog step's files
        plan.add("search_documents", _search(analysis, question), "where it is discussed")
    if analysis.raw.needs_visuals and AnswerRoute.VISUAL not in routes:
        plan.add("inspect_visuals", _visuals(analysis, question), "photos and plots")
    for sub in analysis.raw.sub_questions:
        if sub.tool in (None, "search_documents"):
            plan.add("search_documents", _search(analysis, sub.text), f"sub-question: {sub.text}")
    _external(plan, analysis, intents)
    if not plan.calls and not plan.needs_physics_args and not plan.needs_telemetry_args:
        plan.add("search_documents", _search(analysis, question), "general search")
    return plan


def _external(plan: Plan, analysis: Analysis, intents: set[Intent]) -> None:
    """File 07 §6: on explicit request, or for a design synthesis whose internal and library search found
    nothing; never with an internal-only scope or for a user outside `answer.external_allowed_groups`."""
    if analysis.raw.source_scope == SourceScope.INTERNAL_ONLY:
        return
    if not analysis.external_allowed:
        if analysis.raw.external_requested:
            plan.caveats.append(EXTERNAL_NOT_ALLOWED)
        return
    if analysis.raw.external_requested:
        plan.external = "yes"
    elif Intent.DESIGN_SYNTHESIS in intents:
        plan.external = "if_gap"


def read_document_call(doc_id) -> PlannedCall:
    return PlannedCall("get_document", GetDocumentArgs(doc_id=doc_id), "read the document found")
