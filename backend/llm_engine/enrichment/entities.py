"""Entity normalization without a human gate (file 04 §3.3).

For each extracted `(type, surface)`: canonicalize; exact alias lookup; exact lookup of the model's English
hint; fuzzy match within the type (RapidFuzz token-set ratio ≥ 92) against canonical names and aliases; else
a new entity. A brand-new entity found in non-English text takes the English hint as its canonical name.
Seeded synonyms (`config/aerospace_synonyms.yaml`) and existing `entity_aliases` rows fill the index.

Nothing here writes to the database: `normalize` returns the new entities, new aliases and mentions that
S1's commit path writes in the document's transaction. New entities found earlier in the same document are
reused by later mentions.
"""

import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.llm_engine.enrichment.extract import EntityExtract
from backend.postgres.enums import AliasCreatedBy, EntityType, MentionSource
from backend.postgres.models import Entity, EntityAlias

SYNONYMS_FILE = Path(__file__).resolve().parents[3] / "config" / "aerospace_synonyms.yaml"
FUZZY_MIN_SCORE = 92.0
DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
TRAILING_PUNCTUATION = ".,;:!?)]}\"'»”’"
IDENTIFIER = re.compile(r"^([a-z]{1,5})[\s_-]?(\d+[a-z]?)$")


def canonical_key(surface: str) -> str:
    """NFKC, lowercase, whitespace collapsed, dashes unified, trailing punctuation stripped, and identifier
    patterns normalized (`C 103`, `C103`, `c-103` → `c-103`; `PT 101` → `pt-101`)."""
    key = unicodedata.normalize("NFKC", surface).translate(DASHES).lower()
    key = " ".join(key.split()).rstrip(TRAILING_PUNCTUATION).strip()
    match = IDENTIFIER.match(key)
    return f"{match.group(1)}-{match.group(2)}" if match else key


EntityRef = uuid.UUID | tuple[str, str]
"""An existing `entity_id`, or `(type, canonical_key)` of an entity this document creates."""


@dataclass
class AliasIndex:
    by_key: dict[tuple[str, str], EntityRef] = field(default_factory=dict)
    names: dict[str, list[tuple[str, EntityRef]]] = field(default_factory=dict)

    def add(self, entity_type: str, surface: str, ref: EntityRef) -> None:
        key = canonical_key(surface)
        self.by_key.setdefault((entity_type, key), ref)
        self.names.setdefault(entity_type, []).append((key, ref))

    def exact(self, entity_type: str, surface: str | None) -> EntityRef | None:
        return self.by_key.get((entity_type, canonical_key(surface))) if surface else None

    def fuzzy(self, entity_type: str, surface: str) -> tuple[EntityRef, float] | None:
        key = canonical_key(surface)
        best: tuple[EntityRef, float] | None = None
        for name, ref in self.names.get(entity_type, []):
            score = fuzz.token_set_ratio(key, name)
            if score >= FUZZY_MIN_SCORE and (best is None or score > best[1]):
                best = (ref, score)
        return best


@dataclass(frozen=True)
class SeedEntity:
    type: EntityType
    canonical: str
    aliases: tuple[str, ...]


def load_seed(path: Path = SYNONYMS_FILE) -> list[SeedEntity]:
    """The seeded synonyms (S5's YAML); `quantity_terms` are not entities and are not read here."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        SeedEntity(EntityType(e["type"]), e["canonical"], tuple(a["surface"] for a in e.get("aliases", [])))
        for e in data.get("entities", [])
    ]


@dataclass(frozen=True)
class SeedRows:
    """Plain rows for S1's `seed-entities` command (created_by = seed; idempotent on the unique keys)."""

    entities: list[dict]
    aliases: list[dict]


def seed_rows(seed: Iterable[SeedEntity] | None = None) -> SeedRows:
    """`entities` rows keyed by (type, canonical_key) and `entity_aliases` rows that name their entity by
    (entity_type, entity_canonical_key); duplicate alias keys within a type keep the first entity."""
    entities: list[dict] = []
    aliases: dict[tuple[str, str], dict] = {}
    for entity in load_seed() if seed is None else seed:
        key = canonical_key(entity.canonical)
        entities.append(
            {
                "type": str(entity.type),
                "canonical_name": entity.canonical,
                "canonical_key": key,
                "created_by": "seed",
            }
        )
        for surface in (entity.canonical, *entity.aliases):
            aliases.setdefault(
                (str(entity.type), canonical_key(surface)),
                {
                    "type": str(entity.type),
                    "alias_key": canonical_key(surface),
                    "alias": surface,
                    "entity_type": str(entity.type),
                    "entity_canonical_key": key,
                    "created_by": "seed",
                },
            )
    return SeedRows(entities, list(aliases.values()))


