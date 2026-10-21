# Environment contract loader and .env.example

| Field | Value |
|-------|-------|
| Feature id | `platform/env-contract` |
| Status | planned |
| Owner session | S4 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §7.1 |
| Last updated | 2026-10-21 |

## Purpose

Typed settings from .env per file 01 §7.1: refuses placeholders, refuses GOOGLE_API_KEY, validates DCL_PERMISSION_OPTION; .env.example with names only.

## Location

Code:
- `services/common/config/settings.py`
- `.env.example`

Tests and fixtures:
- `tests/unit/config/test_settings.py`

## Interfaces

Provides:
- Settings object used by every service

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/common/config/settings.py`
- `.env.example`
- `tests/unit/config/test_settings.py`

## Rubric (what "done" means for this feature)

- [ ] Every refusal rule has a test
- [ ] No secret value ever appears in logs or images
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
