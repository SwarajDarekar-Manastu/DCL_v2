# Settings UI (sources, scopes, gate, routes, models, translation, flags, prompts)

| Field | Value |
|-------|-------|
| Feature id | `frontend/settings-ui` |
| Status | planned |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §3.2 |
| Last updated | 2026-10-21 |

## Purpose

Configuration screens over pipeline_config with validation, impact counts, cost estimates for scope widening, history and rollback.

## Location

Code:
- `console_ui/src/routes/settings/`
- `services/console_api/settings.py`

Tests and fixtures:
- `console_ui/tests/settings/`

## Interfaces

Provides:
- /settings/* API

Consumes:
- pipeline_config (backend/schema-and-migrations)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `console_ui/src/routes/settings/`
- `services/console_api/settings.py`
- `console_ui/tests/settings/`

## Rubric (what "done" means for this feature)

- [ ] Widening the processing scope shows counts and an estimated Gemini cost before applying
- [ ] Every change is audited and reversible
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
