# DCL v2 — Document Context Layer for Manastu propulsion data

An ingestion, processing and answer-engine pipeline over the team's OneDrive: test reports, telemetry, code, photos, diagrams, videos and the external library, answered through Open WebUI with verifiable citations.

| Where to look | What it is |
|---------------|------------|
| [`docs/architecture/`](docs/architecture/00_README.md) | The normative design manual (11 files): phases, routes, schema, review policy, answer engine, frontend, decisions, development plan |
| [`.wiki/`](.wiki/index.md) | The map of the repository: one page per feature with location, interfaces, workspace and rubric; read this before touching code |
| [`docs/sessions/`](docs/sessions/README.md) | How the parallel development sessions (Lead + S1–S5) divide the work and coordinate |

Secrets live only in `.env` on the host (ignored by git); see `docs/architecture/01_system_overview_and_tech_stack.md` §7.1 for the variable contract.

License: MIT.
