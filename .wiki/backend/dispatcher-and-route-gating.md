# Dispatcher, type resolution, folder context, assembler, route gating

| Field | Value |
|-------|-------|
| Feature id | `backend/dispatcher-and-route-gating` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §1, §2 |
| Last updated | 2026-10-23 |

## Purpose

Resolve the real file type from magic bytes, build folder context (test ids, siblings, source-origin default), assemble multi-file documents, select the adapter, and park files whose route is disabled.

## Location

Code:
- `backend/dispatcher/runner.py` (`run_document(session, minio, doc_id, route, parser_version, build, indexer)`: the shared runner for A1, A2, D, F: location, cloud_allowed, stores, build, gate, index, commit or park; `vision_for(session)`); `office_run.py` (A1 via S2's `process_office`: PDF, Word family, slides), `source_run.py` (A2 via S6's `process_latex`/`process_json`, paths relative to the assembler's subtree), `media_run.py` (D with bursts via `process_photo`, F via `process_video` + Whisper); B (`process_code`), E (`process_diagram`) and G (`g.process` + `write_references`) in `source_run.py`; tasks `dcl.process.route_a1|a2|b|e|g` (cpu_parse), `route_d|route_f` (media)
- `backend/dispatcher/type_resolution.py` (`resolve_type(head, name, zip_names) -> ResolvedType{kind, mime, route, by, ext_mismatch}`)
- `backend/dispatcher/folder_context.py` (`build_folder_context`: breadcrumb, TP/T/INJ ids with source, conflicts, siblings, folder kind, origin, trust tier)
- `backend/dispatcher/assembler.py` (`assemble`: LaTeX master + parts + PDF twin, orphan .tex, JSON section sets)
- `backend/dispatcher/routing.py` (`dispatch`: processing scope, typing, assembly, documents + document_sources, gating, UNSUPPORTED_FORMAT, CONFLICT flags, then `apply_supersessions`, then `release_waiting` (parked documents whose route is enabled and whose adapter accepts the file become PROCESSING; enqueued after the commit through `enqueue`); `sweep_documents`; `retype_waiting`; `reset_waiting`; CLI `dispatch | sweep | retype | reassemble --route X`); ZIP-based files typed by their members
- `backend/dispatcher/adapters.py` (registry: `Adapter{name, route, task, queue, can_handle}`, `adapter_for(route, head, name)`; a route is implemented kind by kind; Route C: `labjack_dat`, `tdms`, `delimited`, `workbook`, `config_file`; Route A1: `pdf` → `dcl.process.route_a1` on `cpu_parse`)
- `backend/dispatcher/office_run.py` (`process_a1_document(session, minio, doc_id, build, indexer)`: S1's side of Route A1 around S2's `process_pdf`; stores over `dcl-cir/{sha}/A1/v1/` and `dcl-assets`; gate, index, commit or park; `default_build()` with the production VisionService)
- `backend/celery_redis/tasks_process.py` (`dcl.process.dispatch` enqueues every PROCESSING document on its adapter's task, `dcl.process.sweep_documents`, io_light; `dcl.process.route_c`)
- `backend/dispatcher/contract.py` (published: `ProcessedDocument` and parts, `Flag` fingerprint, `Anchor` + `parse_anchor`/`format_anchor`)

Tests and fixtures:
- `backend/tests/unit/dispatcher/test_contract.py`, `test_type_resolution.py`, `test_folder_context.py`, `test_assembler.py`, `test_dispatch.py` (DB + MinIO), `conftest.py`
- `backend/tests/fixtures/dispatcher/`

## Interfaces

Provides:
- ProcessedDocument contract (`backend.dispatcher.contract`): also the staged payload JSON; nodes/assets/mentions cross-reference by route-chosen `ref`, never database ids
- Flag with `fingerprint` = sha256(flag_type | canonical anchor JSON, bbox rounded to 4 digits) and `page_or_sheet` for the case key
- Anchor model with S3's field names; the one owner of the `<kind>:<value>:<content_sha256>` format (`parse_anchor`, `format_anchor`, `Anchor.serialize/parse`)
- Box convention: `PageBox {page_no, x0, y0, x1, y1}` in 0..1, origin top-left, a list per node
- Flag evidence (`Evidence`, union on `kind`: unit_telemetry, unit_fact, array_schema, json_schema, conflict, parse_failure, low_confidence, sensitive, file_facts; provisional) and `Suggestion {resolution, confidence, rationale, proposed_by}`
- Resolution actions (`Resolution`, union on `action`), `ALLOWED_ACTIONS`, `ADMIN_ONLY_ACTIONS`: the file 06 §6 vocabulary shared by routes, review API and overlays
- type resolution: content first (file 03 §1.1 signatures, ZIP member names, delimiter sniff), extension refines text, `ext_mismatch` for `drive_items`; route None → `UNSUPPORTED_FORMAT`; pickles are named, never loaded
- route selection

Consumes:
- registry (backend/registry-and-blobs)
- routes.<X>.enabled config

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/dispatcher/type_resolution.py`
- `backend/dispatcher/folder_context.py`
- `backend/dispatcher/assembler.py`
- `backend/dispatcher/routing.py`
- `backend/dispatcher/adapters.py`
- `backend/dispatcher/office_run.py`
- `backend/dispatcher/location.py`
- `backend/dispatcher/runner.py`
- `backend/dispatcher/source_run.py`
- `backend/dispatcher/media_run.py`
- `backend/tests/unit/dispatcher/test_route_runners.py`
- `backend/tests/unit/dispatcher/test_derived.py`
- `backend/tests/unit/dispatcher/test_office_run.py`
- `backend/celery_redis/tasks_process.py`
- `backend/dispatcher/contract.py`
- `backend/tests/unit/dispatcher/`
- `backend/tests/fixtures/dispatcher/`

## Rubric (what "done" means for this feature)

- [x] Output contract published with JSON round trip, fingerprint and reference tests
- [x] Extension/content mismatch resolved by content and recorded (unit-tested incl. S5 fixture pdf_is_html; storing it on drive_items comes with the dispatcher)
- [x] Disabled route parks documents as WAITING_FOR_ROUTE with no flag (DB test)
- [x] LaTeX master + parts become one document with document_sources roles (S5 fixture two_latex_masters, DB test)
- [x] Unknown type raises UNSUPPORTED_FORMAT HARD (S5 fixture pdf_is_html: route NULL, HALTED, staged payload)
- [x] Live dispatch over E1–E11 on the stack DB (2026-10-22): 182 documents, all WAITING_FOR_ROUTE (A1 25, A2 23, B 4, C 40, D 84, E 2, F 4), 44 parts + 1 visual twin, 8 SOFT CONFLICTs (section files no master includes), 0 HALTED
- [x] Supersession on in-place modification: `apply_supersessions` (SUPERSEDES new→old, old SUPERSEDED only if no live location holds the old blob, column cleared) + daily `sweep_documents` (DB tests)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | Lead | `routes.held_kinds` (list of type-resolution kinds that wait as WAITING_FOR_ROUTE while their route is on): `RouteGate` and `route_gate()` in `routing.py`, honoured by `_new_document` and `release_waiting`, validated in `pipeline_config.py`; live value zip, gzip, wbpz, iges. `location.location_near()` picks each part's path from the copy beside the document's own file (the A2 `relative_to` error came from the alphabetically first copy in another test plan). Tests `test_held_kinds.py`, `test_a2_copies.py` |
| 2026-10-23 | Lead | Orphan notes are no longer flags (supersedes the row above for them): "not included by any master" / "no master found" go to `DocumentPlan.notes` and `documents.metadata_sources.assembler.notes`. Root cause found by reading Test Plan 10/A: the verdict was computed in one folder and stored on a document that stands for every byte-identical copy, so it was false for most of its 36 folders, and accept/ignore changed nothing. Two masters in one folder stays a CONFLICT note. Migration 0014 moved the 5 open ones and deleted their flags |
| 2026-10-23 | Lead | The assembler's doubts (`_conflict_flag`, A2's `conflict_flags`) are CONFLICT `relation = note` with no second side; before, side B was the made-up text "expected: one unambiguous document". A folder holding one loose `.tex` no master includes now gives a document titled after that file, not after the folder (several "Main_Files" rows in the queue could not be told apart). The flag message is unchanged (its hash is the fingerprint). Migration 0014 tags existing rows |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | Published `contract.py` (route output contract, flags with fingerprints, stable anchors and their link format); 27 tests |
| 2026-10-21 | S1 | Typed flag evidence and suggestions; resolution actions moved here from review/api_models |
| 2026-10-21 | S1 | Type resolution (magic bytes, sniffers, extension refinement, mismatch); 39 tests |
| 2026-10-22 | S1 | Adapter registry, release of parked documents, enqueue after commit (Route C LabJack first) |
| 2026-10-22 | S1 | Route A1 (PDF) adapter on cpu_parse with `office_run.py`; `folder_tree` public (settings previews); `Suggestion.resolution` optional (explicit no-suggestion) |
| 2026-10-23 | S1 | `dispatch_derived` and `_new_document` (one creation path for files and derived blobs); `location.py`; contract `ProcessedDocument.derived_blobs` (`DerivedBlob`, base64 in JSON); `LowConfidenceEvidence.page_ocr_text` and `ExtractionCrop.ocr_text` for the viewer's text toggle |
| 2026-10-23 | S1 | Shared runner; A1 on `process_office` (DOCX and slides released); adapters and tasks for A2, B, D, E, F, G (all eight routes); G members via `register_derived_blobs`, CAD references as REFERENCES; kinds for DXF/SVG/VSDX (E), STL/STEP/IGES/DWG (G), .m/.c/.h (B) |

## Related

- `.wiki/index.md`
