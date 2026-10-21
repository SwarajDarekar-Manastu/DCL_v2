# Review backend: flags, fingerprints, staged payloads, rules, resume

| Field | Value |
|-------|-------|
| Feature id | `backend/review-backend` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/06_review_flags_and_halt_policy.md; 05 §4.5 |
| Last updated | 2026-10-21 |

## Purpose

Flag models with deterministic fingerprints and case keys, staged payloads for halted documents, the rules table with one precedence resolver, resume_from_staged with overlays, audit events.

## Location

Code:
- `backend/review/api_models.py` (published: queue, case detail, resolutions, rules, dry-run models)
- `backend/api/review.py` (routes of file 08 §4.4 with their models and roles; 501 until the M2 tables)
- `backend/review/models.py` (planned)
- `backend/review/rules.py` (published: `resolve()` precedence resolver, `RuleScope`, `RuleTarget`, `RuleRecord`, bodies per rule_type, YAML export for `config/rules/`)
- `backend/review/resume.py` (planned)
- Flag fingerprints live on `Flag` in `backend/dispatcher/contract.py` (no separate fingerprints module)

Tests and fixtures:
- `backend/tests/unit/review/test_api_models.py`, `backend/tests/unit/review/test_rules.py`
- `backend/tests/integration/review/`

## Interfaces

Provides:
- review API models (`backend.review.api_models`): `CaseFilters`, `CaseList`/`CaseSummary` (rows of `v_review_cases`), `CaseDetail`, `CaseLocation` (folder id, file name, extension for the scope selector), `FlagView` (typed evidence/suggestion/resolution, `allowed_actions`), `allowed_actions_for()`, `check_actions()`; the action models live in `backend/dispatcher/contract.py`, `ResolveRequest/Response`, `RejectRequest`, `UndoResponse`, `DryRunRequest/Response`, `RuleDraft`, `RuleView`, `RuleSimulation`
- routes: `/review/cases[/{case_key}[/assign|resolve|reject|undo]]`, `/review/dry-run`, `/review/rules[/{id}/simulate|deactivate]`; reviewer role, deactivate needs admin
- rules resolver: `resolve(rules, RuleTarget, rule_type)`; order = scope specificity (nearer folder > ancestor > none; then filename glob; then extension; then root), then operator over derived, then precedence, then newest
- rule bodies: `ChannelMapBody` (`channels: {raw → ChannelMapEntry{canonical_name, physical_quantity, unit, gauge_or_abs, scaling{slope, offset} | expression, sensor_tag, range_min/max}}`, ambient), `UnitMappingBody`, `SchemaMappingBody`, `SupersessionBody`, `IgnorePatternBody`, `OriginOverrideBody`; `RuleDraft.body` validated by type
- `config/rules/*.yaml` format: `{version: 1, rules: [{rule_type, scope, precedence, body, created_by}]}`, operator rules only (`export_yaml` / `load_yaml`)
- resume task

Consumes:
- index commit (backend/index-commit)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/review/models.py`
- `backend/review/rules.py`
- `backend/review/resume.py`
- `backend/review/api_models.py`
- `backend/api/review.py`
- `backend/tests/unit/review/`
- `backend/tests/integration/review/`

## Rubric (what "done" means for this feature)

- [ ] Re-indexing a document does not duplicate or reopen its flags
- [ ] A folder-wide unit rule resumes every halted sibling
- [ ] Undo re-opens the flag and removes the overlay on rebuild
- [ ] Every human action writes audit_events
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | Published review API models and the review route signatures (501 until M2); 25 tests |
| 2026-10-21 | S1 | FlagView typed evidence + allowed_actions; CaseLocation scope values; rule body interim shape |
| 2026-10-21 | S1 | Rules precedence resolver, typed rule bodies, YAML export format (publish-first item 4); 19 tests |

## Related

- `.wiki/index.md`
