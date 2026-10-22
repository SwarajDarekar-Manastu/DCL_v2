"""Layer 2 enrichment (file 04 §3): one Gemini call per parent, English outputs, grounded in the text.

`enrich_parent` sends the parent text in its original language with the document's L1 context and returns
the extraction after `ground`, which drops anything the text does not contain (file 04 §8): an entity whose
surface is absent, a number whose value or unit string is absent, a claim whose span is absent, a test id or
standard the identifier regex does not find. Drops are counted per call; a drop rate above 10% for a prompt
version is a prompt bug. Numbers are validated further by `numeric_facts`, entities normalized by `entities`.
"""

import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from backend.config import ThinkingLevel
from backend.indexing.identifiers import extract_identifiers
from backend.llm_engine.gemini_types import CallContext, Message
from backend.llm_engine.model_ids import model_id
from backend.llm_engine.prompts import load_prompt
from backend.postgres.enums import EntityType, Quantity

PROMPT_VERSION = "parent.v1"
PURPOSE = "enrichment.parent"
MAX_DROP_RATE = 0.10


class StatusMarker(StrEnum):
    FAILED = "failed"
    ABORTED = "aborted"
    NOMINAL = "nominal"
    SUPERSEDED = "superseded"
    DRAFT = "draft"
    PRELIMINARY = "preliminary"
    APPROVED = "approved"


class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EntityExtract(_Item):
    type: EntityType
    surface: str
    normalized_hint_en: str | None = None


class NumericExtract(_Item):
    quantity: Quantity
    quantity_label: str
    value: str = Field(description="the number exactly as written")
    unit: str | None = Field(description="the unit exactly as written, null if none")
    context: str
    span: str


class ClaimExtract(_Item):
    text: str
    span: str


class ParentEnrichment(_Item):
    """The structured output of the per-parent call (file 04 §3.2)."""

    summary: str
    section_kind: str
    publication_type: str | None = None
    entities: list[EntityExtract] = Field(default_factory=list)
    numeric_facts: list[NumericExtract] = Field(default_factory=list)
    test_ids_mentioned: list[str] = Field(default_factory=list)
    standards_mentioned: list[str] = Field(default_factory=list)
    status_markers: list[StatusMarker] = Field(default_factory=list)
    claims: Annotated[list[ClaimExtract], Field(max_length=5)] = Field(default_factory=list)
    questions_answered: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Drops:
    entities: int = 0
    numeric_facts: int = 0
    claims: int = 0
    identifiers: int = 0
    kept: int = 0

    @property
    def rate(self) -> float:
        dropped = self.entities + self.numeric_facts + self.claims + self.identifiers
        total = dropped + self.kept
        return dropped / total if total else 0.0


@dataclass(frozen=True)
class EnrichedParent:
    enrichment: ParentEnrichment
    drops: Drops
    prompt_version: str = PROMPT_VERSION
    model: str = field(default_factory=model_id)
    warnings: list[str] = field(default_factory=list)


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _in_text(fragment: str | None, folded_text: str) -> bool:
    return bool(fragment) and _fold(fragment) in folded_text


def ground(raw: ParentEnrichment, text: str) -> tuple[ParentEnrichment, Drops]:
    """Keep only what the section text contains (case- and spacing-insensitive, NFKC)."""
    folded = _fold(text)
    entities = [e for e in raw.entities if _in_text(e.surface, folded)]
    facts = [
        f
        for f in raw.numeric_facts
        if _in_text(f.value, folded)
        and (f.unit is None or _in_text(f.unit, folded))
        and _in_text(f.span, folded)
    ]
    claims = [c for c in raw.claims if _in_text(c.span, folded)]
    codes = set(extract_identifiers(text))
    test_ids = [t for t in raw.test_ids_mentioned if set(extract_identifiers(t)) & codes]
    standards = [s for s in raw.standards_mentioned if set(extract_identifiers(s)) & codes]
    drops = Drops(
        entities=len(raw.entities) - len(entities),
        numeric_facts=len(raw.numeric_facts) - len(facts),
        claims=len(raw.claims) - len(claims),
        identifiers=len(raw.test_ids_mentioned)
        + len(raw.standards_mentioned)
        - len(test_ids)
        - len(standards),
        kept=len(entities) + len(facts) + len(claims) + len(test_ids) + len(standards),
    )
    grounded = raw.model_copy(
        update={
            "entities": entities,
            "numeric_facts": facts,
            "claims": claims,
            "test_ids_mentioned": test_ids,
            "standards_mentioned": standards,
        }
    )
    return grounded, drops


def document_context(
    title: str, doc_kind: str, source_origin: str | None, extra: list[str] | None = None
) -> str:
    """The one-line L1 context the prompt receives (file 04 §3.2)."""
    parts = [title, doc_kind, source_origin or "internal", *(extra or [])]
    return " · ".join(p for p in parts if p)


def enrich_parent(
    client,
    parent_text: str,
    *,
    context: str,
    language: str | None,
    doc_id: str | None = None,
    anchor: str | None = None,
) -> EnrichedParent:
    """One call per parent through the client's adapter-neutral `generate_sync` (thinking low, T=0)."""
    prompt = load_prompt("enrichment", PROMPT_VERSION)
    user = prompt.render_user(document_context=context, language=language or "und", parent_text=parent_text)
    result = client.generate_sync(
        model=model_id(),
        messages=[Message.system(prompt.system), Message.user(user)],
        context=CallContext(
            purpose=PURPOSE, prompt_version=PROMPT_VERSION, doc_id=doc_id, node_anchor=anchor
        ),
        schema=ParentEnrichment,
        thinking=ThinkingLevel.LOW,
        temperature=0.0,
    )
    grounded, drops = ground(result.parsed, parent_text)
    warnings = [f"drop rate {drops.rate:.0%} above {MAX_DROP_RATE:.0%}"] if drops.rate > MAX_DROP_RATE else []
    return EnrichedParent(grounded, drops, model=result.model or model_id(), warnings=warnings)
