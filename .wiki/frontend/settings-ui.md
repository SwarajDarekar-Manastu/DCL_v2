# Settings UI (sources, scopes, gate, routes, models, translation, flags, prompts)

| Field | Value |
|-------|-------|
| Feature id | `frontend/settings-ui` |
| Status | in-progress (scaffolding done; editing waits for S1's settings API) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §3.2 |
| Last updated | 2026-10-21 |

## Purpose

Configuration screens over pipeline_config with validation, impact counts, cost estimates for scope widening, history and rollback.

## Location

Code:
- `frontend/console/src/routes/settings/` (`+layout.svelte` admin gate and menu, `+page.ts` redirect to the first section, `[section]/` page and 404 for unknown sections)
- `frontend/console/src/lib/components/settings/` (`sections.ts` registry: id, title, `pipeline_config` keys, apply semantics per section of 08 §3.2; `SectionMenu.svelte`)
- `backend/api/settings.py` (S1 owns the router; the Console calls it only through `api_endpoint.ts`)

Tests and fixtures:
- `frontend/console/tests/settings/`

## Interfaces

Provides:
- /settings/* API

Consumes:
- pipeline_config (backend/schema-and-migrations)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/console/src/routes/settings/`
- `frontend/console/src/lib/components/settings/`
- `frontend/console/src/lib/api_endpoint.ts` (settings section, when S1 publishes the API)
- `frontend/console/tests/settings/`

## Rubric (what "done" means for this feature)

- [ ] Widening the processing scope shows counts and an estimated Gemini cost before applying
- [ ] Every change is audited and reversible
- [x] Every section of 08 §3.2 has a route in the manual's order; non-admins see the role notice
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S3 | Scaffolding: admin-gated layout, section registry and routes, tests |

## Related

- `.wiki/index.md`
- `backend/schema-and-migrations` (S1; provides the /settings API over pipeline_config)
