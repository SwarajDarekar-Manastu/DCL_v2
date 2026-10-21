# Backups, retention jobs, runbooks

| Field | Value |
|-------|-------|
| Feature id | `platform/backups-retention` |
| Status | planned |
| Owner session | S4 |
| Spec | docs/architecture/05 §6; 10 M11 |
| Last updated | 2026-10-21 |

## Purpose

PostgreSQL base+WAL, MinIO versioning, nightly retention deletes, runbooks for re-auth, 410 resync, worker OOM, Gemini outage, model-service restart.

## Location

Code:
- `deploy/backup/`
- `deploy/runbooks/`
- `services/sync/retention.py`

Tests and fixtures:
- (none yet)

## Interfaces

Provides:
- restore drill procedure

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `deploy/backup/`
- `deploy/runbooks/`
- `services/sync/retention.py`

## Rubric (what "done" means for this feature)

- [ ] Restore drill completes in staging
- [ ] Retention never deletes done job rows of live documents
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
