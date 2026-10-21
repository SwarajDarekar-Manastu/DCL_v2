# VisionService on Gemini (triage, handwriting, tables, plots, photos, video)

| Field | Value |
|-------|-------|
| Feature id | `backend/vision-service` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §3, §A1.2, §A1.7, §8, §10; 01 §5.4, §7 |
| Last updated | 2026-10-21 |

## Purpose

One component for every vision call through S4's gateway client: versioned prompts, structured-output schemas, content-hash cache, `llm_calls` context, no-guessing rules.

## Location

Code:
- `backend/llm_engine/vision/service.py` (`VisionService`, `TASKS`, cache key and input hash)
- `backend/llm_engine/vision/schemas.py` (the nine reading schemas)
- `backend/llm_engine/prompts/__init__.py` (`load_prompt(area, version)`, shared by every prompt user)
- `backend/llm_engine/prompts/vision/<capability>.v1.md` (nine prompt files)

Tests and fixtures:
- `backend/tests/unit/llm_engine/vision/` (`FakeClient` in `conftest.py` implements only the client's adapter-neutral `generate_sync`; no gateway wire format in these tests)

## Interfaces

Provides:
- `VisionService(client: GeminiClient, cache=vision_cache())` with `triage_page`, `transcribe_page`, `transcribe_handwriting`, `read_table_image`, `digitize_plot`, `read_schematic`, `inspect_hardware_photo`, `describe_slide`, `video_timeline`, `classify_image` (Route D, Flash-Lite); each takes `Image` parts, keyword context, `doc_id`, `anchor` and returns `VisionOutput(reading, model, prompt_version, input_sha256, cached)`
- Schemas in `vision/schemas.py`: `PageTriage`, `PageTranscription`, `HandwritingReading`, `TableReading`, `PlotReading`, `SchematicReading`, `HardwarePhotoReading`, `SlideReading`, `VideoTimeline`; boxes are `box_2d` [ymin, xmin, ymax, xmax] 0–1000, top-left
- Cache key `_vision_cache/{model}/{prompt_version}/{input_sha256}.json` in `dcl-cir`; a hit makes no gateway call and no ledger row
- Prompt files: system text, `--- user ---`, `$variable` template; version = file stem; changing a prompt = new file + new pin in `TASKS`

Consumes:
- `platform/gemini-gateway-client` (`GeminiClient.generate_sync`, its ledger hook writes `llm_calls`)
- `backend/registry-and-blobs` (S1): `BucketStore` on `dcl-cir` from `backend/storage/minio.py` (`vision_cache()`)

## Behavior that callers rely on

- `CapabilityUnavailable` while the gateway's image flag is off (until S4's probe runs); `BudgetExhausted` means retry later; `StructuredOutputError` is never cached.
- Handwriting: an illegible reading carries no value and confidence ≤ 0.5; a `value_number` that `value_raw` does not state is dropped.
- `video_timeline` takes timestamped keyframes; the gateway has no video part.

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
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | `classify_image` capability for Route D (file 03 §8 step 3) |
| 2026-10-22 | S2 | `vision_cache()` on S1's BucketStore; tests moved to an adapter-neutral fake client (S4's gateway adapters change the wire format) |
| 2026-10-21 | S2 | Schemas, nine v1 prompt files, prompt loader, VisionService with cache and ledger context; 23 tests on a mock gateway |

## Related

- `platform/gemini-gateway-client`
- `backend/route-a1-office`, `backend/route-d-photos`, `backend/route-f-video` (callers)
- `backend/enrichment` (shares `load_prompt`)
- `.wiki/index.md`
