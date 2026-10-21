# Review UI (queue, case view, resolution consoles, rules, audit)

| Field | Value |
|-------|-------|
| Feature id | `frontend/review-ui` |
| Status | planned |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §4; 06 §6 |
| Last updated | 2026-10-21 |

## Purpose

Impact-sorted queue, polymorphic evidence and resolution panes per flag type, dry-run preview, rules page with simulation, audit page, undo.

## Location

Code:
- `frontend/console/src/routes/review/`
- `frontend/console/src/lib/components/review/`
- `backend/api/review.py`

Tests and fixtures:
- `frontend/console/tests/review/`
- `backend/tests/integration/api/test_review.py`

## Interfaces

Provides:
- /review/* API
- Review screens

Consumes:
- review backend models (backend/review-backend)
- viewer

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/console/src/routes/review/`
- `frontend/console/src/lib/components/review/`
- `backend/api/review.py`
- `frontend/console/tests/review/`
- `backend/tests/integration/api/test_review.py`

## Rubric (what "done" means for this feature)

- [ ] A folder-wide unit case resolves in one action and siblings resume within 2 minutes
- [ ] Undo works and is audited
- [ ] Handwriting and table panes added in M5
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
