# Route F: test-cell and workshop videos

| Field | Value |
|-------|-------|
| Feature id | `backend/route-f-video` |
| Status | planned |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §10 |
| Last updated | 2026-10-21 |

## Purpose

ffprobe triage, whisper transcripts with timestamps for workshops, ignition detection and keyframes for test videos, Gemini video timeline, deep links with timestamps.

## Location

Code:
- `backend/routes/f_video/`

Tests and fixtures:
- `backend/tests/unit/routes/f_video/`
- `backend/tests/fixtures/route_f/`

## Interfaces

Provides:
- transcript_window and video_event nodes
- frame assets
- t0_ignition_video_ms

Consumes:
- vision-service
- media queue (platform/compose-stack)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/f_video/`
- `backend/tests/unit/routes/f_video/`
- `backend/tests/fixtures/route_f/`

## Rubric (what "done" means for this feature)

- [ ] Ignition timestamp within 0.5 s of telemetry t0 where both exist
- [ ] Long recordings segment without losing transcript continuity
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
