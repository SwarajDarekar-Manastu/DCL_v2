# Route A2: JSON report sections and LaTeX sources

| Field | Value |
|-------|-------|
| Feature id | `backend/route-a2-source` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §5 |
| Last updated | 2026-10-21 |

## Purpose

Parse ground-truth report sources: JSON section schemas, LaTeX master/include resolution, macro expansion, Pandoc to Markdown with math and tables intact, page map to the PDF twin.

## Location

Code:
- `services/routes/a2_source/`

Tests and fixtures:
- `tests/unit/routes/a2_source/`
- `tests/fixtures/route_a2/`

## Interfaces

Provides:
- section nodes with breadcrumbs
- source_map and page_map in CIR

Consumes:
- report_json_schemas.yaml (quality/config-data)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/routes/a2_source/`
- `tests/unit/routes/a2_source/`
- `tests/fixtures/route_a2/`

## Rubric (what "done" means for this feature)

- [ ] Multi-file LaTeX project assembles into one document
- [ ] Unknown JSON shape indexes generically with SCHEMA_UNKNOWN SOFT
- [ ] \ref and \cite resolve to readable text in chunks
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
