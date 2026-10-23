# Route-level acceptance over the public format samples

Lead ruling 2026-10-23: the public samples in the git-ignored `data/samples/web/` (sources, licenses and
hashes in its `SOURCES.md`) have no OneDrive location and never become stack documents, so they are checked
at the route, not through the engine. `test_format_routes.py` calls each route's entry point on the local
sample the way S6's smoke test does (vision off, stores that only return keys) and asserts the extraction
recorded in the git-ignored `data/benchmark/formats.local.yaml` (13 entries: expected entities, numbers with
tolerances, the cited sample).

```bash
uv run --group parse pytest backend/tests/acceptance/test_format_routes.py -v
```

| Route | Sample (in `data/samples/web/`) | Asserted |
|-------|-------------------------------|----------|
| A1 | `docx/` tax-cases document | a table cell value reaches the nodes (needs `soffice` and `tesseract`: skipped on hosts without them, runs in the parse image) |
| A1 | `pptx/` python-pptx test slide | the slide table's column headers |
| B | `c/` cFE CRC module | the CRC algorithm function and the NONE fallback |
| B | `m/` MathWorks day-of-year function | the leap-year February value |
| B | `ipynb/` Jupyter "Running Code" | the three run shortcuts from markdown cells |
| C | `tdms/` synthetic hot-fire record | unit taken from `unit_string`, peak chamber pressure within 0.5 % |
| E | `drawio/` compressed P&ID | the three line tags |
| E | `svg/` V-2 cutaway | the two steering-surface labels |
| E | `vsdx/` connector sample | the shapes a labelled connector joins |
| E | `dxf/` three-layer drawing | the three named layers |
| G | `zip/` nested project | the three source members kept, the `.DS_Store` member skipped |
| G | `stl/` CubeSat top panel | bounding-box extents within 1 % |
| G | `step/` CadQuery test model | solid count and solid names |

Each check was shown to fail when its expected values are changed (mutation run, 2026-10-23). The checks
skip when the samples, the values file or a route library (`--group parse`) are absent.
