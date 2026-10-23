# Platform (stack, env, gateway client, CI, observability)

| Feature | Status | Owner | Purpose |
|---------|--------|-------|---------|
| [Docker Compose stack with GPU model services](compose-stack.md) | in-progress | S4 | All services of file 01 §6 in compose. |
| [Environment contract loader and .env.example](env-contract.md) | in-progress | S4 | Typed settings from . |
| [Gemini gateway client and capability probe](gemini-gateway-client.md) | in-progress | S4 | The only module that talks to the Manastu Cloud Run gateway: structured output, function calling, thinking level, image/PDF parts, streaming, retry/backoff, budget guard, llm_calls hook, capability flags from a probe. |
| [CI pipeline and gates](ci.md) | in-progress | S4 | Lint, unit tests, alembic upgrade/check on the pinned ParadeDB image, FK-index query, image secret scan, benchmark gate. |
| [OpenTelemetry, metrics, dashboards, alerts](observability.md) | in-progress | S4 | Traces across FastAPI/Celery/engine, Prometheus metrics of file 02 §10, Grafana dashboards, operational alerts to the Teams webhook only. |
| [Public HTTPS for Graph webhooks (Cloudflare Tunnel evaluation)](webhook-tunnel.md) | planned | S4 | Recommendation: keep the 5-minute poll; add a named Cloudflare Tunnel limited to the webhook path once the receiver, a domain and IT approval exist. |
| [Backups, retention jobs, runbooks](backups-retention.md) | deprecated | S4 | PostgreSQL base+WAL, MinIO versioning, nightly retention deletes, runbooks for re-auth, 410 resync, worker OOM, Gemini outage, model-service restart. |
