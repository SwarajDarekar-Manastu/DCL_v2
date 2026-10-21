# Fixture corpus and expected outcomes

| Field | Value |
|-------|-------|
| Feature id | `quality/fixtures` |
| Status | planned |
| Owner session | S5 |
| Spec | docs/architecture/10_development_plan.md §7 |
| Last updated | 2026-10-21 |

## Purpose

One real sample per format from the allowlisted folders plus synthetic edge cases, each with an expected-outcome file (route, flags, key numbers).

## Location

Code:
- `tests/fixtures/`

Tests and fixtures:
- (none yet)

## Interfaces

Provides:
- fixtures used by every route test

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `tests/fixtures/`

## Rubric (what "done" means for this feature)

- [ ] Every fixture has an expected-outcome file
- [ ] Edge-case list of file 10 §7 fully covered
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
