# Dispatcher, type resolution, folder context, assembler, route gating

| Field | Value |
|-------|-------|
| Feature id | `backend/dispatcher-and-route-gating` |
| Status | planned |
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
- `backend/dispatcher/contract.py`

Tests and fixtures:
- `backend/tests/unit/dispatcher/`
- `backend/tests/fixtures/dispatcher/`

## Interfaces

Provides:
- ProcessedDocument contract
- Anchor model
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

- [ ] Extension/content mismatch resolved by content and recorded
- [ ] Disabled route parks documents as WAITING_FOR_ROUTE with no flag
- [ ] LaTeX master + parts become one document with document_sources roles
- [ ] Unknown type raises UNSUPPORTED_FORMAT HARD
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
