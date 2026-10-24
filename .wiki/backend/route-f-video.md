# Route F: test-cell and workshop videos

| Field | Value |
|-------|-------|
| Feature id | `backend/route-f-video` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §10 |
| Last updated | 2026-10-24 |

## Purpose

ffprobe triage, whisper transcripts with timestamps for workshops, ignition detection and keyframes for test videos, Gemini video timeline, deep links with timestamps.

## Location

Code:
- `backend/routes/f_video.py` (one module, file 10 §2): `process_video`, `probe`, `luminance`, `detect_ignition`, `keyframe_times`, `scene_changes`, `compress`, `audio_slice`, `scan_times`, `PartStore`, `transcribe_parts`, `windows`, `whisper_transcriber`, `_write_cir`
- `backend/dispatcher/media_run.py` (`process_f_document`, `_Parts`: the `PartStore` over the document's CIR prefix, `parts/{whisper model}/`)
- `backend/celery_redis/tasks_process.py` (`route_f(doc_id, checkpoints=0)`, `MAX_CHECKPOINTS = 12`, `_run(..., checkpoint=)`), `backend/celery_redis/queues.py` (media pool), `backend/devops/compose.yaml` (media worker memory)

Tests and fixtures:
- `backend/tests/unit/routes/f_video/` (synthetic clips from FFmpeg lavfi sources; transcriber injected)

## Interfaces

Provides:
- `process_video(data, blob_sha256=, file_name=, folder=, vision=, put_asset=, transcribe=, cloud_allowed=, doc_id=, put_cir=, parts=) -> ProcessedDocument`
- test-cell: one timeline `parent` node (t 0…duration) + `video_event` children with keyframe assets; `documents.catalog` = `{t0_ignition_video_ms, t0_ignition_confidence, t0_source, t_shutdown_video_ms, duration_s, has_audio, fps, working_copy}`
- workshop: 10-minute `parent` sections kept whole + `transcript_window` children (60–120 s, `metadata.deep_link = "#t=14m20s"`); slide frames as assets, described by `describe_slide`
- frame assets `frames/{sha}/{t_ms}.jpg`
- working copy (`compress`, `PARSER_VERSION = 2`): every step runs on a compressed H.264 MP4 (long side ≤ 1280, ≤ 30 fps, CRF 26, AAC mono 64k, faststart; HDR tone-mapped). It is stored as asset kind `video_proxy` at `videos/{sha}/proxy.mp4` and described in `catalog.working_copy`; a small H.264 source (< 2 Mbit/s) or a copy not at least 10 % smaller is used as is (`compressed: false` plus reason). The original stays in `dcl-raw`; `backend/api/viewer.py` plays the `video_proxy` asset (looked up by the primary blob) from any node of a video document, else the original. Research: `docs/architecture/research/video_compression.md`
- `audio_slice(audio, start_s, end_s)`: the transcriber reads only the samples of its own part (a whole-file `clip_timestamps` call still decodes everything) and shifts word times by the part start
- CIR files `probe.json`, `transcript.json` (word timestamps), `scenes.json`, `events.json` under `dcl-cir/{sha}/F/v2/` through `put_cir` (`_write_cir`)
- the timeline prompt's folder context names the file's real name, not the working copy's temp file
- transcription in 10-minute parts (`PART_S = 600`, 30 s overlap): faster-whisper's voice filter holds a whole part in memory (a 30-minute part passed 4 GiB, a 10-minute one peaks at 3.5 GiB). `transcribe_parts` saves each finished part through `PartStore` as `{start}-{end}.json` under `dcl-cir/{sha}/F/v2/parts/{whisper model}/` (one folder per model, so a model change never reuses parts) and reads a saved part instead of transcribing it again
- soft-time-limit re-queue: when a Route F task hits its soft time limit (3600 s) the document stays PROCESSING, the session is rolled back and `dcl.process.route_f` sends itself again on the media queue with `checkpoints + 1`; the next run reads the saved parts and continues. After `MAX_CHECKPOINTS = 12` re-queues no checkpoint is offered, so the next soft limit ends FAILED
- media worker memory is 6 GiB (`Pool(Queue.MEDIA, "prefork", 1, 6144, 2048, 3600, 3900, 2)`, compose `memory: 6144M`): the live worker runs about 0.8 GiB above a one-off container. Whisper keeps faster-whisper's default of 4 CPU threads (no `cpu_threads` is passed); measured on a 10.5-minute part, 8 threads took 686 s instead of 492 s and 4.2 GiB instead of 3.5 GiB
- ignition scan: when the brightness check finds no ignition and cloud processing is allowed, the timeline call gets `SCAN_FRAMES = 16` frames spread over the whole clip (`scan_times`) instead of the two keyframes, in the same single `video_timeline` call (prompt `video_timeline.v2`, medium resolution; the prompt defines ignition as the first frame with a plume, glow or flame at the nozzle, even small or far away). The model's first `ignition` event becomes t0 and its first later `shutdown` the stop; `catalog.t0_source` is `luminance`, `model reading of the frames` or null (then no t0 and the CONFLICT SOFT below). `t0_ignition_confidence` is set only for `luminance`. Events the model wrote have source `vlm`; the luminance events and audio spikes stay `structured`

Consumes:
- `backend/vision-service` (`video_timeline`, `describe_slide`)
- FFmpeg/ffprobe in the media image; faster-whisper (media worker, model from `routes.F.whisper_model`, default `medium` int8, 4 threads) through `whisper_transcriber()`

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/f_video.py`
- `backend/tests/unit/routes/f_video/`

## Rubric (what "done" means for this feature)

- [ ] Ignition timestamp within 0.5 s of telemetry t0 where both exist (detection within 0.5 s on a synthetic clip; the telemetry comparison needs S1's C.6 alignment)
- [x] Long recordings segment without losing transcript continuity (4,000 s in 10-minute parts: every word kept once; a saved part is not transcribed again after a checkpoint)
- [ ] Open: meetings now fit: 10-minute parts, a 6 GiB media worker and checkpoints (user decision 2026-10-24). The 88-minute meeting completed in a one-off container at 3.66 GiB with 10-minute parts, in 114 min; it has not yet been run on the live worker
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-24 | Lead | Meetings (user, DECISIONS 2026-10-24): media worker 6 GiB; transcription in 10-minute parts saved per whisper model in the CIR (`PartStore`, `media_run._Parts`); a task at its soft time limit re-queues itself and continues (`tasks_process.route_f`, at most 12 times); whisper keeps 4 threads. Test-cell timeline: 16 frames across the clip at medium resolution when the brightness check finds no ignition, prompt `video_timeline.v2`, model ignition becomes t0 (`catalog.t0_source`), model events marked `vlm`. Tests `test_f_video.py` |
| 2026-10-24 | Lead | Compressed working copy (`video_proxy`, migration 0016) that all steps and the viewer use; `audio_slice` per transcription part; CIR files written; real file name in the timeline prompt; viewer looks the copy up by blob. See DECISIONS 2026-10-24 |
| 2026-10-23 | Lead | Speech model is read from `routes.F.whisper_model` (default `medium` int8; was the `large-v3` default, which the 4 GiB media worker cannot hold): `media_run._transcriber(size)`, key validated in `pipeline_config`. Live: the 7.8 MB video that was OOM-killed three times now finishes ACTIVE_WITH_SOFT_FLAGS in 40 s at about 1.9 GiB. Tests `test_route_runners.py` |
| 2026-10-23 | Lead | A missing or weak ignition edge is a CONFLICT SOFT with `relation = check_failed` (detected / expected, file 03 §C.6), as the telemetry route raises its t0 doubt. It was LOW_CONFIDENCE_EXTRACTION with empty evidence: the reviewer saw a flag with nothing to look at and no fitting action. An already open flag of the old type stays until the document is processed again |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | Route F: ffprobe triage, speech check, ignition/shutdown from luminance, keyframes and `video_timeline`, acoustic events, workshop transcript parts, windows and sections; 8 tests |

## Related

- `.wiki/index.md`
