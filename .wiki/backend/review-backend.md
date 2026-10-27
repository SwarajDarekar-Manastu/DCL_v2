# Review backend: flags, fingerprints, staged payloads, rules, resume

| Field | Value |
|-------|-------|
| Feature id | `backend/review-backend` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/06_review_flags_and_halt_policy.md (principle 5, §8); 05 §4.5 |
| Last updated | 2026-10-24 |

## Purpose

Flag models with deterministic fingerprints and case keys, staged payloads for halted documents, the rules table with one precedence resolver, rules that act (answer flags like a person, option A), resume_from_staged with overlays, audit events.

## Location

Code:
- `backend/review/api_models.py` (published: queue, case detail, resolutions, rules, dry-run models)
- `backend/api/review.py` (routes of file 08 §4.4, reviewer role; every route of file 08 §4.4 live, including dry-run (set_unit stats converted to SI against the sanity range), undo (last resolution within 30 days; file rules retired; committed documents rebuilt; junked locations restored) and simulate)
- `backend/review/cases.py` (case grouping and derived status, queue filters and impact/age/severity sort, detail with locations and siblings, `resolve_case` (operator rule: the request's or a file-scoped channel_map from `set_unit`), skip and junk inside `resolve_case` by `flag_subject` (a file flag: `_take_file_out`, QUARANTINED, mark_junk quarantines locations; a page or object flag: a resolution the junk overlay drops; any other decision on a committed file: `_rebuild_committed`), `_resumable` (the document id `resolve_case` returns as `resume_doc_id` when its document is HALTED, not Route C, and no HARD flag is left open), `dry_run` (the channel name is the resolution's `canonical_name`, else `_slug(channel)`, as Apply uses, so the preview checks the same sanity range), `assign_case`, `create_rule`/`deactivate_rule`, `apply_rule` (a saved acting rule answers the open flags of the files it matches, or queues the files a document rule changes; returns a `RuleEffect`), `switch_off_rule` (deactivates, reopens the flags the rule answered, lets another active rule answer them, returns a `RuleEffect`), `RuleEffect` (`resolved_flags`, `reopened_flags`, `rebuild` = committed files now PROCESSING, `resume` = HALTED files with no open HARD flag left), `preview_rule`, audit rows)
- `backend/review/flags.py` (`upsert_location_flag`, `upsert_document_flag`: by fingerprint, status and resolution kept)
- `backend/review/models.py` (planned)
- `backend/review/rules.py` (published: `resolve()` precedence resolver, `resolve_where()` (resolver over the rules a predicate keeps, e.g. those naming one channel), `RuleScope`, `RuleTarget`, `RuleRecord`, bodies per rule_type, YAML export for `config/rules/`)
- `backend/review/rule_answers.py` (rules that act, user 2026-10-24: `load_acting`, `answer`, `best_answer`, `answer_flags(session, document, flags)` resolves the open flags an active rule answers (`AUTO_RESOLVED`, `resolution_rule_id`, `resolved_by = rule`); `ANSWERING` = `source_choice`, `schema_mapping`, `column_unit`, `ignore_pattern`, the first type that speaks to a flag wins and within a type `rules.resolve` picks by scope; `ANSWERABLE` = OPEN and IN_PROGRESS, so a REOPENED flag waits for a person; `document_rules` (`origin_override` sets origin and trust tier, `supersession` marks its document superseded); `json_key_mapping` for Route A2)
- `backend/review/proposals.py` (`refresh`, `target_of`: a flag's suggestion from the active `channel_proposal` rules; a model proposal `proposed_by = llm` is the pipeline's own hint and is kept)
- `backend/review/staged.py` (validation gate: `apply_severity_policy` with `flags.severity_overrides` and `flags.strict_mode`, `gate()` upserts flags, closes stale route flags as AUTO_RESOLVED, halts only on an open HARD flag with `dcl-cir/{sha}/staged.json` (a HARD flag a person decided is dropped from the returned document; one the pipeline closed as AUTO_RESOLVED and the route raises again is reopened), runs `answer_flags` on the flags it upserted before it decides, returns the policy-applied document; `load_staged()`)
- `backend/review/resume.py` (planned)
- Flag fingerprints live on `Flag` in `backend/dispatcher/contract.py` (no separate fingerprints module)
- `backend/postgres/migrations/versions/0019_acting_rule_types.py` (`rules.rule_type` CHECK gains `column_unit`, `source_choice`; `RuleType.COLUMN_UNIT`, `RuleType.SOURCE_CHOICE`)

