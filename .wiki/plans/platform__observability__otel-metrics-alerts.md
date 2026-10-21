# Plan: platform/observability — OTel, metrics of file 02 §10, dashboards, alerts

| Field | Value |
|-------|-------|
| Feature | `platform/observability` (map: `.wiki/platform/observability.md`) |
| Session | S4 |
| Branch | claude/gifted-hofstadter-0bec1c |
| Opened | 2026-10-22 |
| Delete when | rubric below is green and the map page is updated |

## Intent

Every process (API, models, workers, beat) exports OTLP traces and metrics to one collector; Prometheus scrapes the collector and evaluates the operational alert rules of file 02 §10 and 06 §9 (auth failure, root unreachable, 410 resync, download failures > 5 %/h, webhook silence > 36 h, io_light depth > 2,000 for 30 min, budget cap); Alertmanager routes them to `DCL_ALERT_WEBHOOK_URL` (Teams) only; Tempo stores traces; Grafana shows one operations dashboard. `backend/common/telemetry.py` is the one place that names metrics; S1's sync code increments them. The gateway client records LLM calls, tokens, cost and budget stops itself. Without `OTEL_EXPORTER_OTLP_ENDPOINT` nothing is exported (tests, host CLIs).

## Workspace

Files to change (exact):
- `backend/common/telemetry.py`, `backend/main.py` (setup + FastAPI instrumentation; queue depth in the api role), `backend/celery_redis/app.py` (worker/beat init)
- `backend/llm_engine/gemini_client.py` (LLM metrics)
- `backend/devops/compose.yaml`, `backend/devops/compose.dev.yaml`
- `backend/devops/otel/collector.yaml`, `backend/devops/prometheus/prometheus.yml`, `backend/devops/prometheus/alerts.yml`, `backend/devops/alertmanager/alertmanager.yml`, `backend/devops/tempo/tempo.yaml`, `backend/devops/grafana/provisioning/**`, `backend/devops/grafana/dashboards/dcl-operations.json`
- `backend/tests/unit/common/test_telemetry.py`, `backend/tests/unit/devops/test_alert_rules.py`
- `pyproject.toml`, `uv.lock`; `.env.example`; runbook `backend/devops/runbooks/stack.md`
- `.wiki/platform/observability.md`, indexes, `docs/sessions/STATUS.md`

## Rubric for this task

- [ ] Auth failure, 410 resync, queue stall and budget cap raise alerts (promtool rule tests)
- [ ] Live: a request to the API produces a trace in Tempo and metrics in Prometheus; dashboard loads
- [ ] Alertmanager reads the webhook URL from the env at start; it never lands in a committed file
- [ ] `uv run pytest`, ruff, compose config, stack healthy
