# VisionService on Gemini (triage, handwriting, tables, plots, photos, video)

| Field | Value |
|-------|-------|
| Feature id | `backend/vision-service` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §3; 01 §7 |
| Last updated | 2026-10-21 |

## Purpose

One component for every vision call through the gateway client: versioned prompts, structured-output schemas, MinIO cache, llm_calls logging, no-guessing rules.

## Location

Code:
- `backend/llm_engine/vision/service.py`
- `backend/llm_engine/vision/schemas.py`
- `backend/llm_engine/prompts/vision/`

Tests and fixtures:
- `backend/tests/unit/llm_engine/vision/`
- `backend/tests/fixtures/vision/`

## Interfaces

Provides:
- triage_page, transcribe_handwriting, transcribe_page, read_table_image, digitize_plot, read_schematic, inspect_hardware_photo, describe_slide, video_timeline

Consumes:
- gateway client (platform/gemini-gateway-client)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/llm_engine/vision/service.py`
- `backend/llm_engine/vision/schemas.py`
- `backend/llm_engine/prompts/vision/`
- `backend/tests/unit/llm_engine/vision/`
- `backend/tests/fixtures/vision/`

## Rubric (what "done" means for this feature)

- [ ] Identical crops hit the cache and cost once
- [ ] Every call appears in llm_calls with doc reference and tokens
- [ ] Handwriting output carries confidence and alternatives, never a guessed digit
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
