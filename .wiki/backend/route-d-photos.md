# Route D: hardware inspection photos

| Field | Value |
|-------|-------|
| Feature id | `backend/route-d-photos` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §8 |
| Last updated | 2026-10-24 |

## Purpose

HEIC conversion, EXIF without GPS, pHash clusters, classify-first routing, a general photo prompt (`inspect_hardware_photo.v2`: what the photo is for first, damage only when visible) with the folder, camera date and nearby photos as context, LOW_CONFIDENCE_EXTRACTION only on inspection photos, text and image embeddings. The node text is `figures.render_photo`, shared with photos inside documents.

## Location

Code:
- `backend/routes/d_photos.py` (one module while under ~600 lines, file 10 §2): `process_photo`, `normalize`, `cluster_photos`, `read_photo`, `PhotoReading`
- `classify_image` capability in `backend/llm_engine/vision/` (`prompts/vision/classify_image.v1.md`)

Tests and fixtures:
- `backend/tests/unit/routes/d_photos/` (synthetic JPEG/PNG/HEIC with EXIF, GPS and orientation)

## Interfaces

Provides:
- `process_photo(data, blob_sha256=, file_name=, folder=, vision=, put_asset=, cloud_allowed=, doc_id=, representative=, cluster_id=) -> (ProcessedDocument, PhotoReading | None)`; pass a burst representative's reading to its members (no vision call)
- `cluster_photos([(id, phash, taken_at)]) -> {id: representative_id}` for S1's assembler (pHash distance ≤ 6 within 60 s)
- flags: SENSITIVE_CONTENT HARD when a visible-text line contains an export marking (`EXPORT_MARKINGS`: EXPORT CONTROLLED, ITAR, RESTRICTED) as a whole word, as Route A1 matches ("SANITARY FITTING" no longer raises ITAR)
- one `photo` node (page 1, `asset_ref = "photo:web"`) whose image vector `index_document` computes from the web asset; assets `photos/{sha}/web.jpg` (1,600 px) and `thumb.jpg` (256 px) with pHash and GPS-free EXIF

Consumes:
- `backend/vision-service` (`classify_image`, `inspect_hardware_photo`, `digitize_plot`, `read_schematic`, `transcribe_page`)
- `backend/embedding-service` (image vectors, through `index_document`)
- pillow-heif, imagehash (parse group, Lead)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/d_photos.py`
- `backend/llm_engine/vision/` (classify capability)
- `backend/tests/unit/routes/d_photos/`

## Rubric (what "done" means for this feature)

- [ ] Plots/screenshots are separated from hardware photos ≥97%
- [ ] Burst clusters cut vision calls ≥40% (mechanism tested: a 5-photo burst costs 2 calls; the corpus rate is measured in M7)
- [x] GPS never stored (no EXIF in derivatives, none in asset EXIF or node text; test with a GPS-tagged input)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-24 | Lead | Export markings match whole words (`re.search` with `\b`), not substrings |
| 2026-10-23 | S2 | Import chain fixed for the media image (no PDF stack): `a1_office.figures` imports `preflight` only where a PDF crop is rendered; a test imports `d_photos` and `f_video` with pikepdf, pypdfium2, docling and lxml blocked (65 photos FAILED live) |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | Route D: HEIC, EXIF without GPS, pHash bursts, classify-first routing, photo node, web/thumb assets, flags; 9 tests |

## Related

- `.wiki/index.md`
