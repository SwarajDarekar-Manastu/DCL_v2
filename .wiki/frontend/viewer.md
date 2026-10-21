# Shared document viewer with anchor resolution and translate toggle

| Field | Value |
|-------|-------|
| Feature id | `frontend/viewer` |
| Status | planned |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §6; 04 §4.4 |
| Last updated | 2026-10-21 |

## Purpose

Renders page images with bbox overlays, tables, code, photos, plots, diagram renders and video with seeking; resolves stable anchors with page fallback; translate toggle.

## Location

Code:
- `frontend/console/src/routes/docs/[id]/viewer/`
- `backend/api/viewer.py`
- `backend/api/assets.py`

Tests and fixtures:
- `frontend/console/tests/viewer/`

## Interfaces

Provides:
- `/docs/{id}/viewer?anchor=…`
- presigned asset URLs

Consumes:
- anchors resolver (backend/chunker-and-anchors)
- assets

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/console/src/routes/docs/[id]/viewer/`
- `backend/api/viewer.py`
- `backend/api/assets.py`
- `frontend/console/tests/viewer/`

## Rubric (what "done" means for this feature)

- [ ] Citation links open the right page after a forced re-index
- [ ] Fallback to page is shown explicitly when content changed
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