def index_from_seed(seed: Iterable[SeedEntity]) -> AliasIndex:
    """An index over the seed alone (tests, and the install-time seeding plan)."""
    index = AliasIndex()
    for entity in seed:
        ref = (str(entity.type), canonical_key(entity.canonical))
        index.add(entity.type, entity.canonical, ref)
        for alias in entity.aliases:
            index.add(entity.type, alias, ref)
    return index


def index_from_db(session: Session) -> AliasIndex:
    """The index over `entities` and `entity_aliases` (seeded at install, grown by every commit)."""
    index = AliasIndex()
    for entity_id, entity_type, name in session.execute(
        select(Entity.entity_id, Entity.type, Entity.canonical_name)
    ):
        index.add(entity_type, name, entity_id)
    for entity_id, entity_type, alias in session.execute(
        select(EntityAlias.entity_id, EntityAlias.type, EntityAlias.alias)
    ):
        index.add(entity_type, alias, entity_id)
    return index


@dataclass(frozen=True)
class NewEntity:
    type: EntityType
    canonical_name: str
    canonical_key: str
    first_seen_doc_id: uuid.UUID | None

    @property
    def ref(self) -> tuple[str, str]:
        return (str(self.type), self.canonical_key)


@dataclass(frozen=True)
class NewAlias:
    type: EntityType
    alias_key: str
    alias: str
    entity: EntityRef
    created_by: AliasCreatedBy
    fuzzy_score: float | None = None


@dataclass(frozen=True)
class MentionDecision:
    node_ref: str
    entity: EntityRef
    type: EntityType
    surface: str
    span_start: int | None
    span_end: int | None
    source: MentionSource = MentionSource.LLM
    confidence: float | None = None


@dataclass
class EntityDecisions:
    """What the commit writes: entities first, then aliases, then mentions (refs resolve to ids in order)."""

    new_entities: list[NewEntity] = field(default_factory=list)
    new_aliases: list[NewAlias] = field(default_factory=list)
    mentions: list[MentionDecision] = field(default_factory=list)


def _span(text: str, surface: str) -> tuple[int | None, int | None]:
    start = (
        unicodedata.normalize("NFKC", text).casefold().find(unicodedata.normalize("NFKC", surface).casefold())
    )
    return (start, start + len(surface)) if start >= 0 else (None, None)


def _canonical_name(extract: EntityExtract, language: str | None) -> str:
    if language and not language.lower().startswith("en") and extract.normalized_hint_en:
        return extract.normalized_hint_en.strip()
    return extract.surface.strip()


def normalize(
    extracted: Iterable[tuple[str, EntityExtract]],
    node_texts: dict[str, str],
    index: AliasIndex,
    *,
    doc_id: uuid.UUID | None,
    languages: dict[str, str | None] | None = None,
) -> EntityDecisions:
    """Resolve `(node_ref, extracted entity)` pairs; the index grows with every new entity and alias."""
    languages = languages or {}
    decisions = EntityDecisions()
    for node_ref, extract in extracted:
        entity_type, surface = extract.type, extract.surface
        key = canonical_key(surface)
        ref = index.exact(entity_type, surface)
        known_surface = ref is not None
        created_by, score = AliasCreatedBy.SYSTEM_EXACT, None
        if ref is None:
            ref = index.exact(entity_type, extract.normalized_hint_en)
        if ref is None:
            fuzzy = index.fuzzy(entity_type, surface)
            if fuzzy is not None:
                ref, score = fuzzy
                created_by = AliasCreatedBy.SYSTEM_FUZZY
        if ref is None:
            name = _canonical_name(extract, languages.get(node_ref))
            new = NewEntity(entity_type, name, canonical_key(name), doc_id)
            decisions.new_entities.append(new)
            ref = new.ref
            index.add(entity_type, name, ref)
        if not known_surface:
            decisions.new_aliases.append(NewAlias(entity_type, key, surface.strip(), ref, created_by, score))
            index.add(entity_type, surface, ref)
        start, end = _span(node_texts.get(node_ref, ""), surface)
        decisions.mentions.append(MentionDecision(node_ref, ref, entity_type, surface, start, end))
    return decisions
