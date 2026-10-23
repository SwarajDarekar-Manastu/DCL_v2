# Settings UI (sources, scopes, gate, routes, models, translation, flags, prompts)

| Field | Value |
|-------|-------|
| Feature id | `frontend/settings-ui` |
| Status | in-progress (editing, preview, apply, history and rollback live over S1's API; cost estimates wait for S1's price ledger; Prompts section has no keys yet) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §3.2 |
| Last updated | 2026-10-22 |

## Purpose

Configuration screens over pipeline_config with validation, impact counts, cost estimates for scope widening, history and rollback.

## Location

Code:
- `frontend/console/src/routes/settings/` (`+layout.svelte` admin gate and menu, `+page.ts` redirect to the first section, `[section]/` page and 404 for unknown sections)
- `frontend/console/src/lib/components/settings/` (`sections.ts` registry: id, title, `pipeline_config` key patterns (`exact`, `family.*`, `routes.<X>.enabled`), apply semantics per section of 08 §3.2; `SectionMenu.svelte` (sections + Users); `settings_form.ts` (key matching, typed drafts, parsing, value comparison); `SettingsEditor.svelte` (keys with typed editors, one batch: preview → apply with reason; 422 per key, 409 reloads); `KeyHistory.svelte` (versions, restore → rollback); `SectionHistory.svelte` ("rollback to version" for a whole section: every write newest first, restore to a moment = one rollback of each key's version from then where it differs; keys created later are kept and named); `UsersAdmin.svelte` (see console-shell-auth))
- `backend/api/settings.py` (S1 owns the router; the Console calls it only through `api_endpoint.ts`)

Tests and fixtures:
- `frontend/console/tests/settings/`

## Interfaces

Provides:
- Console pages `/settings/{section}` and `/settings/users`

Consumes:
- S1's `/settings` API (`backend/api/settings.py`): `GET /settings?prefix`, `GET /settings/{key}/history`, `POST /settings/preview` (impacts: summary, counts, bytes, by_extension, estimated_cost_usd, cost_note), `PUT /settings` (`changes[{key, value, expected_version}]`, `description`; 422 `{"detail":{"errors":{key: reason}}}`, 409 on a stale version), `POST /settings/rollback` (`versions{key: version}`); each write is versioned and audited by S1
- `api_endpoint.ts`: `listSettings`, `settingHistory`, `previewSettings`, `applySettings`, `rollbackSettings`; `ApiError.errors` carries 422 reasons per key

Editor rules: a section shows every stored key matching its patterns plus exact keys not set yet (sent with `expected_version` 0); the editor kind follows the stored value (switch, number, text, one value per line for string lists, JSON otherwise); malformed input is refused before sending; Apply is enabled only after a Preview of the same edits.

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/console/src/routes/settings/`
- `frontend/console/src/lib/components/settings/`
- `frontend/console/src/lib/api_endpoint.ts` (settings section, when S1 publishes the API)
- `frontend/console/tests/settings/`

## Rubric (what "done" means for this feature)

- [x] Widening the processing scope shows counts, bytes and extensions before applying (live preview of `processing.scope` = [] on the stack: 3,429 files, 17.8 GB)
- [ ] … and an estimated Gemini cost (S1 returns `estimated_cost_usd` = null until the llm_calls price ledger exists; the UI shows it when present)
- [x] Every change is audited and reversible (live on the stack: `gate.junk_names` edited to v2, restored as v3 from the history; `audit_events` rows `update` and `rollback`)
- [x] Every section of 08 §3.2 has a route in the manual's order; non-admins see the role notice
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | S3 | Re-embed warning: an embedding-model preview with `counts.reembed_nodes` > 0 shows S1's summary and Apply waits for an explicit acknowledgement |
| 2026-10-23 | S3 | Sources over S1's /sync routes: roots table (sign-in, webhook or poll, crawl/delta, counts, recent errors), device-code sign-in with the code shown and polled, process everything with its preview first (`SourcesPanel.svelte`); Routes: re-process by route with the count first (`RedispatchPanel.svelte`) |
| 2026-10-23 | S3 | Settings › Prompts over S2's prompt registry (`/v1/prompts`): versions with in-use/latest markers, system and user template, side-by-side diff, run on sample (text, model, tokens, latency); read-only (`PromptsPanel.svelte`, `prompts.ts`) |
| 2026-10-23 | S3 | Section rollback to a point in time (file 08 §3.2) |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S3 | Scaffolding: admin-gated layout, section registry and routes, tests |
| 2026-10-22 | S3 | Editing over S1's /settings API: typed editors, preview with impacts, apply with reason and expected versions, 422/409 handling, history and restore; Users page |

## Related

- `.wiki/index.md`
- `backend/schema-and-migrations` (S1; provides the /settings API over pipeline_config)
