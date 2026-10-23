# Frontend (DCL Console, Open WebUI)

| Feature | Status | Owner | Purpose |
|---------|--------|-------|---------|
| [Console shell, sign-in (local accounts; Entra ID later), roles, websocket](console-shell-auth.md) | in-progress | S3 | SvelteKit app shell with local password sign-in (Entra ID later), role mapping, navigation, websocket channel for live updates. |
| [Review UI (queue, case view, resolution consoles, rules, audit)](review-ui.md) | in-progress | S3 | Impact-sorted queue, polymorphic evidence and resolution panes per flag type, dry-run preview, rules page with simulation, audit page, undo. |
| [Shared document viewer with anchor resolution and translate toggle](viewer.md) | in-progress | S3 | Renders page images with bbox overlays, tables, code, photos, plots, diagram renders and video with seeking; resolves stable anchors with page fallback; translate toggle. |
| [Settings UI (sources, scopes, gate, routes, models, translation, flags, prompts)](settings-ui.md) | in-progress | S3 | Configuration screens over pipeline_config: typed editors, preview with impact counts, apply, history and rollback; Users page. |
| [Benchmark UI (suites, cases, runs, results, drilldown, compare, retrieval lab)](benchmark-ui.md) | in-progress | S3 | Golden-suite management and regression dashboards with failure classes and trace drilldowns; draft approval from chat. |
| [Open WebUI Pipe (engine model, event mapping)](openwebui-pipe.md) | in-progress | S3 | The Pipe function that exposes the Answer Engine as a model, maps engine SSE events to status/source/embeds/confirmation, with Valves and UserValves. |
| [Open WebUI Actions, Filter and Skills publication](openwebui-actions-skills.md) | in-progress | S3 | Actions 'Show trace', 'Add to benchmark', 'Report issue'; Filter attaching user policy; publishing playbooks as Skills; the single gateway connection for plain Gemini chat. |
| [Ops page (failed tasks; sync, queues and cost to follow)](ops-page.md) | in-progress | S3 | Failed tasks from the Celery dead-letter list; later sync status, queue depths, cost today. |

## Guides

| Page | Purpose |
|------|---------|
| [M9 pilot walk-through](m9-pilot-walkthrough.md) | Steps a pilot engineer runs in Open WebUI and the Console to accept M9 (file 10 §5) |
| [Console against file 08](console-gaps-08.md) | Every function file 08 names that the Console lacks, with status and blockers (build-out tracking) |
