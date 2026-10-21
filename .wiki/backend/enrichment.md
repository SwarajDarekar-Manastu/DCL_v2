# L2 enrichment, entity normalization, numeric facts

| Field | Value |
|-------|-------|
| Feature id | `backend/enrichment` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/04_metadata_enrichment_chunking_embedding.md §1–§3, §8 |
| Last updated | 2026-10-21 |

## Purpose

One Gemini call per parent producing English summary, entities, numeric facts, claims and question proxies; grounding and pint validation; entities/aliases normalization without a human gate.

## Location

Code:
- `backend/llm_engine/enrichment/extract.py`
- `backend/llm_engine/enrichment/entities.py`
- `backend/llm_engine/enrichment/numeric_facts.py`
- `backend/llm_engine/prompts/enrichment/`

Tests and fixtures:
- `backend/tests/unit/llm_engine/enrichment/`

## Interfaces

Provides:
- entity_mentions, numeric_facts, documents.enrichment, search_text

Consumes:
- gateway client
- aerospace_synonyms.yaml (quality/config-data)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/enrichment/extract.py`
- `backend/llm_engine/enrichment/entities.py`
- `backend/llm_engine/enrichment/numeric_facts.py`
- `backend/llm_engine/prompts/enrichment/`
- `backend/tests/unit/llm_engine/enrichment/`

## Rubric (what "done" means for this feature)

- [ ] Entity surfaces not found in the text are dropped (drop rate <10%)
- [ ] Units parse and match the quantity dimension
- [ ] A merge in the Entities page re-points mentions and rewrites search_text in one transaction
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
