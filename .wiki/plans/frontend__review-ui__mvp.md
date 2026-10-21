# Plan: frontend/review-ui — Review UI MVP (M3)

| Field | Value |
|-------|-------|
| Feature | `frontend/review-ui` (map: `.wiki/frontend/review-ui.md`) |
| Session | S3 |
| Branch | claude/cranky-rhodes-0cb23f |
| Opened | 2026-10-21 |
| Delete when | rubric below is green and the map page is updated |

## Intent

Build the Review UI of file 08 §4 against S1's review API (`backend/review/api_models.py`, `backend/api/review.py`, S1 commit 9fda653, merge pending): impact-sorted queue with the §6 §9 filters and keyboard navigation; case view with header, evidence pane and the resolution consoles for `UNIT_AMBIGUITY`, `SCHEMA_UNKNOWN`, `CONFLICT`, `PARSE_FAILURE`; dry-run preview; scope selector that turns a resolution into a rule; assign, reject, undo; rules page with scope editor, simulation and deactivation; live case updates. TypeScript types are generated from the backend's OpenAPI schema, not hand-written. The routes answer 501 until S1's M2 tables exist, so the UI is verified against a mock API built from the same schema. `backend/api/review.py` stays S1's.

## Workspace

Files to read:
- docs/architecture/08_frontend_openwebui.md §4; 06 §3, §5, §6, §8, §9; S1 `backend/review/api_models.py`

Files to change (exact):
- `frontend/console/package.json`, `package-lock.json` (openapi-typescript, `gen:api`)
- `frontend/console/scripts/export_openapi.py`
- `frontend/console/src/lib/api_schema.d.ts` (generated)
- `frontend/console/src/lib/api_endpoint.ts` (types from the schema; review calls)
- `frontend/console/src/lib/components/review/`
- `frontend/console/src/lib/live.svelte.ts` (shared live state, so the layout's one websocket feeds the queue) and `frontend/console/src/routes/+layout.svelte` (uses it)
- `frontend/console/src/routes/review/` (`+page.svelte` queue and case side by side, case chosen by `?case=<case_key>`; `rules/+page.svelte`)
- `frontend/console/tests/review/`, `frontend/console/tests/api_endpoint.test.ts`

Files explicitly out of scope (owned by another session → message them):
- `backend/api/review.py`, `backend/review/*` (S1); audit route (asked S1 2026-10-21); evidence shapes per flag type (asked S1)

## Steps

1. Generator + `api_endpoint.ts` on generated types; review calls with tests.
2. Queue: list, filters, impact sort, cursor paging, `j`/`k`/`enter`, live `case` events, counts.
3. Case view: header (breadcrumb, OneDrive, status, age, assignee, undo), evidence (generic + typed when known), consoles per flag type driven by `ALLOWED_ACTIONS`, scope → rule draft, dry-run, apply, reject.
4. Rules page: list, create with scope editor, simulate, deactivate (admin).
5. Mock API from the schema; browser check of queue → case → dry-run → resolve.

## Rubric for this task

- [ ] (map) A folder-wide unit case resolves in one action: the console sends one `resolve` with a folder-scoped `unit_mapping` rule; siblings resuming within 2 min needs S1 and stays open
- [ ] (map) Undo works and is audited: undo control calls the API and refreshes; audit side is S1's
- [ ] (task) Types come from the generated schema; no hand-written copy of a backend model in `api_endpoint.ts`
- [ ] (task) Each console offers exactly the actions `ALLOWED_ACTIONS` allows for its flag type (test per type)
- [ ] (task) Apply is disabled until the resolution validates; dry-run shows converted stats against sanity bounds
- [ ] (task) Case links carry `case_key` percent-encoded, never node ids
- [ ] Verification commands below pass

## Verification commands

```bash
cd frontend/console && npm run gen:api && git diff --exit-code src/lib/api_schema.d.ts && npm run check && npm test && npm run build
grep -rnE "fetch\(|new WebSocket" frontend/console/src | grep -v src/lib/api_endpoint.ts   # prints nothing
```

## Risks and open questions

- S1's merge is pending; regenerate after it lands. Evidence shapes and the audit route are open questions to S1.
