# Golden benchmark suites and verification notes

| Field | Value |
|-------|-------|
| Feature id | `quality/benchmark-suites` |
| Status | planned |
| Owner session | S5 |
| Spec | docs/architecture/08_frontend_openwebui.md §5.3, §5.7 |
| Last updated | 2026-10-21 |

## Purpose

The 60-case golden set across categories incl. MULTILINGUAL and LIBRARY_VS_INTERNAL, the 40-query retrieval set with gold anchors, verification scripts, hold-out subset.

## Location

Code:
- `tests/benchmark/suites/`
- `tests/benchmark/retrieval_set.yaml`
- `tests/benchmark/verification/`

Tests and fixtures:
- (none yet)

## Interfaces

Provides:
- suites consumed by the benchmark runner and CI

Consumes:
- anchors (S2)
- benchmark UI (S3)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `tests/benchmark/suites/`
- `tests/benchmark/retrieval_set.yaml`
- `tests/benchmark/verification/`

## Rubric (what "done" means for this feature)

- [ ] Every numeric case has an independent verification note
- [ ] Hold-out subset recorded in DECISIONS.md
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
