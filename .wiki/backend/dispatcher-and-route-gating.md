# Dispatcher, type resolution, folder context, assembler, route gating

| Field | Value |
|-------|-------|
| Feature id | `backend/dispatcher-and-route-gating` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/03_phase2_processing_routes.md §1, §2 |
| Last updated | 2026-10-21 |

## Purpose

Resolve the real file type from magic bytes, build folder context (test ids, siblings, source-origin default), assemble multi-file documents, select the adapter, and park files whose route is disabled.

## Location

Code:
- `backend/dispatcher/type_resolution.py`
- `backend/dispatcher/folder_context.py`
- `backend/dispatcher/assembler.py`
- `backend/dispatcher/registry.py`
- `backend/dispatcher/contract.py` (published: `ProcessedDocument` and parts, `Flag` fingerprint, `Anchor` + `parse_anchor`/`format_anchor`)

Tests and fixtures:
- `backend/tests/unit/dispatcher/test_contract.py`
- `backend/tests/fixtures/dispatcher/`

## Interfaces

Provides:
- ProcessedDocument contract (`backend.dispatcher.contract`): also the staged payload JSON; nodes/assets/mentions cross-reference by route-chosen `ref`, never database ids
- Flag with `fingerprint` = sha256(flag_type | canonical anchor JSON, bbox rounded to 4 digits) and `page_or_sheet` for the case key
- Anchor model with S3's field names; the one owner of the `<kind>:<value>:<content_sha256>` format (`parse_anchor`, `format_anchor`, `Anchor.serialize/parse`)
- Box convention: `PageBox {page_no, x0, y0, x1, y1}` in 0..1, origin top-left, a list per node
- Flag evidence (`Evidence`, union on `kind`: unit_telemetry, unit_fact, array_schema, json_schema, conflict, parse_failure, low_confidence, sensitive, file_facts; provisional) and `Suggestion {resolution, confidence, rationale, proposed_by}`
- Resolution actions (`Resolution`, union on `action`), `ALLOWED_ACTIONS`, `ADMIN_ONLY_ACTIONS`: the file 06 §6 vocabulary shared by routes, review API and overlays
- route selection

Consumes:
- registry (backend/registry-and-blobs)
- routes.<X>.enabled config

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/dispatcher/type_resolution.py`
- `backend/dispatcher/folder_context.py`
- `backend/dispatcher/assembler.py`
- `backend/dispatcher/registry.py`
- `backend/dispatcher/contract.py`
- `backend/tests/unit/dispatcher/`
- `backend/tests/fixtures/dispatcher/`

## Rubric (what "done" means for this feature)

- [x] Output contract published with JSON round trip, fingerprint and reference tests
- [ ] Extension/content mismatch resolved by content and recorded
- [ ] Disabled route parks documents as WAITING_FOR_ROUTE with no flag
- [ ] LaTeX master + parts become one document with document_sources roles
- [ ] Unknown type raises UNSUPPORTED_FORMAT HARD
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | Published `contract.py` (route output contract, flags with fingerprints, stable anchors and their link format); 27 tests |
| 2026-10-21 | S1 | Typed flag evidence and suggestions; resolution actions moved here from review/api_models |

## Related

- `.wiki/index.md`
