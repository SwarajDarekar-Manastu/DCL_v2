# Domain configuration data (synonyms, vendors, sanity ranges, units, propellants, report schemas, rules)

| Field | Value |
|-------|-------|
| Feature id | `quality/config-data` |
| Status | in-progress |
| Owner session | S5 |
| Spec | docs/architecture/04 §3.3, §8; 03 §1.3, §A2.1, §C.1; 06 §8; 10 §2 |
| Last updated | 2026-10-21 |

## Purpose

YAML/text data the pipeline loads, authored with the SME and covered by load tests.

## Location

Code:
- `config/aerospace_synonyms.yaml`
- `config/vendors.yaml`
- `config/sanity_ranges.yaml`
- `config/units.txt`
- `config/propellants.yaml`
- `config/report_json_schemas.yaml`
- `config/gate.yaml`
- `config/rules/proposed/` (S5 channel-map proposals for E1–E3; not applied until an SME or the user confirms; README)
- `config/rules/*.yaml` (confirmed operator rules; none yet)

Tests and fixtures:
- `backend/tests/unit/config_data/` (conftest.py with fixtures; one `test_config_<file>.py` per file)

## Interfaces

Provides (formats are documented in each file's header; the tests' JSON Schemas are the contract):
- `units.txt`: pint definitions (`load_definitions`) plus `#= surface => expr | dimension` alias lines; consumer applies aliases longest-first before pint. Gauge/absolute is not carried by pint (`backend/common/units.py`, S1)
- `sanity_ranges.yaml` (v2): ordered `ranges[]` of `{id, physical_quantity, canonical_name_glob, dimension, unit, min, max, checks_external_kept}`; first match on S1's channel_map `physical_quantity` + `canonical_name` applies (Route C bounds); `id` is the numeric-fact quantity label (S2 `suspect`)
- `aerospace_synonyms.yaml`: `entities[]` typed by the closed list of 04 §3.2, `quantity_terms[]` (load target open), aliases `{surface, lang}` (S2 entity normalization)
- `vendors.yaml`: `vendors[]` with aliases, case-sensitive short aliases, domains, `internal_equipment` (L1 origin detectors)
- `propellants.yaml`: RocketCEA cards with published reference checks (physics_calculator, S2)
- `report_json_schemas.yaml`: `schemas[]` (required keys, ordered sections) and `section_file_sets[]` (Route A2, assembler, S1)
- `gate.yaml`: S1's GateConfig schema (docstring of `backend/sync/gate.py`): tier-1 segments, quarantine globs, tier-2 endings/names/prefixes, `junk_extensions_under`, shortcuts, `max_download_bytes`, `kept_endings_by_parent_kind` (junk gate, S1)
- every entry except `gate.yaml` carries `sme_confirmed` (false until the SME review)

Consumes:
- (none)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `config/aerospace_synonyms.yaml`
- `config/vendors.yaml`
- `config/sanity_ranges.yaml`
- `config/units.txt`
- `config/propellants.yaml`
- `config/report_json_schemas.yaml`
- `config/gate.yaml`
- `config/rules/`
- `backend/tests/unit/config_data/conftest.py`
- `backend/tests/unit/config_data/test_config_units.py`
- `backend/tests/unit/config_data/test_config_sanity_ranges.py`
- `backend/tests/unit/config_data/test_config_synonyms.py`
- `backend/tests/unit/config_data/test_config_vendors.py`
- `backend/tests/unit/config_data/test_config_propellants.py`
- `backend/tests/unit/config_data/test_config_report_schemas.py`
- `backend/tests/unit/config_data/test_config_gate.py`
- `backend/tests/unit/config_data/test_config_rules.py`
- `pyproject.toml` (dev dependencies only: pint, pyyaml, jsonschema, rocketcea)

## Rubric (what "done" means for this feature)

- [x] Every file loads and is covered by a test (seven files; `config/rules/` pending its schema)
- [x] Synonym seeds include non-English surfaces (de, fr, es, it, ru, ja, zh)
- [x] Every unit alias and sanity-range unit resolves with its declared dimension
- [x] RocketCEA reproduces the published HTP 90/98 decomposition temperatures within 1.5%
- [x] `gate.yaml` equals the file 02 §4 lists plus two recorded judgment calls; decisions verified through S1's GateConfig (S1 branch 100eae2; the test runs it automatically once on main)
- [ ] Gate rejection counts checked against the real crawl (segments build/env/backup, endings .log/.bin/.tab/.out)
- [x] `.out` kept for `.wbpz` members via `kept_endings_by_parent_kind` (02 §4, 03 §11); 5 archive-member cases
- [ ] SME has reviewed every entry (`sme_confirmed: true`)
- [x] `config/rules/proposed/` loads with S1's `load_yaml`; names select the intended sanity ranges
- [ ] SME confirmation of the proposed channel maps (then moved to `config/rules/`)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

Verification: `uv run pytest backend/tests/unit/config_data && uv run ruff check backend`

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-23 | S5 | gate.yaml: `.c` no longer junk (Lead: C sources go to Route B); tests pin `.c` accepted, `.o`/`.a`/`.so` and C under site-packages still junk |
| 2026-10-22 | S5 | `units.txt`: National Instruments spellings `Deg C`/`Deg F`/`Deg K` (TDMS unit_string, S1 request) |
| 2026-10-22 | S5 | proposals carry `status: proposed` per rule (S1's final ExportedRule shape) |
| 2026-10-22 | S5 | proposed channel-map rules for E1–E3 in `config/rules/proposed/` (Lead ruling: never applied until confirmed); `test_config_rules.py` |
| 2026-10-22 | S5 | `sanity_ranges.yaml`: one `<quantity>_general` range per quantity (force 0–5,000 N, temperature 0–3,500 K, mass flow 0–5 kg/s, power 0–50 kW, pressure 0–700 bar renamed `pressure_general`), the only ranges that check external facts; Route C bounds unchanged |
| 2026-10-22 | S5 | `sanity_ranges.yaml`: feed/valve/tank 0–400 bar and general 0–700 bar pressure ranges; `checks_external_kept` (only the general range checks external facts); Route C values unchanged (Lead ruling, S2 finding) |
| 2026-10-22 | S5 | `sanity_ranges.yaml` v2 keyed by S1's channel_map quantity + canonical-name glob, first match wins; selection cases on S1-style names |
| 2026-10-21 | S5 | `gate.yaml`: `kept_endings_by_parent_kind: {wbpz: [.out]}` (Lead ruling); 5 archive-member cases; 58 gate tests |
| 2026-10-21 | S5 | `gate.yaml`: `.ini` and `.1` removed per manual (Lead decisions); cases for `report_v1.1` and instrument `.ini` files; 48 gate tests |
| 2026-10-21 | S5 | `config/gate.yaml` from file 02 §4 in S1's GateConfig schema (`.1` kept as a string; `.xlsm` junk only under environment library folders; `* (old)` quarantine); 44 gate tests |
| 2026-10-21 | S5 | Six data files drafted from the manual and public references (all `sme_confirmed: false`); 152 load tests; dev dependencies added |

## Related

- `.wiki/index.md`
- `backend/route-c-telemetry` (sanity ranges, units)
- `backend/enrichment` (synonyms, units, sanity ranges)
- `backend/route-a2-source` (report JSON schemas)
- `backend/answer-engine` (propellants for the physics tool)
