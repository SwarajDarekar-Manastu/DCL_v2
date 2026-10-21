# Route B: Python scripts and tooling docs

| Field | Value |
|-------|-------|
| Feature id | `backend/route-b-code` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §6 |
| Last updated | 2026-10-21 |

## Purpose

Tree-sitter AST nodes per function/class/method with context headers, module header node, constants with units, secrets scan.

## Location

Code:
- `services/routes/b_code/`

Tests and fixtures:
- `tests/unit/routes/b_code/`
- `tests/fixtures/route_b/`

## Interfaces

Provides:
- code_symbol nodes with qualname/calls/imports

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/routes/b_code/`
- `tests/unit/routes/b_code/`
- `tests/fixtures/route_b/`

## Rubric (what "done" means for this feature)

- [ ] Every function/class in the team scripts is retrievable by name
- [ ] Methods carry their class header
- [ ] Hard-coded credentials raise SENSITIVE_CONTENT HARD
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
