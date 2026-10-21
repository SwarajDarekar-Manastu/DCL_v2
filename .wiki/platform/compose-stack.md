# Docker Compose stack with GPU model services

| Field | Value |
|-------|-------|
| Feature id | `platform/compose-stack` |
| Status | planned |
| Owner session | S4 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §6; 10 §4 |
| Last updated | 2026-10-21 |

## Purpose

All services of file 01 §6 in compose.yaml/compose.dev.yaml: ParadeDB, MinIO, Redis, Celery pools, FastAPI services, embedding and reranker on the GPU, LibreOffice, OTel, Grafana.

## Location

Code:
- `compose.yaml`
- `compose.dev.yaml`
- `deploy/docker/`
- `deploy/grafana/`

Tests and fixtures:
- `tests/integration/stack/`

## Interfaces

Provides:
- healthy stack from a clean checkout

Consumes:
- env contract

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `compose.yaml`
- `compose.dev.yaml`
- `deploy/docker/`
- `deploy/grafana/`
- `tests/integration/stack/`

## Rubric (what "done" means for this feature)

- [ ] docker compose up reaches healthy
- [ ] GPU visible only to the two model services
- [ ] Queue memory limits match file 10 §4
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
