"""Step 1 of the workflow, query analysis (file 07 §3): one structured call, then deterministic resolution.

The model reads the question with the conversation summary and state and returns `QueryAnalysis`. Code then
resolves what must not depend on the model: entities through the alias index (`C103` → `C-103`), test ids
through the same patterns the dispatcher applies to folders (`TP7` → `TP07`, `Run 4` → `T04`, `Injector 14` →
`INJ14`), numeric bounds through S1's unit registry, and `external_allowed` from the user's groups and the
policy in `pipeline_config` (the model only says whether the user asked).
"""

import json
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from backend.common.units import UnitError, parse_unit
from backend.config import ThinkingLevel
from backend.dispatcher.folder_context import HARDWARE_PATTERNS, PLAN_PATTERNS, RUN_PATTERNS
from backend.llm_engine.enrichment.entities import AliasIndex
from backend.llm_engine.gemini_types import CallContext, Message
from backend.llm_engine.prompts import load_prompt
from backend.postgres.enums import EntityType

MODEL = "gemini-3.8-flash"
PROMPT_VERSION = "query_analysis.v1"
PURPOSE = "engine.query_analysis"


class Intent(StrEnum):
    TELEMETRY_METRIC = "telemetry_metric"
    RUN_COMPARISON = "run_comparison"
    FACT_LOOKUP = "fact_lookup"
    PROCEDURE_LOOKUP = "procedure_lookup"
    FAILURE_INVESTIGATION = "failure_investigation"
    STANDARDS_COMPLIANCE = "standards_compliance"
    CODE_WALKTHROUGH = "code_walkthrough"
    DIAGRAM_TRAVERSAL = "diagram_traversal"
    DESIGN_SYNTHESIS = "design_synthesis"
    DOCUMENT_SUMMARY = "document_summary"
    NAVIGATIONAL = "navigational"
    PHYSICS_CALC = "physics_calc"
    VISUAL_LOOKUP = "visual_lookup"
    CHITCHAT = "chitchat_or_out_of_scope"


class SourceScope(StrEnum):
    INTERNAL_ONLY = "internal_only"
    INTERNAL_AND_LIBRARY = "internal_and_library"
    INCLUDE_WEB = "include_web"


ToolName = Literal[
    "search_documents",
    "query_telemetry",
    "inspect_visuals",
    "inspect_code_and_diagrams",
    "physics_calculator",
    "get_document",
    "catalog_lookup",
    "external_search",
]


class EntityMentionQ(BaseModel):
    type: EntityType
    surface: str


class Filters(BaseModel):
    doc_kinds: list[str] = []
    date_from: str | None = None
    date_to: str | None = None
    standards: list[str] = []
    include_superseded: bool = False
    node_types: list[str] = []


class NumericConstraint(BaseModel):
    quantity: str
    op: Literal[">", "<", ">=", "<=", "=", "between"]
    value: str
    unit: str | None = None


class SubQuestion(BaseModel):
    text: str
    tool: ToolName | None = None


class Clarification(BaseModel):
    needed: bool = False
    question: str | None = None
    options: list[str] = []


class QueryAnalysis(BaseModel):
    intents: list[Intent] = Field(min_length=1)
    entities: list[EntityMentionQ] = []
    test_plan_ids: list[str] = []
    test_run_ids: list[str] = []
    hardware_items: list[str] = []
    filters: Filters = Filters()
    numeric_constraints: list[NumericConstraint] = []
    needs_visuals: bool = False
    external_requested: bool = False
    answer_format: Literal[
        "number", "short_fact", "table", "narrative", "trade_matrix", "code_explanation", "timeline"
    ] = "short_fact"
    language: str = "en"
    source_scope: SourceScope = SourceScope.INTERNAL_AND_LIBRARY
    sub_questions: list[SubQuestion] = []
    clarification: Clarification = Clarification()


@dataclass
class Analysis:
    """The model's reading plus the deterministic resolution the tools use."""

    raw: QueryAnalysis
    entity_ids: list[uuid.UUID]
    unresolved_entities: list[str]
    test_plan_ids: list[str]
    test_run_ids: list[str]
    hardware_items: list[str]
    constraints: list[dict]
    external_allowed: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def chitchat(self) -> bool:
        return self.raw.intents == [Intent.CHITCHAT]


def normalize_ids(values: list[str], patterns, fmt) -> list[str]:
    out = []
    for value in values:
        for pattern in patterns:
            match = pattern.search(value)
            if match:
                out.append(fmt(match.group(1)))
                break
        else:
            out.append(value.strip().upper())
    return list(dict.fromkeys(out))


def resolve(
    raw: QueryAnalysis, index: AliasIndex, *, user_groups: list[str], external_allowed_groups: list[str]
) -> Analysis:
    entity_ids, unresolved = [], []
    for mention in raw.entities:
        ref = (
            index.exact(mention.type, mention.surface)
            or (index.fuzzy(mention.type, mention.surface) or (None,))[0]
        )
        if isinstance(ref, uuid.UUID):
            entity_ids.append(ref)
        else:
            unresolved.append(mention.surface)
    constraints, warnings = [], []
    for c in raw.numeric_constraints:
        try:
            parsed = parse_unit(c.unit) if c.unit else None
            constraints.append(
                {**c.model_dump(), "unit_ok": True, "dimension": parsed.dimension if parsed else None}
            )
        except UnitError:
            constraints.append({**c.model_dump(), "unit_ok": False})
            warnings.append(f"unit {c.unit!r} of constraint {c.quantity} not recognized")
    group_ok = bool(set(user_groups) & set(external_allowed_groups))
    wants = raw.external_requested or Intent.DESIGN_SYNTHESIS in raw.intents
    return Analysis(
        raw=raw,
        entity_ids=list(dict.fromkeys(entity_ids)),
        unresolved_entities=unresolved,
        test_plan_ids=normalize_ids(raw.test_plan_ids, PLAN_PATTERNS, lambda n: f"TP{int(n):02d}"),
        test_run_ids=normalize_ids(raw.test_run_ids, RUN_PATTERNS, lambda n: f"T{int(n):02d}"),
        hardware_items=normalize_ids(raw.hardware_items, HARDWARE_PATTERNS, lambda n: f"INJ{int(n):02d}"),
        constraints=constraints,
        external_allowed=group_ok and wants,
        warnings=warnings,
    )


async def analyze(
    client,
    question: str,
    *,
    history: str,
    state: dict,
    index: AliasIndex,
    user_groups: list[str],
    external_allowed_groups: list[str],
    trace_id: str | None = None,
) -> Analysis:
    prompt = load_prompt("engine", PROMPT_VERSION)
    user = prompt.render_user(
        history=history or "none", state=json.dumps(state, default=str), question=question
    )
    result = await client.generate(
        model=MODEL,
        messages=[Message.system(prompt.system), Message.user(user)],
        context=CallContext(purpose=PURPOSE, prompt_version=PROMPT_VERSION, trace_id=trace_id),
        schema=QueryAnalysis,
        thinking=ThinkingLevel.LOW,
    )
    return resolve(
        result.parsed, index, user_groups=user_groups, external_allowed_groups=external_allowed_groups
    )
