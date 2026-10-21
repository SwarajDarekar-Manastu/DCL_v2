# S3 — Full-stack (DCL Console, Open WebUI integration, viewer)

**Mission:** the human surfaces: the DCL Console (Review UI first, then Settings, Benchmark UI, Entities, Audit, Ops), the shared document viewer with anchor resolution and page fallback, and the Open WebUI integration (Pipe, Actions, Filter, Skills publication).

## Read first

`docs/architecture/08_frontend_openwebui.md` (all), `06_review_flags_and_halt_policy.md` (§5, §6, §9), `07_phase3_answer_engine.md` (§7, §8, §11), `05_storage_schema.md` (§4.5, §4.7, §5 views), `04_metadata_enrichment_chunking_embedding.md` §4.4 (anchors) and §10 (translation).

## You own

`frontend/console` (SvelteKit + TypeScript), `backend/api/` (FastAPI), `frontend/openwebui` (Pipe, Actions, Filter, Skills markdown).

## Publish first

1. Console API route list with request/response models for review cases, rules, dry-run, assets presign, viewer, entities, ops, settings and benchmarks (file 08 §4.4, §5), built on S1's `api_models.py`.
2. The viewer route `/docs/{id}/viewer?anchor=…` contract (what it renders per node type, translate toggle, fallback behavior) so S2 can emit citation URLs.
3. The Open WebUI Pipe skeleton with the event mapping table (engine `step`/`citation`/`embed`/`needs_confirmation` → Open WebUI `status`/`source`/`embeds`/`confirmation`) against S2's `/v1/answer` schema.

## Depends on

S1: review API models and endpoints, views `v_review_cases`, `v_doc_locations`. S2: engine SSE schema, anchors resolver, retrieval lab endpoint. S4: SSO configuration (Entra ID), presign service, compose entries for the Console. S5: benchmark case schema fixtures.

## Milestones

M3 Review UI MVP (primary), M5 handwriting and table panes (supporting), M9 Open WebUI (primary), M10 Benchmark UI (primary), Settings UI alongside each milestone that introduces config keys.

## First tasks

1. Console shell: Entra ID OIDC login, role mapping (`viewer`, `reviewer`, `admin`), layout, websocket channel.
2. Review UI MVP: queue (impact sort, filters), case view with evidence and resolution panes for `UNIT_AMBIGUITY`, `SCHEMA_UNKNOWN`, `CONFLICT`, `PARSE_FAILURE`; dry-run preview; rules page with scope editor and simulation; audit page; undo.
3. Viewer: page render with bbox overlays from assets, anchor resolution with page fallback, OneDrive and download links, translate toggle placeholder.
4. Settings: Sources (scopes with live counts, "process everything" with cost estimate), Gate, Routes (enabled switches with parked counts), Models, Translation, Flags; every change audited with rollback.
5. Open WebUI: Pipe with Valves/UserValves and the event mapping; Actions "Show trace", "Add to benchmark", "Report issue"; Filter for user policy; publish S2's playbooks as Skills; the single gateway connection for plain Gemini chat.
6. Benchmark UI: suites/cases/runs/results/drilldown/compare/retrieval lab; draft approval flow.

## Definition of done

Wiki: map page updated and plan sheet deleted (see below). Then:

Component tests; an end-to-end test that resolves a unit case and sees the siblings resume; citation links open the right page after a forced re-index; Pipe integration test against a recorded engine stream; status entry; merge request.

## Wiki duty (applies to every task)

Read `.wiki/index.md` and your feature's map page first. Open a plan sheet (`.wiki/_templates/plan-sheet.md`) with the exact workspace and rubric; work only inside it; when done, update the map page (status, location, interfaces, workspace, change log), update the area index, delete the plan sheet. Your map pages are listed in `.wiki/<area>/index.md` under your session id.

## When in doubt or blocked

Write the question or the blocker to `docs/sessions/STATUS.md`, message `DCL Lead` (or the session you wait on) once, and end your turn. Never improvise around the manual and never keep working "on the side" while waiting.

## Coordination rules

- The Console never talks to MinIO directly; it asks the Console API for presigned URLs.
- Never store node ids in links or state; anchors only.
- Open WebUI is not forked; if something seems to need a fork, message `DCL Lead` first.
