# Route G: archives and ANSYS packages

| Field | Value |
|-------|-------|
| Feature id | `backend/route-g-archives` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §11 |
| Last updated | 2026-10-21 |

## Purpose

Bomb-guarded extraction, members as blobs with blob_derivations, re-dispatch through the gate, .wbpz solver logs and material XML, .scdoc catalog reference.

## Location

Code:
- `backend/routes/g_archives/`

Tests and fixtures:
- `backend/tests/unit/routes/g_archives/`
- `backend/tests/fixtures/route_g/`

## Interfaces

Provides:
- blob_derivations rows
- member dispatch

Consumes:
- dispatcher (backend/dispatcher-and-route-gating)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/g_archives/`
- `backend/tests/unit/routes/g_archives/`
- `backend/tests/fixtures/route_g/`

## Rubric (what "done" means for this feature)

- [ ] Zip-bomb fixture is rejected with PARSE_FAILURE HARD
- [ ] A member identical to a loose file is not processed twice
- [ ] Nested archives stop at depth 3
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
