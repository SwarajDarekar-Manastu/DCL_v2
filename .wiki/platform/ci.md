# CI pipeline and gates

| Field | Value |
|-------|-------|
| Feature id | `platform/ci` |
| Status | planned |
| Owner session | S4 |
| Spec | docs/architecture/10_development_plan.md §7; 05 §3 |
| Last updated | 2026-10-21 |

## Purpose

Lint, unit tests, alembic upgrade/check on the pinned ParadeDB image, FK-index query, image secret scan, benchmark gate.

## Location

Code:
- `.github/workflows/`
- `backend/devops/ci/`

Tests and fixtures:
- (none yet)

## Interfaces

Provides:
- green/red on every PR

Consumes:
- schema (S1)
- benchmark runner (S2/S5)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `.github/workflows/`
- `backend/devops/ci/`

## Rubric (what "done" means for this feature)

- [ ] A merge that drops telemetry exactness is blocked
- [ ] Secret scan passes on every image
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
