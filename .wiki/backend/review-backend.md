# Review backend: flags, fingerprints, staged payloads, rules, resume

| Field | Value |
|-------|-------|
| Feature id | `backend/review-backend` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/06_review_flags_and_halt_policy.md; 05 §4.5 |
| Last updated | 2026-10-21 |

## Purpose

Flag models with deterministic fingerprints and case keys, staged payloads for halted documents, the rules table with one precedence resolver, resume_from_staged with overlays, audit events.

## Location

Code:
- `services/review/models.py`
- `services/review/fingerprints.py`
- `services/review/rules.py`
- `services/review/resume.py`
- `services/review/api_models.py`

Tests and fixtures:
- `tests/unit/review/`
- `tests/integration/review/`

## Interfaces

Provides:
- review API models
- rules resolver
- resume task

Consumes:
- index commit (backend/index-commit)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/review/models.py`
- `services/review/fingerprints.py`
- `services/review/rules.py`
- `services/review/resume.py`
- `services/review/api_models.py`
- `tests/unit/review/`
- `tests/integration/review/`

## Rubric (what "done" means for this feature)

- [ ] Re-indexing a document does not duplicate or reopen its flags
- [ ] A folder-wide unit rule resumes every halted sibling
- [ ] Undo re-opens the flag and removes the overlay on rebuild
- [ ] Every human action writes audit_events
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
