# L2 enrichment, entity normalization, numeric facts

| Field | Value |
|-------|-------|
| Feature id | `backend/enrichment` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/04_metadata_enrichment_chunking_embedding.md §1–§3, §8 |
| Last updated | 2026-10-22 |

## Purpose

One Gemini call per parent producing English summary, entities, numeric facts, claims and question proxies; grounding and pint validation; entities/aliases normalization without a human gate.

## Location

Code:
- `backend/llm_engine/enrichment/extract.py` (`ParentEnrichment`, `enrich_parent`, `ground`, `Drops`)
- `backend/llm_engine/enrichment/entities.py` (`canonical_key`, `AliasIndex`, `index_from_seed`, `index_from_db`, `normalize`)
- `backend/llm_engine/enrichment/numeric_facts.py` (`parse_number`, `validate_fact`, `fact_source`, `sanity_bounds`)
- `backend/llm_engine/prompts/enrichment/parent.v1.md`

Tests and fixtures:
- `backend/tests/unit/llm_engine/enrichment/`

## Interfaces

Provides:
- `enrich_parent(client, text, context=, language=, doc_id=, anchor=) -> EnrichedParent(enrichment, drops, prompt_version, model, warnings)`; one gateway call per parent, grounded
- `normalize(pairs, node_texts, index, doc_id=, languages=) -> EntityDecisions(new_entities, new_aliases, mentions)` for S1's commit; entity refs are an `entity_id` or `(type, canonical_key)` of a new entity
- `validate_fact(extract, node_ref=, node_text=, locale=, source=, ranges=) -> FactDecision | DroppedFact` for `numeric_facts`
- planned (with `index_document`): document aggregation (`documents.enrichment`, `entity_ids`, `search_text`), question proxies

Consumes:
- `platform/gemini-gateway-client` (adapter-neutral `generate_sync`)
- `backend/common/units.py` (S1): `parse_unit`, `fits_quantity`, `to_canonical`
- `backend/postgres/enums.py` (S1): `EntityType`, `Quantity`, `NumericFactSource`, `AliasCreatedBy`
- `config/aerospace_synonyms.yaml`, `config/sanity_ranges.yaml` (`quality/config-data`)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/enrichment/extract.py`
- `backend/llm_engine/enrichment/entities.py`
- `backend/llm_engine/enrichment/numeric_facts.py`
- `backend/llm_engine/prompts/enrichment/`
- `backend/tests/unit/llm_engine/enrichment/`

## Rubric (what "done" means for this feature)

- [x] Entity surfaces not found in the text are dropped and counted; a call above 10% drops carries a warning (`test_extract.py`); the <10% rate itself is measured on real parents once the gateway is live
- [x] Units parse and match the quantity dimension; mismatch dropped, unreadable unit kept with needs_unit (`test_numeric_facts.py`)
- [ ] A merge in the Entities page re-points mentions and rewrites search_text in one transaction (the Entities API is S1's `backend/api/entities.py`; needs `search_text` from `index_document`)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | Per-parent extraction with grounding, entity normalization (seed + DB index, fuzzy ≥ 92, English canonical for non-English), numeric facts (locale, units, sanity, provenance); 37 tests |

## Related

- `.wiki/index.md`
