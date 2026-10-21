# OpenTelemetry, metrics, dashboards, alerts

| Field | Value |
|-------|-------|
| Feature id | `platform/observability` |
| Status | planned |
| Owner session | S4 |
| Spec | docs/architecture/01 §5.7; 02 §10 |
| Last updated | 2026-10-21 |

## Purpose

Traces across FastAPI/Celery/engine, Prometheus metrics of file 02 §10, Grafana dashboards, operational alerts to the Teams webhook only.

## Location

Code:
- `services/common/telemetry/`
- `deploy/grafana/dashboards/`

Tests and fixtures:
- (none yet)

## Interfaces

Provides:
- dashboards and alert rules

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/common/telemetry/`
- `deploy/grafana/dashboards/`

## Rubric (what "done" means for this feature)

- [ ] Auth failure, 410 resync, queue stall and budget cap raise alerts
- [ ] A trace links Open WebUI message id to engine steps and tool calls
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
