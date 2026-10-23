# Review backend: flags, fingerprints, staged payloads, rules, resume

| Field | Value |
|-------|-------|
| Feature id | `backend/review-backend` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/06_review_flags_and_halt_policy.md; 05 §4.5 |
| Last updated | 2026-10-23 |

## Purpose

Flag models with deterministic fingerprints and case keys, staged payloads for halted documents, the rules table with one precedence resolver, resume_from_staged with overlays, audit events.

## Location

Code:
- `backend/review/api_models.py` (published: queue, case detail, resolutions, rules, dry-run models)
- `backend/api/review.py` (routes of file 08 §4.4, reviewer role; every route of file 08 §4.4 live, including dry-run (set_unit stats converted to SI against the sanity range), undo (last resolution within 30 days; file rules retired; committed documents rebuilt; junked locations restored) and simulate)
- `backend/review/cases.py` (case grouping and derived status, queue filters and impact/age/severity sort, detail with locations and siblings, `resolve_case` (operator rule: the request's or a file-scoped channel_map from `set_unit`), `reject_case` (QUARANTINED, mark_junk quarantines locations), `assign_case`, `create_rule`/`deactivate_rule`, audit rows)
- `backend/review/flags.py` (`upsert_location_flag`, `upsert_document_flag`: by fingerprint, status and resolution kept)
- `backend/review/models.py` (planned)
- `backend/review/rules.py` (published: `resolve()` precedence resolver, `resolve_where()` (resolver over the rules a predicate keeps, e.g. those naming one channel), `RuleScope`, `RuleTarget`, `RuleRecord`, bodies per rule_type, YAML export for `config/rules/`)
- `backend/review/staged.py` (validation gate: `apply_severity_policy` with `flags.severity_overrides` and `flags.strict_mode`, `gate()` upserts flags, closes stale route flags as AUTO_RESOLVED, halts on HARD with `dcl-cir/{sha}/staged.json`, returns the policy-applied document; `load_staged()`)
- `backend/review/resume.py` (planned)
- Flag fingerprints live on `Flag` in `backend/dispatcher/contract.py` (no separate fingerprints module)

Tests and fixtures:
- `backend/tests/unit/review/test_api_models.py`, `backend/tests/unit/review/test_rules.py`, `backend/tests/unit/review/test_cases.py` (DB, `conftest.py` reuses the sync fixtures)
- `backend/tests/integration/review/`

## Interfaces

Provides:
- review API models (`backend.review.api_models`): `CaseFilters`, `CaseList`/`CaseSummary` (rows of `v_review_cases`), `CaseDetail`, `CaseLocation` (folder id, file name, extension for the scope selector), `FlagView` (typed evidence/suggestion/resolution, `allowed_actions`), `allowed_actions_for()`, `check_actions()`; the action models live in `backend/dispatcher/contract.py`, `ResolveRequest/Response`, `RejectRequest`, `UndoResponse`, `DryRunRequest/Response`, `RuleDraft`, `RuleView`, `RuleSimulation`
- routes: `/review/cases[/{case_key}[/assign|resolve|reject|undo]]`, `/review/dry-run`, `/review/rules[/{id}/simulate|deactivate]`; reviewer role for all, including rule deactivation (Lead ruling 2026-10-21)
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
- `backend/review/staged.py`
- `backend/review/api_models.py`
- `backend/api/review.py`
- `backend/review/cases.py`
- `backend/review/entities.py`
- `backend/api/entities.py`
- `backend/tests/unit/review/`
- `backend/tests/integration/review/`

## Rubric (what "done" means for this feature)

- [ ] Re-indexing a document does not duplicate or reopen its flags
- [ ] A folder-wide unit rule resumes every halted sibling
- [x] Undo re-opens the flag and removes the overlay on rebuild (`test_cases.py`: rule retired, junk restored, rebuild started)
- [x] Every human action writes audit_events (assign, resolve, reject, rule create/deactivate; `test_cases.py`)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-24 | Lead | Rules propose, people approve. New `backend/review/proposals.py` (`refresh`: the one place a flag's suggestion is derived from the active `channel_proposal` rules, closest scope wins, else the pipeline's own hint); `create_rule` stores a unit rule as a proposal and `POST /rules` refuses `channel_map`; `resolve_case` always writes the file's own `channel_map` approval and, with `rule_scope`, also a proposal that fills the other files (they stay open); `deactivate_rule` restores hints; `rule_view` counts proposed/decided/waiting and the folder path. New: `POST /cases/{key}/edit` (unit decisions, supersedes the approval, rebuilds, reason + actor audited), `POST /cases/{key}/reopen` (any flag type and age, narrows or switches off the approval so a reopened channel is asked again, switches off a still-active legacy rule), `CaseDetail.applied_units` (units a rule applied to `AUTO_RESOLVED` flags), filters `proposed_by_rule_id`, `q`, `decided`. Route C calls `refresh` after the gate. Tests: `test_cases.py` (27), `test_pipeline.py` |
| 2026-10-23 | Lead | Rules made real: `create_rule` stores a `unit_mapping` as the `channel_map` the pipeline reads (it was stored and never applied, so a folder-scoped unit decision resumed nothing). New: `POST /review/rules/preview` (what a rule would touch, the columns its files wait on, `applied`, `problem`; nothing saved), `GET /review/folders` (folder search; with no query the folders holding halted telemetry files, most first), `POST /review/rules` returns `RuleCreated` with `resumed_documents` and resumes only when files wait, `ResolveRequest.rule_scope` (a case's unit decisions become one channel_map for the chosen scope). `APPLIED_RULE_TYPES` names what is read. Tests in `test_cases.py` |
| 2026-10-23 | Lead | `ConflictEvidence` gains `relation` (`sources_disagree` default, `check_failed`, `note`; a note has no `b`). Tagged: assembler and A2 notes; t0 alignment, formula errors and diagram graph checks as `check_failed`; Route F's weak video ignition is now a CONFLICT `check_failed` (file 03 §C.6) instead of an empty LOW_CONFIDENCE_EXTRACTION. Migration 0014 tags old rows (`test_conflict_relation.py`); OpenAPI types regenerated |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | Published review API models and the review route signatures (501 until M2); 25 tests |
| 2026-10-21 | S1 | FlagView typed evidence + allowed_actions; CaseLocation scope values; rule body interim shape |
| 2026-10-21 | S1 | Rules precedence resolver, typed rule bodies, YAML export format (publish-first item 4); 19 tests |
| 2026-10-22 | S1 | Validation gate and staged payload (`staged.py`); `resolve_where` |
| 2026-10-22 | S1 | `ExportedRule.status` (operator / proposed, default proposed), `load_rules_dir` (top level only, operator rules only); `ChannelMapEntry.open_threshold`; quantities typed |
| 2026-10-22 | S1 | Review API live: queue, detail, resolve with operator rules and resume_for_rule, reject, assign, rules; 13 DB tests |
| 2026-10-23 | S1 | Review dry run, undo and simulate (no 501 left); `task_for_route()` in the adapter table for rebuilds |
| 2026-10-23 | S1 | Entity curation (item 10): `GET /entities`, `POST /entities/merge`, `POST /entities/split` in `backend/api/entities.py` over `backend/review/entities.py` (aliases, mentions, documents.entity_ids, audit); route tolerance for unknown flag routes |

## Related

- `.wiki/index.md`
