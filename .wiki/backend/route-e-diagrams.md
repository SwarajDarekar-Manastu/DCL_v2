# Route E: draw.io diagrams and XSD

| Field | Value |
|-------|-------|
| Feature id | `backend/route-e-diagrams` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §9 |
| Last updated | 2026-10-21 |

## Purpose

Parse mxGraphModel into a component/edge graph stored in documents.catalog, render PNG, emit diagram summary and per-component nodes; XSD element tree.

## Location

Code:
- `backend/routes/e_diagrams/`

Tests and fixtures:
- `backend/tests/unit/routes/e_diagrams/`
- `backend/tests/fixtures/route_e/`

## Interfaces

Provides:
- documents.catalog graph JSON
- diagram_component nodes
- diagram render asset

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/e_diagrams/`
- `backend/tests/unit/routes/e_diagrams/`
- `backend/tests/fixtures/route_e/`

## Rubric (what "done" means for this feature)

- [ ] Upstream/downstream of a tag answers correctly for the Rev C diagram
- [ ] Compressed draw.io pages decode
- [ ] Unlabeled-edge ratio above threshold raises CONFLICT SOFT
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
