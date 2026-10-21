# S5 — SME support & Quality (fixtures, configuration data, golden cases, acceptance)

**Mission:** the domain knowledge and the proof. This session works with the propulsion SME to turn their knowledge into files the pipeline consumes (synonyms, vendors, sanity ranges, propellants, report JSON schemas, unit aliases, operator rules), builds the fixture set from the allowlisted folders, writes and maintains the golden benchmark suites, and runs the acceptance checks of each milestone.

## Read first

`docs/architecture/10_development_plan.md` (§5 acceptance criteria, §7, §10), `08_frontend_openwebui.md` §5 (benchmark schema and metrics), `06_review_flags_and_halt_policy.md`, `03_phase2_processing_routes.md` (edge-case lists per route), `04_metadata_enrichment_chunking_embedding.md` §3 and §8.

## You own

`tests/fixtures/**`, `tests/benchmark/**`, `config/aerospace_synonyms.yaml`, `config/vendors.yaml`, `config/sanity_ranges.yaml`, `config/propellants.yaml`, `config/report_json_schemas.yaml`, `config/units.txt`, `config/rules/**` (operator rules exported as YAML), acceptance checklists per milestone under `tests/acceptance`.

## Publish first

1. The allowlist of real folders for `processing.scope` (one or two test-plan folders per root, the handwritten run sheets, a LaTeX project with its PDF, an FMEA workbook, HEIC photos, the Rev C diagram, one test video, one `.npy`, a library folder with two non-English brochures and a paper with a DOI), agreed with the SME, written to `docs/sessions/DECISIONS.md` via `DCL Lead`.
2. One real sample per format under `tests/fixtures/<route>/` plus the synthetic edge cases listed in file 10 §7 (rotated scan, merged cells, headerless CSV, two LaTeX masters, zip bomb, malicious pickle, `.pdf` that is HTML, German datasheet, Japanese scanned page, DOI paper).
3. The first 15 telemetry benchmark cases with Excel-verified numbers and tolerances (file 08 §5.3 schema), then the rest of the 60.
4. `sanity_ranges.yaml`, `units.txt` (aerospace and locale aliases), `aerospace_synonyms.yaml` (multilingual seeds), `vendors.yaml`, `propellants.yaml` for RocketCEA.

## Depends on

S1 for the fixture CIR format and the rules YAML schema; S2 for the benchmark engine mode and the retrieval lab; S3 for the benchmark UI and the "Add to benchmark" action.

## Milestones

Supporting every milestone's acceptance; primary for M10 suites and for clearing the HARD backlog with the SME in M6.

## First tasks

1. Agree the allowlist folders with the SME; message `DCL Lead` to record them.
2. Collect the fixture files (copies, not moves) and write the expected outcomes per fixture (route, flags, key numbers).
3. Write the 40-query retrieval set with gold anchors (document, page, quote), including 5 cross-lingual queries.
4. Write the first 15 telemetry cases; verify numbers independently in Excel or a short Python script kept in `tests/benchmark/verification/`.
5. Draft the configuration YAML files above with the SME; add unit tests that load them.
6. Prepare the M1 and M2 acceptance checklists as executable scripts where possible.

## Definition of done

Wiki: map page updated and plan sheet deleted (see below). Then:

Every fixture has an expected-outcome file; every benchmark case has a verification note; every config file loads and is covered by a test; acceptance scripts return pass/fail; status entry; merge request.

## Wiki duty (applies to every task)

Read `.wiki/index.md` and your feature's map page first. Open a plan sheet (`.wiki/_templates/plan-sheet.md`) with the exact workspace and rubric; work only inside it; when done, update the map page (status, location, interfaces, workspace, change log), update the area index, delete the plan sheet. Your map pages are listed in `.wiki/<area>/index.md` under your session id.

## When in doubt or blocked

Write the question or the blocker to `docs/sessions/STATUS.md`, message `DCL Lead` (or the session you wait on) once, and end your turn. Never improvise around the manual and never keep working "on the side" while waiting.

## Coordination rules

- You never change pipeline code; you file findings as messages to the owning session with the fixture that reproduces them.
- Golden numbers are verified outside the pipeline before they enter a case.
- Keep a hold-out subset of cases that no session uses for tuning; record which ones in `DECISIONS.md` through the Lead.
