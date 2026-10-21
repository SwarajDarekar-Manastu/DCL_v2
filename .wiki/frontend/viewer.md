# Shared document viewer with anchor resolution and translate toggle

| Field | Value |
|-------|-------|
| Feature id | `frontend/viewer` |
| Status | in-progress (wired to the database; end-to-end citation check after a real re-index waits for S1's commit path) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §6, §4.4; 04 §4.4, §10 |
| Last updated | 2026-10-21 |

## Purpose

One page for every citation, review case and benchmark drilldown: renders the cited page (with bbox overlays), image, table, code, text or video at the anchor; resolves stable anchors with an explicit page fallback; metadata, OneDrive and download links; translate toggle.

## Location

Code:
- `backend/api/viewer.py` (`viewer_path`, `ViewerPayload` models, `build_viewer_payload` over documents, document_sources, drive_items, assets and `resolve_anchor`; `GET /docs/{doc_id}/viewer` with `get_session`; the anchor format itself is `parse_anchor` / `format_anchor` in `backend/dispatcher/contract.py`, S1)
- `frontend/console/src/lib/api_endpoint.ts` (`ViewerPayload` types, `getViewer`)
- `frontend/console/src/lib/components/viewer/` (`DocumentViewer`, `ImageWithRegions`, `TableView`, `CodeView`, `MetaPanel`)
- `frontend/console/src/routes/docs/[id]/viewer/+page.svelte`
- `backend/api/assets.py` (`GET /assets/url?uri=s3://dcl-assets/...`, built with the Review UI)

Tests and fixtures:
- `backend/tests/unit/api/test_viewer.py`
- `backend/tests/integration/api/test_viewer_payload.py` (real ParadeDB via `DCL_TEST_DATABASE_URL`)
- `frontend/console/tests/viewer/` (`fixtures.ts`, `DocumentViewer.test.ts`, `ImageWithRegions.test.ts`)

## Interfaces

Provides:
- Deep link `{CONSOLE_URL}/docs/{doc_id}/viewer?anchor=<kind>:<value>:<content_sha256>`; kinds `page:12:<h>`, `line:120:<h>`, `t:83500:<h>` (ms), `cells:<sheet>!<A1 range>:<h>`; hash lowercase hex 16–64 or empty; trailing colon always written; never a node id. Build with `viewer_path(doc_id, anchor.locator_fields())`; the format is owned by `backend/dispatcher/contract.py`.
- `GET /docs/{doc_id}/viewer?anchor=…&translate=true|false` (role viewer) → `ViewerPayload`: `document` (kind, origin, tier, language, test ids, date, status, open flags), `resolution` (`exact` | `page_fallback` | `document_only` + message), `view` (discriminated by `kind`: `page`, `image`, `table`, `code`, `text`, `video`), `links` (all OneDrive locations, presigned original, review case key), `translation` (source language, available, translated text, pending). Regions are normalized 0–1 of the rendered image, origin top-left. Table cells are text, never HTML. 400 on a bad anchor (checked before any read), 404 for an unknown document. View choice: page render asset of the resolved page → `page` with the cited boxes; code nodes → `code` (line anchors highlight the line); photo nodes → `image`; transcript/video nodes → `video` of the original; otherwise `text`. Locations come from `drive_items` of the primary blob until `v_doc_locations` exists; `open_flags` and `review_case_key` stay empty until `review_flags` exists.

Consumes (to wire the endpoint body):
- `Anchor`, `parse_anchor`, `format_anchor`, `PageBox` (S1 `backend/dispatcher/contract.py`, on main), documents, `v_doc_locations`, `assets` page renders with width/height, presign 15 min (S1 `backend/storage`)
- `resolve_anchor` (S2 `backend/indexing/anchors.py`) with exact / fallback status and the bbox unit it stores
- `content_en` and on-the-fly translation (S2 enrichment) for the translate toggle

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/api/viewer.py`
- `backend/api/assets.py`
- `backend/tests/unit/api/test_viewer.py`
- `backend/tests/integration/api/test_viewer_payload.py` (real ParadeDB via `DCL_TEST_DATABASE_URL`)
- `frontend/console/src/lib/api_endpoint.ts` (viewer section)
- `frontend/console/src/lib/components/viewer/`
- `frontend/console/src/routes/docs/[id]/viewer/`
- `frontend/console/tests/viewer/`
- `backend/tests/integration/api/test_viewer_payload.py`

## Rubric (what "done" means for this feature)

- [ ] Citation links open the right page after a forced re-index (end to end; needs S1 commit path and S2 resolver)
- [x] Fallback to page is shown explicitly when content changed (component test and browser check with a mock API)
- [x] Anchor link codec round-trips page, line, time and cells (sheet names with `:` and `!`); malformed anchors get 400
- [x] bbox overlays follow normalized coordinates at any rendered size (component test; checked at 1280 px and 375 px)
- [x] No node id in links, payloads or Console state (grep)
- [x] Endpoint body wired to real data (integration tests: exact with boxes, changed hash → page fallback, moved passage still exact, location gone → document start, code line, translation)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

Verify:

```bash
cd frontend/console && npm run check && npm test && npm run build
uv run --with 'pyjwt[crypto]' --with redis python -m pytest backend/tests/unit/api
grep -rn "node_id" frontend/console/src backend/api/viewer.py   # prints nothing
```

Deployment note: presigned MinIO URLs must be reachable from engineers' browsers (S4); the Console never holds MinIO credentials.

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S3 | Deep-link contract, payload models, Console viewer page and components, tests; endpoint 501 until wired |
| 2026-10-22 | S3 | Endpoint wired: `build_viewer_payload` over real tables and `resolve_anchor`; integration tests on ParadeDB |
| 2026-10-21 | S3 | Anchor codec delegated to `backend/dispatcher/contract.py`; viewer keeps `viewer_path` (the temporary `parse_anchor_param` alias is removed) |

## Related

- `.wiki/index.md`
- `backend/chunker-and-anchors` (`resolve_anchor`), `backend/schema-and-migrations` (documents, assets), `backend/registry-and-blobs` (presign)
- `backend/answer-engine` (emits citation links with `viewer_path`), `frontend/review-ui`, `frontend/benchmark-ui` (open the viewer)
- `frontend/console-shell-auth`
