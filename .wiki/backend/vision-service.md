# VisionService on Gemini (triage, handwriting, tables, plots, photos, video)

| Field | Value |
|-------|-------|
| Feature id | `backend/vision-service` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §3, §A1.2, §A1.7, §8, §10; 01 §5.4, §7 |
| Last updated | 2026-10-24 |

## Purpose

One component for every vision call through S4's gateway client: versioned prompts, structured-output schemas, content-hash cache, `llm_calls` context, no-guessing rules.

## Location

Code:
- `backend/llm_engine/vision/service.py` (`VisionService`, `FileMetadata`, `TASKS`, `PREAMBLE_VERSION`, cache key and input hash)
- `backend/llm_engine/vision/schemas.py` (the nine reading schemas)
- `backend/llm_engine/prompts/__init__.py` (`load_prompt(area, version)`, shared by every prompt user)
- `backend/llm_engine/prompts/vision/<capability>.v<n>.md` (the version each capability uses is pinned in `TASKS`: `transcribe_page.v2`, `read_schematic.v2`, `video_timeline.v2`, every other one v1; replaced versions stay in the folder) and the shared preamble `image_context.v2.md` (the v1 file is unused)

Tests and fixtures:
- `backend/tests/unit/llm_engine/vision/` (`FakeClient` in `conftest.py` implements only the client's adapter-neutral `generate_sync` and `record_cache_hit`; no gateway wire format in these tests)

## Interfaces

Provides:
- `VisionService(client: GeminiClient, cache=vision_cache(), *, extraction_safety=extraction_safety_from(session), file: FileMetadata | None = None)` with `triage_page`, `transcribe_page`, `transcribe_handwriting`, `read_table_image`, `digitize_plot`, `read_schematic`, `inspect_hardware_photo`, `describe_slide`, `video_timeline`, `classify_image` (Route D, Flash-Lite); each takes `Image` parts, keyword context, `doc_id`, `anchor` and returns `VisionOutput(reading, model, prompt_version, input_sha256, cached)`
- Schemas in `vision/schemas.py`: `PageTriage`, `PageTranscription`, `HandwritingReading`, `TableReading`, `PlotReading`, `SchematicReading`, `HardwarePhotoReading`, `SlideReading`, `VideoTimeline`, plus `ImageMetadata`; boxes are `box_2d` [ymin, xmin, ymax, xmax] 0–1000, top-left
- Preamble: every call's system text is `image_context.v2` + the task's system text, and its first user part is the preamble's `--- user ---` block filled with `FileMetadata.render()` (file name, folder, site, taken-out-of, test plan/run, hardware, origin, created and modified dates, other locations; "not known" without a file). The runner builds one service per document with `vision_for(session, file=file_metadata(ctx))` (`backend/dispatcher/runner.py`). `FileMetadata` carries no document title: the commit renames the title, which changed every cache key on a re-run
- `image_metadata` (`ImageMetadata`: `subject`, `setting`, `hardware`, `test_context`, `from_metadata`) is a required field of the five image-describing schemas (`PlotReading`, `SchematicReading`, `HardwarePhotoReading`, `SlideReading`, `VideoTimeline`); triage, transcription, table, handwriting and classify do not return it
- Cache key `_vision_cache/{model}/{prompt_version}/{input_sha256}.json` in `dcl-cir`; the hash covers the preamble version and the rendered file metadata. A hit makes no gateway call but writes an `llm_calls` row with status `cache_hit` through `GeminiClient.record_cache_hit(model, context)`
- `read_schematic.v2` (user, quality 2026-10-24): reads a schematic or a mechanical drawing; tags, labels, numbers and units are copied as printed, never a tag built from a part name, no medium unless drawn or in the legend; a mechanical drawing has no connections (dimension lines, leaders and hatching are not) and lists only parts with a printed name; notes start "Schematic." or "Mechanical drawing."
- `video_timeline.v2`: reads frames taken across the clip (the keyframes, or 16 frames of the whole clip when Route F's brightness check finds no ignition); defines ignition as the first frame with a plume, glow or flame at the nozzle, even small or far away; media resolution `medium` (v1: `low`). A new prompt version is a new cache key, so every earlier schematic and video reading is paid once again
- Prompt files: system text, `--- user ---`, `$variable` template; version = file stem; changing a prompt = new file + new pin in `TASKS`

Consumes:
- `platform/gemini-gateway-client` (`GeminiClient.generate_sync`, its ledger hook writes `llm_calls`)
- `backend/registry-and-blobs` (S1): `BucketStore` on `dcl-cir` from `backend/storage/minio.py` (`vision_cache()`)

## Behavior that callers rely on

- Safety settings: off unless `vision.extraction_safety` is set; the constructor takes the parsed set (`extraction_safety_from(session)` reads it), so whoever builds the service in a worker passes it

- `CapabilityUnavailable` while the gateway's image flag is off (until S4's probe runs); `BudgetExhausted` means retry later; `StructuredOutputError` is never cached.
- Handwriting: an illegible reading carries no value and confidence ≤ 0.5; a `value_number` that `value_raw` does not state is dropped.
- `video_timeline` takes timestamped frames (Route F sends the keyframes around the ignition, or 16 frames across the clip; each image follows a `t = … s` text part); the gateway has no video part.

## Workspace (files to touch when modifying this feature)

- `backend/llm_engine/vision/service.py`
- `backend/llm_engine/vision/schemas.py`
- `backend/llm_engine/prompts/__init__.py`
- `backend/llm_engine/prompts/vision/`
- `backend/tests/unit/llm_engine/vision/`

## Rubric (what "done" means for this feature)

- [x] Identical crops hit the cache and cost once (`test_identical_crops_cost_once`)
- [x] Every call appears in llm_calls with doc reference and tokens (ledger hook test; the table itself is S1's)
- [x] Handwriting output carries confidence and alternatives, never a guessed digit (schema tests)
- [x] MinIO-backed cache on `dcl-cir` (`vision_cache()` returns S1's `BucketStore`)
- [ ] One real call per capability through the gateway once S4's probe enables image input
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-24 | Lead | `read_schematic.v2` (verbatim tags, mechanical drawings have no connections) and `video_timeline.v2` (frames across the clip, ignition defined, medium resolution), both pinned in `TASKS` (DECISIONS 2026-10-24, quality and meetings) |
| 2026-10-24 | Lead | Shared preamble `image_context.v2` and per-file `FileMetadata` on every call; `image_metadata` required on the five describing schemas (v1 left it optional and the model dropped it on hardware photos); no document title in the metadata; cache hits recorded as `cache_hit`. Every vision cache key changed once. See DECISIONS 2026-10-24 |
| 2026-10-22 | S2 | Extraction safety flag: `pipeline_config` `vision.extraction_safety` (`true` or a list; default off) makes the seven extraction capabilities (transcribe_page, transcribe_handwriting, read_table_image, digitize_plot, read_schematic, describe_slide, video_timeline) send `EXTRACTION_SAFETY`; triage, photo and classify never do; unknown names refused |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | `transcribe_page.v2`: printed headers, footers and margin codes in `furniture` (not the body); v1 said to skip them. Wording kept neutral: an earlier draft ("they identify the document") was blocked with `block_reason=SAFETY` on a propellant paper |
| 2026-10-22 | S2 | `classify_image` capability for Route D (file 03 §8 step 3) |
| 2026-10-22 | S2 | `vision_cache()` on S1's BucketStore; tests moved to an adapter-neutral fake client (S4's gateway adapters change the wire format) |
| 2026-10-21 | S2 | Schemas, nine v1 prompt files, prompt loader, VisionService with cache and ledger context; 23 tests on a mock gateway |

## Related

- `platform/gemini-gateway-client`
- `backend/route-a1-office`, `backend/route-d-photos`, `backend/route-f-video` (callers)
- `backend/enrichment` (shares `load_prompt`)
- `.wiki/index.md`
