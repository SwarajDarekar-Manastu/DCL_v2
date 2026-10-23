# Route A2: JSON report sections and LaTeX sources

| Field | Value |
|-------|-------|
| Feature id | `backend/route-a2-source` |
| Status | in-progress |
| Owner session | S6 |
| Spec | docs/architecture/03_phase2_processing_routes.md §5 (A2), §1.3 (assembler), file 04 §4, file 06 §4 |
| Last updated | 2026-10-23 |

## Purpose

Parse the ground-truth report sources: a LaTeX project (master, parts, PDF twin) or a report JSON file becomes one `ProcessedDocument` with section breadcrumbs, `$…$` math, HTML tables, figures with captions, resolved references, a source map to `file:line` and a page map to the compiled PDF.

## Location

Code (`backend/routes/a2_source/`):
- `route.py`: `process_latex`, `process_json` (the entry points), `SourceFile`, `Stores`, `can_handle_tex`, `can_handle_json`, flags, CIR
- `latex.py`: include resolution with a source map (`assemble`), user macros (`collect_macros`), the pylatexenc `Walker` (blocks, labels, numbering), siunitx, `resolve_refs`
- `tables.py`: `tabular` family → HTML (`multicolumn`, `multirow`, header detection, `longtable` heads and feet)
- `bib.py`: BibTeX parser, cite text, reference text
- `json_sections.py`: schema sniffer (report section, section file, data array, config, unknown), flatten

Tests: `backend/tests/unit/routes/a2_source/` (synthetic projects inline; `test_real_samples.py` runs on E4 TP12 and E3 when `data/samples/` is present).

## Interfaces

Provides:
- `process_latex(files, *, title, folder, stores, folder_files, read_file, conflicts, vision, cloud_allowed, doc_id, twin_appendix)` and `process_json(files, *, title, folder, stores, schema_config)` → `ProcessedDocument` (route A2, parser_version 1)
- `files`: the assembler's plan as `SourceFile(path, blob_sha256, data, role)` with roles primary / part / visual_twin
- Node anchors: `line_start`/`line_end` are lines of `assembled.md`; `metadata.source` = `file:line`; with a twin, `page_no` = twin page of the section (S2's `process_twin`)
- CIR `dcl-cir/{sha256}/A2/v1/`: `assembled.md`, `structure.json`, `source_map.json`; `page_map.json` and `appendix/…` from `process_twin`
- Twin: page renders (`pages/{twin sha}/{nnnn}.png`), PDF-only pages through `twin_appendix` (a bound A1 `process_pdf`) under "Appendix (PDF-only)"
- Assets: `figures/{sha256}/{nnnn}{ext}` (kind `figure_crop`) for `\includegraphics` images found in the folder
- Mentions: `reference` (bibliography), `quantity` (siunitx, JSON strings with units)
- Flags: CONFLICT SOFT (assembler), PARSE_FAILURE HARD (full and per-section walk fail; invalid JSON), UNIT_AMBIGUITY SOFT (unit-less numeric table in a results section), SENSITIVE_CONTENT HARD (secret, `backend/sync/gate.scan_secrets`), SCHEMA_UNKNOWN SOFT (JSON)

Consumes:
- `backend/dispatcher/assembler.py` plans (S1), `config/report_json_schemas.yaml` (S5)
- `backend/routes/a1_office/metadata.py` (`extract_metadata`, `plan_conflicts`), `figures.render_plot`, `twin.process_twin` (S2)
- VisionService `classify_image` + `digitize_plot` for plot images, only when cloud processing is allowed
- pylatexenc 2.11 (parse group)

Waiting on others:
- S1: adapter registration and the `dcl.process.route_a2` runner (reads the plan's blobs, lists the subtree for `folder_files`, reads siblings by path)

## Workspace (files to touch when modifying this feature)

- `backend/routes/a2_source/`
- `backend/tests/unit/routes/a2_source/`

## Rubric (what "done" means for this feature)

- [x] Multi-file LaTeX project assembles into one document (E4 TP12: 11 sections and appendices A, B)
- [x] Unknown JSON shape indexes generically with SCHEMA_UNKNOWN SOFT
- [x] \ref and \cite resolve to readable text in chunks
- [x] Every node has a line locator; `source_map.json` maps it to `file:line`
- [x] Twin page map assigns a page to the TP12 sections (monotone); nodes carry `page_no`
- [ ] Runner and adapter registered by S1; one live document committed
- [ ] TikZ figures described (manual: low priority; today a figure node with the caption only)

## Notes

- The manual names Pandoc; file 01 lists "Pandoc / pylatexenc". pylatexenc keeps character positions, which the source map needs, and needs no binary. A failure of the walker on the whole body falls back to one walk per `\section`; only when every section fails is PARSE_FAILURE raised.
- The real section JSON files (`{id, title, order, content: {text, …}}`, written by `Test_plan_creator.py`) match no schema in `report_json_schemas.yaml`, so they index generically with SCHEMA_UNKNOWN; S5 can add a schema for that shape.
- doc_kind comes from A1's L1 rules (`Test_plan.tex` → `test_plan` even when the title says Report).

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | Lead | The `ValueError … is not in the subpath` on real documents was `primary_location` choosing each part's path from the alphabetically first copy of identical bytes in another test plan; `location_near` (dispatcher) now takes the copy beside the master. Test `backend/tests/unit/dispatcher/test_a2_copies.py`; end to end on a real report folder in `backend/tests/unit/indexing/test_route_tail.py` |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-23 | S6 | Twin through S2's `process_twin` (Lead ruling); own page map removed |
| 2026-10-23 | S6 | Route built: LaTeX (assembly, macros, walker, tables, figures, bibliography, twin page map) and JSON; tests on synthetic projects and E3/E4 |
| 2026-10-23 | S6 | Samples smoke test `backend/tests/unit/routes/test_samples_smoke.py` (every accepted file in data/samples, vision off) |
| 2026-10-23 | S6 | Import-light: the `route` module and `can_handle` need only the standard library and Pillow (the dispatcher's io_light image); parse libraries load inside the process functions. Guarded by `backend/tests/unit/routes/test_routes_import_light.py` |

## Related

- `backend/dispatcher-and-route-gating` (assembler, registry), `backend/route-a1-office` (metadata, figures), `backend/chunker-and-anchors`, `quality/config-data` (report schemas)