Tests and fixtures:
- `backend/tests/unit/review/test_api_models.py`, `backend/tests/unit/review/test_rules.py`, `backend/tests/unit/review/test_cases.py` (DB, `conftest.py` reuses the sync fixtures)
- `backend/tests/unit/dispatcher/test_acting_rules.py` (DB + MinIO: a rule resolves the same finding on a second file, saving a rule resolves processed files and switching it off takes it back, a reopened flag waits for a person, `source_choice`, `origin_override`)
- `backend/tests/integration/review/`

## Interfaces

Provides:
- review API models (`backend.review.api_models`): `CaseFilters`, `CaseList`/`CaseSummary` (rows of `v_review_cases`), `CaseDetail`, `CaseLocation` (folder id, file name, extension for the scope selector), `FlagView` (typed evidence/suggestion/resolution, `allowed_actions`), `allowed_actions_for()`, `check_actions()`; the action models live in `backend/dispatcher/contract.py`, `ResolveRequest/Response`, `RejectRequest`, `UndoResponse`, `DryRunRequest/Response`, `RuleDraft`, `RuleView`, `RuleSimulation`
- routes: `/review/cases[/{case_key}[/assign|resolve|reject|undo]]`, `/review/dry-run`, `/review/rules[/{id}/simulate|deactivate]`, `/review/rules/preview`; reviewer role for all, including rule deactivation (Lead ruling 2026-10-21)
- rules resolver: `resolve(rules, RuleTarget, rule_type)`; order = scope specificity (nearer folder > ancestor > none; then filename glob; then extension; then root), then operator over derived, then precedence, then newest
- rule bodies: `ChannelMapBody` (`channels: {raw → ChannelMapEntry{canonical_name, physical_quantity, unit, gauge_or_abs, scaling{slope, offset} | expression, sensor_tag, range_min/max}}`, ambient), `UnitMappingBody`, `SchemaMappingBody` (`columns` or `key_to_section`, exactly one), `SupersessionBody`, `IgnorePatternBody` (`reason`, `flag_type`, `relation`, `subject_contains`; without `flag_type` it answers nothing), `ColumnUnitBody` (`column` glob, `unit` or null = keep as text), `SourceChoiceBody` (`subject`, `prefer` = the label of the winning side), `OriginOverrideBody`; `RuleDraft.body` validated by type
- `config/rules/*.yaml` format: `{version: 1, rules: [{rule_type, scope, precedence, body, created_by}]}`, operator rules only (`export_yaml` / `load_yaml`)
- resume tasks: Route C `dcl.process.resume_route_c` (through its approval rule); every other route `dcl.process.resume_staged` (cpu_parse, `backend/celery_redis/tasks_process.py`) running `runner.resume_staged` in `backend/dispatcher/runner.py` (file 06 §7: HALTED document, staged payload, gate again, index, commit; an open HARD flag keeps it HALTED). `POST /review/cases/{key}/resolve` starts it (`start_resume_staged` in `backend/api/review.py`, best effort) when the case's document has no open HARD flag left and `ResolveResponse.resumed_doc_ids` lists it
- rules that act (option A): telemetry channel units keep "a rule proposes, a person approves" (`channel_proposal`, `channel_map`; `POST /rules` refuses `channel_map`); every other kind answers like a person. A flag is answered in the gate and for the commit's own flags (`answer_flags`), by what each kind speaks to: `source_choice` a two-sided CONFLICT (`sources_disagree`) by subject and side label, resolution `choose_source`; `schema_mapping` SCHEMA_UNKNOWN (`json_schema` evidence with `key_to_section`: `map_json_keys`; `array_schema` with `columns`: `map_columns`); `column_unit` a SOFT UNIT_AMBIGUITY by column or label name: `set_fact_unit` (a HARD telemetry unit flag is never answered by a rule); `ignore_pattern` CONFLICT and CLOUD_RESTRICTED: `ignore`, LOW_CONFIDENCE_EXTRACTION: the model's own suggestion. The commit applies the stored resolution as an overlay (backend/index-commit)
- `POST /review/rules` runs `create_rule`, `propose_rule`, `apply_rule`, then starts the effect (`_start_effect`: `start_rebuild` for committed files, `start_resume_staged` for HALTED ones); `RuleCreated` adds `resolved_flags` and `rebuilt_doc_ids`. `POST /review/rules/{id}/deactivate` runs `switch_off_rule` and starts its effect. `RulePreview.effect` is `proposes` (channel rules), `resolves` (answering kinds), `applies` (origin, supersession) or `stored`; `resolves_flags` counts the open flags of the matched files the body would answer

