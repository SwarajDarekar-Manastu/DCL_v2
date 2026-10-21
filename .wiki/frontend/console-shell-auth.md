# Console shell, Entra ID login, roles, websocket

| Field | Value |
|-------|-------|
| Feature id | `frontend/console-shell-auth` |
| Status | planned |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §2.3, §7 |
| Last updated | 2026-10-21 |

## Purpose

SvelteKit app shell with OIDC login, role mapping, navigation, websocket channel for live updates.

## Location

Code:
- `frontend/console/src/routes/+layout.svelte`
- `frontend/console/src/lib/auth/`
- `backend/api/auth.py`
- `backend/api/ws.py`

Tests and fixtures:
- `frontend/console/tests/`
- `backend/tests/unit/api/`

## Interfaces

Provides:
- authenticated SPA
- /ws channel

Consumes:
- Entra app registration (platform)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/console/src/routes/+layout.svelte`
- `frontend/console/src/lib/auth/`
- `backend/api/auth.py`
- `backend/api/ws.py`
- `frontend/console/tests/`
- `backend/tests/unit/api/`

## Rubric (what "done" means for this feature)

- [ ] Login works for viewer/reviewer/admin groups
- [ ] Unauthorized routes are blocked server-side
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
