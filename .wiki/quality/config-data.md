# Domain configuration data (synonyms, vendors, sanity ranges, units, propellants, report schemas, rules)

| Field | Value |
|-------|-------|
| Feature id | `quality/config-data` |
| Status | planned |
| Owner session | S5 |
| Spec | docs/architecture/04 §3.3, §8; 03 §C; 10 §2 |
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
- `config/rules/`

Tests and fixtures:
- `tests/unit/config_data/`

## Interfaces

Provides:
- loaded configuration

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `config/aerospace_synonyms.yaml`
- `config/vendors.yaml`
- `config/sanity_ranges.yaml`
- `config/units.txt`
- `config/propellants.yaml`
- `config/report_json_schemas.yaml`
- `config/rules/`
- `tests/unit/config_data/`

## Rubric (what "done" means for this feature)

- [ ] Every file loads and is covered by a test
- [ ] Synonym seeds include non-English surfaces
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