Consumes:
- index commit (backend/index-commit)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/review/models.py`
- `backend/review/rules.py`
- `backend/review/resume.py`
- `backend/review/staged.py`
- `backend/review/rule_answers.py`
- `backend/review/proposals.py`
- `backend/review/api_models.py`
- `backend/api/review.py`
- `backend/review/cases.py`
- `backend/review/entities.py`
- `backend/api/entities.py`
- `backend/tests/unit/review/`
- `backend/tests/unit/dispatcher/test_acting_rules.py`
- `backend/tests/integration/review/`
- `backend/postgres/migrations/versions/0019_acting_rule_types.py`

## Rubric (what "done" means for this feature)

- [ ] Re-indexing a document does not duplicate or reopen its flags
- [ ] A folder-wide unit rule resumes every halted sibling
- [x] Undo re-opens the flag and removes the overlay on rebuild (`test_cases.py`: rule retired, junk restored, rebuild started)
- [x] Every human action writes audit_events (assign, resolve, reject, rule create/deactivate; `test_cases.py`)
- [ ] A rule saved once answers the matching open flags of processed and halted files and rebuilds or resumes them; switching it off opens them again; a reopened flag is never answered by it (`test_acting_rules.py`; needs the test database)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-24 | Lead | Rules act outside telemetry units (option A, DECISIONS 2026-10-24; manual 06 principle 5 and §8). New `rule_answers.py`: rule types `column_unit` and `source_choice` (migration 0019), `ignore_pattern` names flag type, relation and subject, `schema_mapping` maps JSON keys too; a rule answers a flag the way a person would, in the gate and for the commit's own flags; `origin_override` and `supersession` act on the document at the commit. `cases.apply_rule` / `switch_off_rule` return a `RuleEffect`, the API starts the rebuilds and resumes; preview gains effect `resolves` / `applies` and `resolves_flags`. A reopened flag is not answered again (`ANSWERABLE` leaves out REOPENED). `proposals.refresh` keeps a model proposal. Review overlays are now applied at commit (backend/index-commit), which closes the open item of the row below. Tests `test_acting_rules.py`, `test_cases.py` |
| 2026-10-24 | Lead | Resume for routes other than C: the gate halts only on an open HARD flag, `runner.resume_staged` and `dcl.process.resume_staged` continue from the staged payload, resolve starts it when the last open HARD flag is decided; dry run uses the rule's `canonical_name`. Review overlays are still recorded but not applied (open). Tests `test_cases.py`, `test_runner_flags_and_fields.py` |
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
