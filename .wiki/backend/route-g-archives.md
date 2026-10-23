# Route G: archives and ANSYS packages

| Field | Value |
|-------|-------|
| Feature id | `backend/route-g-archives` |
| Status | in-progress |
| Owner session | S6 |
| Spec | docs/architecture/03_phase2_processing_routes.md §11; DECISIONS 2026-10-23 (members as `derived_blobs`, `.dwg` like `.scdoc`, STL/STEP measured with trimesh + cascadio) |
| Last updated | 2026-10-23 |

## Purpose

Archives are opened safely and their members become documents of their own; ANSYS packages are summarized; CAD files become `cad_reference` documents, measured when they are meshes or B-reps and linked to the drawings next to them.

## Location

Code (`backend/routes/g_archives/`):
- `route.py`: `process` (runner entry), `process_archive`, `process_cad`, `can_handle`, `Stores`, manifest nodes, flags
- `archive.py`: `Expander` (bomb guard, gate per member, nested archives), `archive_kind`, limits
- `wbpz.py`: solver `.out` summary, MatML materials, analysis systems from `.wbpj`
- `cad.py`: `measure` (trimesh, cascadio), `related_files`, `describe`

Tests: `backend/tests/unit/routes/g_archives/test_route_g.py` (synthetic bombs, nesting, traversal, encryption, held members, gzip, tar symlinks, wbpz, STL, scdoc/dwg; X2 Injector.zip, web zip with junk, tar.gz, STL, STEP when `data/samples/` is present).

## Interfaces

Provides:
- `process(data, *, blob_sha256, file_name, folder, stores, path=None, folder_files=(), web_url=None, gate_config=None)` → `ProcessedDocument` (route G, parser_version 1); `.zip .tar .tar.gz .tgz .gz .wbpz .stl .step .stp .igs .iges .scdoc .dwg`
- Archives: `derived_blobs` = kept members (`archive_member`, bytes inside, `member_path` like `a/inner.zip!/b.txt`); contents nodes (60 members each, line = manifest line); catalog `{archive_format, members, kept, skipped, held, nested_archives, total_uncompressed_bytes, mostly_junk, routes}`; CIR `manifest.json`
- `.wbpz`: doc_kind `cae_package`; catalog `analysis_systems`, `materials`, `solver_logs`; solver nodes, one table node per material, `material` mentions; only images handed over
- CAD: doc_kind `cad_reference`; catalog `{cad_format, file_name, size_bytes, folder, web_url, measurement, references, folder_drawings}`; one node; `dimension` mention; CIR `cad.json`
- Flags: PARSE_FAILURE HARD (bomb guard: ratio > 100, > 5 GB, > 50,000 entries, depth > 3, traversal; encrypted; unreadable CAD) with the partial manifest; HELD_LARGE_FILE SOFT per member over 1 GB

Consumes: `backend/sync/gate.gate_item` + `config/gate.yaml` (S1), `backend/dispatcher/type_resolution.resolve_type` (S1), trimesh 5.1.1, cascadio 0.1.1, lxml.

Waiting on others: S1 registers the adapter (`dcl.process.route_g`) and runner (passes `path`, `folder_files`, `web_url`), calls `register_derived_blobs`, writes `document_relations(REFERENCES)` from `catalog.references`; type kinds for `.stl .step .stp .igs .iges .dwg` (today `resolve_type` sends `.step` members to Route C and has no kind for `.stl`).

## Workspace (files to touch when modifying this feature)

- `backend/routes/g_archives/`
- `backend/tests/unit/routes/g_archives/`

## Rubric (what "done" means for this feature)

- [x] Bomb-guard violations and encrypted archives → PARSE_FAILURE HARD with the manifest
- [x] Members become derived_blobs (archive_member); junk members are skipped by the gate
- [x] STL extents and STEP solids are in node text
- [x] `.scdoc`/`.dwg` → cad_reference with related exports
- [ ] Runner and adapter registered by S1; one live archive committed with its members as documents
- [ ] A real `.wbpz` checked (none in the samples; tested with a synthetic Workbench layout)

## Notes

- Members travel as bytes in the `ProcessedDocument`, so the worker holds an archive's kept members in memory; members over 1 GB are held.
- STL carries no units: measurements are in model units. cascadio returns STEP in metres; reported in mm.
- Nested archives are expanded in place (depth ≤ 3); the nested archive itself is listed, not handed over.

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-23 | S6 | Route built: archives with bomb guard and gate, derived blobs, wbpz, CAD measurement and references |
| 2026-10-23 | S6 | Samples smoke test `backend/tests/unit/routes/test_samples_smoke.py` (every accepted file in data/samples, vision off) |
| 2026-10-23 | S6 | Import-light: the `route` module and `can_handle` need only the standard library and Pillow (the dispatcher's io_light image); parse libraries load inside the process functions. Guarded by `backend/tests/unit/routes/test_routes_import_light.py` |

## Related

- `backend/registry-and-blobs` (`register_derived_blobs`), `backend/gate-and-scope`, `backend/route-e-diagrams`
