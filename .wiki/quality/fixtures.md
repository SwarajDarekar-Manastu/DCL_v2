# Fixture corpus and expected outcomes

| Field | Value |
|-------|-------|
| Feature id | `quality/fixtures` |
| Status | in-progress |
| Owner session | S5 |
| Spec | docs/architecture/10_development_plan.md §7 |
| Last updated | 2026-10-21 |

## Purpose

One real sample per format from the allowlisted folders plus synthetic edge cases, each with an expected-outcome file (route, flags, key numbers).

## Location

Code:
- `backend/tests/fixtures/<route>/<fixture>/` (fixture files + `expected.yaml`); route folders `dispatcher`, `a1_office`, `a2_source`, `b_code`, `c_telemetry`, `d_photos`, `e_diagrams`, `f_video`, `g_archives`
- `backend/tests/fixtures/make_synthetic.py` (generator of every synthetic fixture)
- `backend/tests/fixtures/README.md` (layout, expected.yaml fields, safety rules)

Tests and fixtures:
- `backend/tests/fixtures/test_fixture_integrity.py`

Synthetic fixtures (2026-10-21): `a1_office/{rotated_scan, japanese_scanned_page, german_datasheet, doi_paper}`, `a2_source/two_latex_masters`, `c_telemetry/{headerless_csv, merged_cells_fmea, malicious_pickle, unlabeled_npy}`, `g_archives/{zip_bomb_ratio, zip_path_traversal, zip_nested_depth}`, `dispatcher/pdf_is_html`. Real samples: none yet. Allowlist recorded in docs/sessions/DECISIONS.md (2026-10-22, entries E1–E11, chosen from S1's crawl); real samples come from those folders with user approval.

## Interfaces

Provides:
- fixtures used by every route test; `expected.yaml` per fixture (document-level outcome: route, detected type, status, flags, metadata, numeric facts, `never` actions), with `simulated_location` for folder context
- hostile fixtures (pickle, archives) that pipeline tests must handle without executing or extracting

Consumes:
- CIR snapshot format (S1, not yet published): snapshot comparisons are added when it exists

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/tests/fixtures/README.md`
- `backend/tests/fixtures/make_synthetic.py`
- `backend/tests/fixtures/test_fixture_integrity.py`
- `backend/tests/fixtures/<route>/<fixture>/` (fixture files and `expected.yaml`)
- `pyproject.toml` (dev dependencies only: reportlab, pillow, openpyxl, pypdf)

## Rubric (what "done" means for this feature)

- [x] Every fixture has an expected-outcome file (13 synthetic fixtures)
- [x] Edge-case list of file 10 §7 covered by synthetic fixtures (all ten, plus two extra archive guards)
- [ ] One real sample per format from the allowlisted folders, approved by the user
- [ ] CIR snapshot expectations once S1 publishes the format
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

Verification: `uv run pytest backend/tests/fixtures && uv run ruff check backend`

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S5 | processing.scope allowlist chosen from S1's crawl and recorded by the Lead (DECISIONS.md); .npy slot dropped per ruling |
| 2026-10-22 | S5 | unlabeled_npy synthetic fixture (no accepted corpus .npy exists; all are under _to_delete); numpy cross-check with allow_pickle=False |
| 2026-10-21 | S5 | merged_cells_fmea expects no flag: S/O/D/RPN are on the dimensionless list (03 §C.4 step 8, Lead decision) |
| 2026-10-21 | S5 | Synthetic edge-case fixtures, generator, expected.yaml format, 30 integrity tests |

## Related

- `.wiki/index.md`
- `backend/dispatcher-and-route-gating` (pdf_is_html, pickle sniff)
- `backend/route-a1-office`, `backend/route-a2-source`, `backend/route-c-telemetry`, `backend/route-g-archives`
- `quality/config-data` (synonyms and units the expected numeric facts rely on)
