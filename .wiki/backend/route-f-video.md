# Route F: test-cell and workshop videos

| Field | Value |
|-------|-------|
| Feature id | `backend/route-f-video` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §10 |
| Last updated | 2026-10-23 |

## Purpose

ffprobe triage, whisper transcripts with timestamps for workshops, ignition detection and keyframes for test videos, Gemini video timeline, deep links with timestamps.

## Location

Code:
- `backend/routes/f_video.py` (one module, file 10 §2): `process_video`, `probe`, `luminance`, `detect_ignition`, `keyframe_times`, `scene_changes`, `transcribe_parts`, `windows`, `whisper_transcriber`

Tests and fixtures:
- `backend/tests/unit/routes/f_video/` (synthetic clips from FFmpeg lavfi sources; transcriber injected)

## Interfaces

Provides:
- `process_video(data, blob_sha256=, file_name=, folder=, vision=, put_asset=, transcribe=, cloud_allowed=, doc_id=) -> ProcessedDocument`
- test-cell: one timeline `parent` node (t 0…duration) + `video_event` children with keyframe assets; `documents.catalog` = `{t0_ignition_video_ms, t0_ignition_confidence, t_shutdown_video_ms, duration_s, has_audio, fps}`
- workshop: 10-minute `parent` sections kept whole + `transcript_window` children (60–120 s, `metadata.deep_link = "#t=14m20s"`); slide frames as assets, described by `describe_slide`
- frame assets `frames/{sha}/{t_ms}.jpg`

Consumes:
- `backend/vision-service` (`video_timeline`, `describe_slide`)
- FFmpeg/ffprobe in the media image; faster-whisper large-v3 (media worker, Lead/S4) through `whisper_transcriber()`

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/f_video.py`
- `backend/tests/unit/routes/f_video/`

## Rubric (what "done" means for this feature)

- [ ] Ignition timestamp within 0.5 s of telemetry t0 where both exist (detection within 0.5 s on a synthetic clip; the telemetry comparison needs S1's C.6 alignment)
- [x] Long recordings segment without losing transcript continuity (4,000 s in 30-minute parts: every word kept once)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | Lead | Speech model is read from `routes.F.whisper_model` (default `medium` int8; was the `large-v3` default, which the 4 GiB media worker cannot hold): `media_run._transcriber(size)`, key validated in `pipeline_config`. Live: the 7.8 MB video that was OOM-killed three times now finishes ACTIVE_WITH_SOFT_FLAGS in 40 s at about 1.9 GiB. Tests `test_route_runners.py` |
| 2026-10-23 | Lead | A missing or weak ignition edge is a CONFLICT SOFT with `relation = check_failed` (detected / expected, file 03 §C.6), as the telemetry route raises its t0 doubt. It was LOW_CONFIDENCE_EXTRACTION with empty evidence: the reviewer saw a flag with nothing to look at and no fitting action. An already open flag of the old type stays until the document is processed again |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | Route F: ffprobe triage, speech check, ignition/shutdown from luminance, keyframes and `video_timeline`, acoustic events, workshop transcript parts, windows and sections; 8 tests |

## Related

- `.wiki/index.md`
