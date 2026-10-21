# .wiki — the map of this repository

This folder is the compiled, always-current map of what exists in the repository, where it lives, and what "done" means for it. It follows the LLM-wiki idea: raw sources (the architecture manual and the code) stay immutable in their own places; this wiki is the derived layer that agents and people read **first**, so that changing or re-building a feature never requires traversing the whole repository again. Conventions are in [README.md](README.md).

## Areas

| Area | Index | Owner sessions |
|------|-------|----------------|
| Backend | [backend/index.md](backend/index.md) | S1 (pipeline, data), S2 (ML services, answer engine) |
| Frontend | [frontend/index.md](frontend/index.md) | S3 |
| Platform | [platform/index.md](platform/index.md) | S4 |
| Quality | [quality/index.md](quality/index.md) | S5 |

## All features

| Feature id | Status | Owner | Map |
|------------|--------|-------|-----|
| `backend/sync-engine` | in-progress | S1 | [Graph sync engine (delta, webhooks, resync)](backend/sync-engine.md) |
| `backend/gate-and-scope` | in-progress | S1 | [Junk gate, quarantine, download and processing scopes](backend/gate-and-scope.md) |
| `backend/registry-and-blobs` | in-progress | S1 | [Registry, content-addressed blobs, downloader](backend/registry-and-blobs.md) |
| `backend/schema-and-migrations` | in-progress | S1 | [PostgreSQL schema, enums as CHECK, Alembic](backend/schema-and-migrations.md) |
| `backend/dispatcher-and-route-gating` | in-progress | S1 | [Dispatcher, type resolution, folder context, assembler, route gating](backend/dispatcher-and-route-gating.md) |
| `backend/route-c-telemetry` | planned | S1 | [Route C: telemetry, LabVIEW, spreadsheets, arrays](backend/route-c-telemetry.md) |
| `backend/route-a2-source` | planned | S1 | [Route A2: JSON report sections and LaTeX sources](backend/route-a2-source.md) |
| `backend/route-b-code` | planned | S1 | [Route B: Python scripts and tooling docs](backend/route-b-code.md) |
| `backend/route-e-diagrams` | planned | S1 | [Route E: draw.io diagrams and XSD](backend/route-e-diagrams.md) |
| `backend/route-g-archives` | planned | S1 | [Route G: archives and ANSYS packages](backend/route-g-archives.md) |
| `backend/review-backend` | in-progress | S1 | [Review backend: flags, fingerprints, staged payloads, rules, resume](backend/review-backend.md) |
| `backend/index-commit` | planned | S1 | [Index commit path (transaction, overlays, vector reuse)](backend/index-commit.md) |
| `backend/vision-service` | in-progress | S2 | [VisionService on Gemini (triage, handwriting, tables, plots, photos, video)](backend/vision-service.md) |
| `backend/route-a1-office` | planned | S2 | [Route A1: PDF, DOCX, PPTX, PPT](backend/route-a1-office.md) |
| `backend/route-d-photos` | planned | S2 | [Route D: hardware inspection photos](backend/route-d-photos.md) |
| `backend/route-f-video` | planned | S2 | [Route F: test-cell and workshop videos](backend/route-f-video.md) |
| `backend/enrichment` | planned | S2 | [L2 enrichment, entity normalization, numeric facts](backend/enrichment.md) |
| `backend/chunker-and-anchors` | in-progress | S2 | [Chunker, contextual headers, stable anchors, identifier extraction](backend/chunker-and-anchors.md) |
| `backend/embedding-service` | done | S2 | [Embedding service (EmbeddingGemma 2, text + image, GPU)](backend/embedding-service.md) |
| `backend/reranker-service` | done | S2 | [Reranker service (bge-reranker-v2-m3, GPU)](backend/reranker-service.md) |
| `backend/retrieval` | planned | S2 | [Hybrid retrieval (dense exact/HNSW, BM25 per language, RRF, rerank, parent expansion)](backend/retrieval.md) |
| `backend/answer-engine` | in-progress | S2 | [Answer Engine (workflow, tools, playbooks, sanitizer, verifier, DBOS)](backend/answer-engine.md) |
| `frontend/console-shell-auth` | in-progress | S3 | [Console shell, Entra ID login, roles, websocket](frontend/console-shell-auth.md) |
| `frontend/review-ui` | in-progress | S3 | [Review UI (queue, case view, resolution consoles, rules, audit)](frontend/review-ui.md) |
| `frontend/viewer` | in-progress | S3 | [Shared document viewer with anchor resolution and translate toggle](frontend/viewer.md) |
| `frontend/settings-ui` | in-progress | S3 | [Settings UI (sources, scopes, gate, routes, models, translation, flags, prompts)](frontend/settings-ui.md) |
| `frontend/benchmark-ui` | planned | S3 | [Benchmark UI (suites, cases, runs, results, drilldown, compare, retrieval lab)](frontend/benchmark-ui.md) |
| `frontend/openwebui-pipe` | planned | S3 | [Open WebUI Pipe (engine model, event mapping)](frontend/openwebui-pipe.md) |
| `frontend/openwebui-actions-skills` | planned | S3 | [Open WebUI Actions, Filter and Skills publication](frontend/openwebui-actions-skills.md) |
| `platform/compose-stack` | planned | S4 | [Docker Compose stack with GPU model services](platform/compose-stack.md) |
| `platform/env-contract` | in-progress | S4 | [Environment contract loader and .env.example](platform/env-contract.md) |
| `platform/gemini-gateway-client` | in-progress | S4 | [Gemini gateway client and capability probe](platform/gemini-gateway-client.md) |
| `platform/ci` | planned | S4 | [CI pipeline and gates](platform/ci.md) |
| `platform/observability` | planned | S4 | [OpenTelemetry, metrics, dashboards, alerts](platform/observability.md) |
| `platform/backups-retention` | planned | S4 | [Backups, retention jobs, runbooks](platform/backups-retention.md) |
| `quality/fixtures` | in-progress | S5 | [Fixture corpus and expected outcomes](quality/fixtures.md) |
| `quality/config-data` | in-progress | S5 | [Domain configuration data (synonyms, vendors, sanity ranges, units, propellants, report schemas, rules)](quality/config-data.md) |
| `quality/benchmark-suites` | planned | S5 | [Golden benchmark suites and verification notes](quality/benchmark-suites.md) |
| `quality/acceptance` | planned | S5 | [Milestone acceptance checklists](quality/acceptance.md) |

## Active plan sheets

Temporary, one per task in progress, deleted on completion (see README). Listed here only while they exist on a branch; `main` never contains plan sheets.

| Plan sheet | Feature | Session | Opened |
|------------|---------|---------|--------|

## Maintenance

- Status values: `planned`, `in-progress`, `done`, `deprecated`.
- The Lead runs the wiki lint at every merge round (README §5).
- Last full lint: 2026-10-21 (initial).
