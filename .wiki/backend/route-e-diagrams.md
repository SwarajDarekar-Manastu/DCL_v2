# Route E: draw.io diagrams and XSD

| Field | Value |
|-------|-------|
| Feature id | `backend/route-e-diagrams` |
| Status | in-progress |
| Owner session | S6 |
| Spec | docs/architecture/03_phase2_processing_routes.md §9; DECISIONS 2026-10-23 (SVG, Visio, DXF via ezdxf; DWG → Route G `cad_reference`) |
| Last updated | 2026-10-23 |

## Purpose

Diagrams become a component/connection graph in `documents.catalog` plus focused text: a summary per page and one node per labeled component with its neighbourhood, so "what feeds SV-1?" retrieves one chunk. Formats: draw.io, XSD, SVG, Visio `.vsdx`, DXF.

## Location

Code (`backend/routes/e_diagrams/`):
- `route.py`: `process_diagram` (entry point), `can_handle`, `diagram_format`, `Stores`, XSD nodes, `read_schematic` pass, flags
- `graph.py`: `Graph` model, `graph_nodes` (summary + component nodes, tag/range mentions), `graph_flags`, `duplicate_tags`
- `drawio.py`: `<mxfile>` pages, compressed diagrams, cells, edges, containers, notes, embedded images; safe lxml parser
- `formats.py`: `parse_svg`, `parse_vsdx`, `parse_dxf` (+ `dxf_texts`), `parse_xsd`
- `render.py`: matplotlib render of a draw.io page; ezdxf matplotlib render of a DXF modelspace

Tests: `backend/tests/unit/routes/e_diagrams/test_route_e.py` (synthetic draw.io/XSD/SVG/VSDX/DXF; E6 Rev C and web pid_1, V-2 SVG, test4_connectors.vsdx, three_layers.dxf when `data/samples/` is present).

## Interfaces

Provides:
- `process_diagram(data, *, blob_sha256, file_name, folder, stores, vision=None, cloud_allowed=False, doc_id=None)` → `ProcessedDocument` (route E, parser_version 1); extensions `.drawio .dio .xsd .svg .vsdx .dxf` and XML that starts `<mxfile`/`<mxGraphModel`
- `documents.catalog`: `{diagram_format, pages, nodes, edges, groups, notes, extra, duplicate_tags}`; CIR `graph.json` (catalog + schematic readings)
- Nodes: `diagram_summary` per page (`page{n}`), `diagram_component` per labeled component (`c{page}:{id}`), `figure` (source vlm) per schematic reading; XSD: one `child` per element/type. `page_no` on every diagram node, `line_start` where the XML has one
- Assets: `diagrams/{sha256}/{page:02d}.png` (`diagram_render`), linked from the page summary
- Mentions: `tag` (PT-101, SV-1, T7), `quantity` (ranges such as 0–250 bar), `enumeration` (XSD)
- Flags: PARSE_FAILURE HARD (invalid XML, unreadable package/DXF); CONFLICT SOFT (> 30 % unlabeled connections, > 20 % orphan components; tags read by `read_schematic` that the file lacks)

Consumes: VisionService `read_schematic` (renders and embedded images, cloud only), `figures.render_schematic` (S2); lxml, ezdxf 1.4.4, matplotlib.

Waiting on others: S1 registers the adapter (`dcl.process.route_e`) and runner; S1 adds `.svg .vsdx .dxf` kinds.

## Workspace (files to touch when modifying this feature)

- `backend/routes/e_diagrams/`
- `backend/tests/unit/routes/e_diagrams/`

## Rubric (what "done" means for this feature)

- [x] draw.io components, edges and groups land in documents.catalog and graph.json
- [x] Every labeled component is a diagram_component node with its neighbours
- [x] draw.io line tags, SVG labels, Visio connector ends, DXF layers are in node text (S5 formats suite)
- [x] Invalid XML → PARSE_FAILURE HARD; > 30 % unlabeled edges → CONFLICT SOFT
- [ ] Runner and adapter registered by S1; one live document committed
- [ ] Revision supersession across documents (same title, older Rev → SUPERSEDED) — needs the commit path (S1)

## Notes

- No draw.io CLI on the workers: the render is drawn from the parsed geometry (rotations ignored). SVG has no rasterizer in the dependencies, so no render or `read_schematic` for SVG.
- Edge medium (dashed = electrical, solid = fluid) only on P&ID pages (`mxgraph.pid` shapes); fault trees and flow charts get none.
- Lines with neither end attached (dimension and leader lines) are counted as free lines, not connections, and do not count toward the unlabeled-edge check.
- The two real thruster drawings (E5, E6) are cross-sections whose labels are text cells, so they index as notes and raise the incomplete-graph CONFLICT (SOFT), as the manual's thresholds say.
- Visio arrows are usually inherited from the master; a glued connector counts as directed begin → end unless both arrows are explicitly off.

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-23 | S6 | Route built: draw.io, XSD, SVG, Visio, DXF; renders and read_schematic cross-check; tests on synthetic and real samples |
| 2026-10-23 | S6 | Samples smoke test `backend/tests/unit/routes/test_samples_smoke.py` (every accepted file in data/samples, vision off) |

## Related

- `backend/vision-service` (`read_schematic`), `backend/dispatcher-and-route-gating`, `backend/route-g-archives` (DWG and `.scdoc` as cad_reference)
