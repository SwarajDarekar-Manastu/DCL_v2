# Route D: hardware inspection photos

| Field | Value |
|-------|-------|
| Feature id | `backend/route-d-photos` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §8 |
| Last updated | 2026-10-21 |

## Purpose

HEIC conversion, EXIF without GPS, pHash clusters, classify-first routing, hardware inspection prompt with folder context, text and image embeddings.

## Location

Code:
- `backend/routes/d_photos/`

Tests and fixtures:
- `backend/tests/unit/routes/d_photos/`
- `backend/tests/fixtures/route_d/`

## Interfaces

Provides:
- photo nodes with image_embedding
- web and thumbnail assets

Consumes:
- vision-service
- embedding-service

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/d_photos/`
- `backend/tests/unit/routes/d_photos/`
- `backend/tests/fixtures/route_d/`

## Rubric (what "done" means for this feature)

- [ ] Plots/screenshots are separated from hardware photos ≥97%
- [ ] Burst clusters cut vision calls ≥40%
- [ ] GPS never stored
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
