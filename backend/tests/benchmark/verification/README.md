# Verification of golden benchmark values (owner: S5)

Golden numbers are verified outside the pipeline before they enter a case (S5 brief). Measured
results are company test data, so they never enter the public repository (DECISIONS.md
2026-10-22, option b):

| File | In git | Content |
|------|--------|---------|
| `backend/tests/benchmark/suites/telemetry.template.yaml` | yes | questions, metric names, methods, units, tolerances, notes |
| `backend/tests/benchmark/verification/telemetry_metrics.py` | yes | the metric functions and the `build` command |
| `data/benchmark/telemetry_sources.yaml` | no | run key → raw file under `data/samples/`; the team's workbook values for cross-checks |
| `data/benchmark/telemetry.json` | no | the importable suite with values (S3's import format) |

Build the suite (needs the E1–E3 samples, see `backend/tests/fixtures/README.md`):

```bash
uv run python backend/tests/benchmark/verification/telemetry_metrics.py build
uv run pytest backend/tests/benchmark
```

The test recomputes every value from the raw files and requires agreement with the team's own
analysis workbook within the case tolerance where one exists. Import into the Console with
`POST /benchmark/suites/telemetry/import` (body: `data/benchmark/telemetry.json`).

Verification notes for the first 15 cases (2026-10-22):

- TP7 Test 01: the valve-open window is the span where the valve signal (y7) exceeds 2.5 V. The
  window statistics of all six channels, the rise time T90 (first time chamber pressure reaches
  90% of its valve-open mean) and the decay time T10 reproduce the team's workbook to its two
  decimals. The thermocouple log is a separate 2 Hz device; it is aligned by wall-clock time
  (stream header date and time + t; logger timestamps), which reproduces all 32 temperature
  values of the workbook.
- The team's "Through put" is the mass-flow integral over the whole record; the case asks for
  the valve-open integral, which differs by about 9%.
- Injector 10 and Injector 14 runs have no matching team workbook; their values rest on the
  committed functions alone.
