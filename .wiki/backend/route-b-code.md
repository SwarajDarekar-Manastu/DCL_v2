# Route B: Python scripts and tooling docs

| Field | Value |
|-------|-------|
| Feature id | `backend/route-b-code` |
| Status | in-progress |
| Owner session | S6 |
| Spec | docs/architecture/03_phase2_processing_routes.md §6, file 04 §4.1 (code symbol), file 06 §4 |
| Last updated | 2026-10-23 |

## Purpose

Team scripts (Python, C, MATLAB), notebooks and tooling documents (Markdown, `.txt`, `.bat`, requirements) become retrievable nodes: one per function, class, method and script block, each with a context header, so "how do we compute expansion ratio" or "what limit does the validator use" finds the code.

## Location

Code (`backend/routes/b_code/`):
- `route.py`: `process_code` (entry point), `can_handle`, `Stores`, `split_symbol`, decoding, flags
- `symbols.py`: Tree-sitter walkers per language (`parse_python`, `parse_c`, `parse_matlab`): module header facts, symbols, parameters with units, calls, annotations
- `text_docs.py`: Markdown passages, text windows, requirements, notebook cells

Tests: `backend/tests/unit/routes/b_code/test_route_b.py` (synthetic sources; E1 `Test_plan_creator.py`, web C/MATLAB/notebook samples when `data/samples/` is present).

## Interfaces

Provides:
- `process_code(data, *, blob_sha256, file_name, folder, stores)` → `ProcessedDocument` (route B, parser_version 1)
- Extensions: `.py .pyw .c .h .m .ipynb .md .markdown .txt .bat .cmd`
- Nodes: `module_header` (ref `module`), `code_symbol` (ref `sym:<qualname>`, parts `#2…`; methods have `parent_ref` = their class); notebook cells `cell<n>`; documents `child`. Every node has `line_start`/`line_end` in the file (a notebook cell: the line of its `"cell_type"` key)
- `metadata`: `qualname`, `symbol_kind` (function, method, class, type, body), `signature`, `docstring`, `params` [{name, annotation, default, unit}], `calls`, `generated`, `part`
- Mentions: `annotation` (TODO/FIXME/XXX/HACK/BUG), `quantity` (constants with a unit suffix), `dependency` (requirements)
- Unit hashes: one `symbol` per qualname
- Catalog: `{language, generated, symbols}`, or `{dependencies}`, or `{language, cells}`
- CIR `dcl-cir/{sha256}/B/v1/`: `ast.json`, `module_header.md`
- Flags: SENSITIVE_CONTENT HARD (`backend/sync/gate.scan_secrets`), PARSE_FAILURE SOFT (syntax errors → text windows)

Consumes: tree-sitter 0.26 with the python, c and matlab grammars (parse group).

Waiting on others: S1 registers the adapter (`dcl.process.route_b`, cpu_parse) and the runner; S1 adds type kinds for `.c`/`.h`/`.m`.

## Workspace (files to touch when modifying this feature)

- `backend/routes/b_code/`
- `backend/tests/unit/routes/b_code/`

## Rubric (what "done" means for this feature)

- [x] Every function/class in the team scripts is retrievable by name (E1 Test_plan_creator: all defs, 98% of code lines covered)
- [x] Methods carry their class header
- [x] Hard-coded credentials raise SENSITIVE_CONTENT HARD
- [x] C CRC algorithm, MATLAB leap-year logic and notebook shortcuts are in node text
- [ ] Runner and adapter registered by S1; one live document committed

## Notes

- Markdown uses a heading splitter, not Docling's Markdown backend: Docling gives no line positions for Markdown and anchors need a line locator.
- Tokens are estimated by characters (6,000 ≈ 1,500 tokens) for the long-symbol split; exact counts happen in the chunker.
- MATLAB calls are not extracted (the grammar cannot tell a call from indexing).

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-23 | S6 | Route built: Python, C, MATLAB via Tree-sitter, notebooks, Markdown, text, requirements; tests on synthetic and real samples |
| 2026-10-23 | S6 | Samples smoke test `backend/tests/unit/routes/test_samples_smoke.py` (every accepted file in data/samples, vision off) |

## Related

- `backend/dispatcher-and-route-gating` (registry), `backend/chunker-and-anchors`, `backend/gate-and-scope` (secret scan)
