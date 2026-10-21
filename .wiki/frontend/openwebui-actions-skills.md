# Open WebUI Actions, Filter and Skills publication

| Field | Value |
|-------|-------|
| Feature id | `frontend/openwebui-actions-skills` |
| Status | planned |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §1, §2.2, §3.1 |
| Last updated | 2026-10-21 |

## Purpose

Actions 'Show trace', 'Add to benchmark', 'Report issue'; Filter attaching user policy; publishing playbooks as Skills; the single gateway connection for plain Gemini chat.

## Location

Code:
- `services/openwebui/actions/`
- `services/openwebui/filter_policy.py`
- `services/openwebui/skills/`

Tests and fixtures:
- `tests/integration/openwebui/`

## Interfaces

Provides:
- Actions and Skills installed in Open WebUI

Consumes:
- traces API
- benchmark API

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/openwebui/actions/`
- `services/openwebui/filter_policy.py`
- `services/openwebui/skills/`
- `tests/integration/openwebui/`

## Rubric (what "done" means for this feature)

- [ ] 'Add to benchmark' creates a draft case prefilled from verified claims
- [ ] Only Gemini credentials exist in Open WebUI
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
