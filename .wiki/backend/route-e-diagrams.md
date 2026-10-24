# Route E: draw.io diagrams and XSD

| Field | Value |
|-------|-------|
| Feature id | `backend/route-e-diagrams` |
| Status | in-progress |
| Owner session | S6 |
| Spec | docs/architecture/03_phase2_processing_routes.md §9; DECISIONS 2026-10-23 (SVG, Visio, DXF via ezdxf; DWG → Route G `cad_reference`) |
| Last updated | 2026-10-24 |

## Purpose

Diagrams become a component/connection graph in `documents.catalog` plus focused text: a summary per page and one node per labeled component with its neighbourhood, so "what feeds SV-1?" retrieves one chunk. Formats: draw.io, XSD, SVG, Visio `.vsdx`, DXF.

## Location

Code (`backend/routes/e_diagrams/`):
- `route.py`: `process_diagram` (entry point), `can_handle`, `diagram_format`, `Stores`, XSD nodes, `read_schematic` pass, `completeness` note, flags
- `graph.py`: `Graph` model, `graph_nodes` (summary + component nodes, `sensor_tag`/range mentions), `graph_flags`, `completeness`, `duplicate_tags`
- `drawio.py`: `<mxfile>` pages, compressed diagrams, cells, edges, containers, notes, embedded images; safe lxml parser
- `formats.py`: `parse_svg`, `parse_vsdx`, `parse_dxf` (+ `dxf_texts`), `parse_xsd`
- `render.py`: matplotlib render of a draw.io page; ezdxf matplotlib render of a DXF modelspace

Tests: `backend/tests/unit/routes/e_diagrams/test_route_e.py` (synthetic draw.io/XSD/SVG/VSDX/DXF; E6 Rev C and web pid_1, V-2 SVG, test4_connectors.vsdx, three_layers.dxf when `data/samples/` is present).

## Interfaces

Provides:
- `process_diagram(data, *, blob_sha256, file_name, folder, stores, vision=None, cloud_allowed=False, doc_id=None)` → `ProcessedDocument` (route E, parser_version 1); extensions `.drawio .dio .xsd .svg .vsdx .dxf` and XML that starts `<mxfile`/`<mxGraphModel`
- `documents.catalog`: `{diagram_format, pages, nodes, edges, groups, notes, extra, duplicate_tags, completeness}`; CIR `graph.json` (catalog + schematic readings)
- `catalog.completeness` (draw.io and Visio graphs; not SVG, DXF or XSD, which expect no connections): `{incomplete, unlabeled_edges: [count, total], orphan_components: [count, total], reasons}`. An incomplete drawing is kept (user, 2026-10-24): when `incomplete` the first summary node ends with the line `Diagram incomplete: <reasons>` (for example `5 of 5 unlabeled edges`), and the SOFT CONFLICT below is raised as before; it never halts
- Nodes: `diagram_summary` per page (`page{n}`), `diagram_component` per labeled component (`c{page}:{id}`), `figure` (source vlm) per schematic reading, whose `metadata.structured_reading` holds the whole reading (with `image_metadata`), as for A1 figures and D photos; XSD: one `child` per element/type. `page_no` on every diagram node, `line_start` where the XML has one
- Assets: `diagrams/{sha256}/{page:02d}.png` (`diagram_render`) for draw.io pages, SVG and DXF, linked from the page summary
- Mentions: `sensor_tag` (PT-101, SV-1, T7; `tag` is not an entity type and the commit dropped it, so tag lookup through `entity_mentions` now works; an equipment tag the enrichment model types as `component` in prose stays a separate entity), `quantity` (ranges such as 0–250 bar), `enumeration` (XSD)
- Flags: PARSE_FAILURE HARD (invalid XML, unreadable package/DXF); CONFLICT SOFT (> 30 % unlabeled connections, > 20 % orphan components; tags read by `read_schematic` that the file lacks)

Consumes: VisionService `read_schematic` (renders and embedded images, cloud only; prompt `read_schematic.v2`: tags and labels copied as printed, never a tag built from a part name, a mechanical drawing has no connections and its notes start "Mechanical drawing."), `figures.render_schematic` (S2); lxml, ezdxf 1.4.4, matplotlib, resvg-py 0.5.0.

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

- No draw.io CLI on the workers: the render is drawn from the parsed geometry (rotations ignored). SVG is rasterized by resvg-py 0.5.0 (English `<switch>` variants, relative image links not resolved) at the draw.io size rule, and `read_schematic` reads it.
- Edge medium (dashed = electrical, solid = fluid) only on P&ID pages (`mxgraph.pid` shapes); fault trees and flow charts get none.
- Lines with neither end attached (dimension and leader lines) are counted as free lines, not connections, and do not count toward the unlabeled-edge check.
- The two real thruster drawings (E5, E6) are cross-sections whose labels are text cells, so they index as notes and raise the incomplete-graph CONFLICT (SOFT), as the manual's thresholds say.
- Visio arrows are usually inherited from the master; a glued connector counts as directed begin → end unless both arrows are explicitly off.

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-24 | Lead | Incomplete diagrams are kept and tagged (user, quality): `graph.completeness` -> `catalog.completeness` and a `Diagram incomplete: …` line in the first summary node, plus the existing SOFT CONFLICT; `read_schematic.v2` (verbatim tags, mechanical drawings). Test `test_mostly_unlabeled_edges_mark_the_graph_incomplete` |
| 2026-10-24 | Lead | Diagram tags are mention kind `sensor_tag` (were dropped at commit); schematic reading kept as `metadata.structured_reading` on the `figure` node |
| 2026-10-23 | S6 | Route built: draw.io, XSD, SVG, Visio, DXF; renders and read_schematic cross-check; tests on synthetic and real samples |
| 2026-10-23 | S6 | Samples smoke test `backend/tests/unit/routes/test_samples_smoke.py` (every accepted file in data/samples, vision off) |
| 2026-10-23 | S6 | SVG render with resvg-py; read_schematic on it |
| 2026-10-23 | S6 | Import-light: the `route` module and `can_handle` need only the standard library and Pillow (the dispatcher's io_light image); parse libraries load inside the process functions. Guarded by `backend/tests/unit/routes/test_routes_import_light.py` |

## Related

- `backend/vision-service` (`read_schematic`), `backend/dispatcher-and-route-gating`, `backend/route-g-archives` (DWG and `.scdoc` as cad_reference)
