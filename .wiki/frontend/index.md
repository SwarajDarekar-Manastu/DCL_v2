# Frontend (DCL Console, Open WebUI)

| Feature | Status | Owner | Purpose |
|---------|--------|-------|---------|
| [Console shell, Entra ID login, roles, websocket](console-shell-auth.md) | in-progress | S3 | SvelteKit app shell with OIDC login, role mapping, navigation, websocket channel for live updates. |
| [Review UI (queue, case view, resolution consoles, rules, audit)](review-ui.md) | in-progress | S3 | Impact-sorted queue, polymorphic evidence and resolution panes per flag type, dry-run preview, rules page with simulation, audit page, undo. |
| [Shared document viewer with anchor resolution and translate toggle](viewer.md) | in-progress | S3 | Renders page images with bbox overlays, tables, code, photos, plots, diagram renders and video with seeking; resolves stable anchors with page fallback; translate toggle. |
| [Settings UI (sources, scopes, gate, routes, models, translation, flags, prompts)](settings-ui.md) | in-progress | S3 | Configuration screens over pipeline_config with validation, impact counts, cost estimates for scope widening, history and rollback. |
| [Benchmark UI (suites, cases, runs, results, drilldown, compare, retrieval lab)](benchmark-ui.md) | in-progress | S3 | Golden-suite management and regression dashboards with failure classes and trace drilldowns; draft approval from chat. |
| [Open WebUI Pipe (engine model, event mapping)](openwebui-pipe.md) | in-progress | S3 | The Pipe function that exposes the Answer Engine as a model, maps engine SSE events to status/source/embeds/confirmation, with Valves and UserValves. |
| [Open WebUI Actions, Filter and Skills publication](openwebui-actions-skills.md) | in-progress | S3 | Actions 'Show trace', 'Add to benchmark', 'Report issue'; Filter attaching user policy; publishing playbooks as Skills; the single gateway connection for plain Gemini chat. |
