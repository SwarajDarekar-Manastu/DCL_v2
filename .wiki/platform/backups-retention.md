# Backups, retention jobs, runbooks

| Field | Value |
|-------|-------|
| Feature id | `platform/backups-retention` |
| Status | deprecated |
| Owner session | S4 |
| Spec | docs/architecture/05 §6; 10 M11 |
| Last updated | 2026-10-21 |

## Purpose

**Dropped by user decision on 2026-10-22 (DECISIONS.md): no backups for now.** PostgreSQL and the single MinIO instance stay on local disk, with no off-host target, no WAL archiving and no bucket mirror. Retention code stays S1's (`backend/sync/retention.py`); S4 schedules it in beat when it exists.


PostgreSQL base+WAL, MinIO versioning, nightly retention deletes, runbooks for re-auth, 410 resync, worker OOM, Gemini outage, model-service restart.

## Location

Code:
- `backend/devops/backup/`
- `backend/devops/runbooks/`
- `backend/sync/retention.py`

Tests and fixtures:
- (none yet)

## Interfaces

Provides:
- restore drill procedure

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/devops/backup/`
- `backend/devops/runbooks/`
- `backend/sync/retention.py`

## Rubric (what "done" means for this feature)

- [ ] Restore drill completes in staging
- [ ] Retention never deletes done job rows of live documents
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S4 | Marked deprecated after the user decided against backups for now |

## Related

- `.wiki/index.md`
