# Route A1: PDF, DOCX, PPTX, PPT

| Field | Value |
|-------|-------|
| Feature id | `backend/route-a1-office` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §4 |
| Last updated | 2026-10-21 |

## Purpose

Pre-flight, page triage with language/script, Docling by script group, tables QA with VLM A/B, equations, figure classification, handwriting regions, DOCX/PPTX specifics, section tree, PDF twin page map, library-document specifics.

## Location

Code:
- `backend/routes/a1_office/`

Tests and fixtures:
- `backend/tests/unit/routes/a1_office/`
- `backend/tests/fixtures/route_a1/`

## Interfaces

Provides:
- page/table/figure/handwriting nodes
- page renders and crops as assets

Consumes:
- vision-service
- embedding/enrichment via index_document

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/a1_office/`
- `backend/tests/unit/routes/a1_office/`
- `backend/tests/fixtures/route_a1/`

## Rubric (what "done" means for this feature)

- [ ] Page types correct ≥95% on the SME set
- [ ] Handwritten values ≥90% correct with calibrated confidence
- [ ] Non-English scanned pages OCR'd with the engine chosen by script
- [ ] Citations open the right page and bbox
- [ ] Reference lists of papers are mentions, not body nodes
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
