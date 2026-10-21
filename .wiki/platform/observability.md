# OpenTelemetry, metrics, dashboards, alerts

| Field | Value |
|-------|-------|
| Feature id | `platform/observability` |
| Status | in-progress |
| Owner session | S4 |
| Spec | docs/architecture/01 §5.7; 02 §10; 06 §9 (decision H6) |
| Last updated | 2026-10-22 |

## Purpose

Traces across FastAPI/Celery/engine, Prometheus metrics of file 02 §10, Grafana dashboards, operational alerts to the Teams webhook only.

## Location

Code:
- `backend/common/telemetry.py` (setup, FastAPI/Celery/httpx instrumentation, `METRICS`, queue depth gauge)
- `backend/main.py`, `backend/celery_redis/app.py` (setup per process), `backend/llm_engine/gemini_client.py` (LLM metrics)
- `backend/devops/otel/collector.yaml`, `backend/devops/tempo/tempo.yaml`
- `backend/devops/prometheus/prometheus.yml`, `alerts.yml`, `alerts_test.yml`
- `backend/devops/alertmanager/alertmanager.yml`
- `backend/devops/grafana/provisioning/`, `backend/devops/grafana/dashboards/dcl-operations.json`

Tests and fixtures:
- `backend/tests/unit/common/test_telemetry.py`
- `backend/tests/unit/devops/test_alert_rules.py` (promtool check + rule unit tests through Docker)

## Interfaces

Provides:
- `METRICS.<name>.add/.set(value, attributes)` for: `graph_requests_total{status}`, `graph_pause_seconds_total`, `delta_pages_total{root}`, `items_gated_total{decision}`, `downloads_total{result}`, `download_bytes_total`, `blob_dedup_hits_total`, `sync_resync_started_total{root}`, `sync_auth_ok{root}`, `sync_root_reachable{root}`, `webhook_last_notification_timestamp_seconds{root}`; LLM metrics are recorded by the gateway client; `celery_queue_depth{queue}` by the api role
- Alerts: DclGraphAuthFailure, DclGraphRootUnreachable, DclResyncStarted, DclDownloadFailureRate, DclWebhookSilence, DclQueueStall (io_light > 2,000 for 30 min), DclGeminiBudgetCap
- Grafana "DCL operations" dashboard; Tempo traces

Consumes:
- S1 sync code calling `METRICS` (graph client, gate, downloader, token health, webhook receiver, resync)
- `DCL_ALERT_WEBHOOK_URL`; `DCL_GRAFANA_ADMIN_PASSWORD` (name pending Lead approval)

## Workspace (files to touch when modifying this feature)

- `backend/common/telemetry.py`
- `backend/devops/otel/`, `backend/devops/tempo/`, `backend/devops/prometheus/`, `backend/devops/alertmanager/`, `backend/devops/grafana/`
- `backend/tests/unit/common/test_telemetry.py`, `backend/tests/unit/devops/test_alert_rules.py`

## Rubric (what "done" means for this feature)

- [x] Auth failure, 410 resync, queue stall and budget cap raise alerts (promtool tests, incl. counters first seen above zero)
- [x] Live (test project, 2026-10-22): span and child span in Tempo, metrics with final names in Prometheus, auth alert pending, dashboard provisioned, an alert routed to the Teams receiver
- [ ] S1's sync code emits the 02 §10 metrics (handoff sent)
- [ ] A trace links Open WebUI message id to engine steps and tool calls (S2/S3, M8–M9)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S4 | OTel setup and metric catalogue, collector, Prometheus + alert rules with promtool tests, Alertmanager → Teams, Tempo, Grafana dashboard; verified live in a test project |

## Related

- `platform/compose-stack`, `platform/gemini-gateway-client`, `backend/sync-engine`
- `.wiki/index.md`
