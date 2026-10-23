# Runbook: the Compose stack

Spec: docs/architecture/01 §6, 10 §3–§4. Map: `.wiki/platform/compose-stack.md`. Run every command from the repository root.

## Start and stop

```bash
docker compose --env-file .env -f backend/devops/compose.yaml -f backend/devops/compose.dev.yaml up -d --build --wait
docker compose -p dcl-v2 ps -a
docker compose -p dcl-v2 down            # keeps volumes
```

- Every `up` first runs two one-shot jobs: `minio-init` (buckets, versioning on dcl-raw and dcl-cir, lifecycle, the application user) and `migrate` (`alembic upgrade head`). Both are idempotent and must show `Exited (0)`.
- Host ports on `DCL_DATA_BIND_HOST` (default 127.0.0.1, keep it there): PostgreSQL `DCL_DB_PORT` (5435 on the dev host), Redis 6381, MinIO API 9100.
- Host ports on `DCL_BIND_HOST` (0.0.0.0 for LAN access): MinIO console `DCL_MINIO_CONSOLE_PORT` (9101), models 8500, API 8200, Grafana `DCL_GRAFANA_PORT` (3300), Console 8601, Portainer 9443/9000 (dev).
- Redis password: when `DCL_REDIS_PASSWORD` is set, Redis runs with `requirepass` and compose puts it into every in-stack `DCL_REDIS_URL`. The host-side `DCL_REDIS_URL` in `.env` must then read `redis://:<password>@127.0.0.1:6381/0`; the loader refuses a URL without it. Changing the password: edit both lines, then `up -d` (Redis and every backend service restart). `redis-cli -a "$DCL_REDIS_PASSWORD"` for manual checks.
- `.env` holds host-side URLs for operator CLIs (`127.0.0.1:5435`, …). Compose sets the in-network URLs per container (`postgres:5432`, `redis:6379`, `minio:9000`, `models:8500`). Credentials are interpolated into URLs and must be URL-safe.
- Console (`console`, 8601): S3's production build (`frontend/console/Dockerfile`, nginx, msal sign-in, no dev sign-in). Build args are baked in at `up --build`: `DCL_API_BASE_URL` (must be reachable from the browser), `DCL_TENANT_ID`, `DCL_CONSOLE_SPA_CLIENT_ID`, `DCL_CONSOLE_API_SCOPE`. Until the Entra app is registered the last two are empty and the page shows a config error; the dev Console stays on the Vite server (8600). After changing any of them: `up -d --build console`. Add the container origin (`http://<host>:8601`) to `DCL_CONSOLE_ALLOWED_ORIGINS` when switching to it.
- Only `worker-io-light` mounts `DCL_TOKEN_DIR` (read-write). In dev it runs as uid 1001, the owner of that directory.
- Running from a worktree, which has no `.env` of its own: `export DCL_ENV_FILE=/home/ai/Desktop/Swaraj_/dcl_v2/.env` and pass the same path to `--env-file`.
- Staging and prod omit `compose.dev.yaml`. `.env` must then hold `DCL_DB_USER`, `DCL_DB_PASSWORD`, `DCL_MINIO_ROOT_*` and a separate `DCL_MINIO_ACCESS_KEY`/`DCL_MINIO_SECRET_KEY` service account.
- The project name is `dcl-v2`. Never run compose with `-p dcl`: that is the paused v1 stack on the dev host.
- `down -v` deletes the database, MinIO data and the model cache. Do not use it outside a throwaway test project.

## Check health

```bash
docker compose -p dcl-v2 ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}'
DCL_STACK_PROJECT=dcl-v2 uv run pytest backend/tests/integration/stack -q
```

The integration tests check that every service is healthy, the one-shot jobs exited 0, migrations are at head, the GPU is visible only to `models`, the token dir is writable only in the sync worker, every worker answers a ping, and no `.env` or key file exists in the backend image.

## GPU check

```bash
docker compose -p dcl-v2 exec models nvidia-smi -L        # lists GPU 0
docker compose -p dcl-v2 exec api ls /dev/nvidia0          # must fail
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
```

The models role needs about 2.6 GiB of GPU memory at peak (S2 measurement). On the 8 GB dev card other processes may already hold part of it. If the models container logs CUDA out-of-memory errors, list the GPU processes and stop the one that should not be there.

## Restart the models role

```bash
docker compose -p dcl-v2 restart models
docker compose -p dcl-v2 logs -f models        # weights load on the first /models/health call, about 15 s
```

The first start downloads the weights into the `hf-cache` volume (about 4 GB), so the health check allows a 15-minute start period. Workers that embed wait while the role is down. The `embed` queue retries, and nothing is lost.

## A worker was killed for memory

Each queue runs in its own container with the memory limit of file 10 §4, so a kill stays inside one queue.

```bash
docker compose -p dcl-v2 ps worker-telemetry-stream
docker inspect --format '{{.State.OOMKilled}}' dcl-v2-worker-telemetry-stream-1
```

Tasks are acknowledged late and rejected on worker loss, so the task returns to the queue. A route that needs more memory asks S4 to change `backend/celery_redis/queues.py` and compose together; the unit tests fail if the two disagree.

## Observability

- Grafana: `http://<DCL_BIND_HOST>:${DCL_GRAFANA_PORT:-3300}`, user `admin`, password `DCL_GRAFANA_ADMIN_PASSWORD` (dev default in `compose.dev.yaml` only). Dashboard: DCL → DCL operations. Traces: Explore → Tempo.
- Every backend container exports OTLP to `otel-collector:4318`. Prometheus scrapes the collector and evaluates `backend/devops/prometheus/alerts.yml`. Alertmanager sends to the Teams webhook in `DCL_ALERT_WEBHOOK_URL`, which is read at container start and never written to a committed file.
- Change an alert: edit `alerts.yml`, add a case to `alerts_test.yml`, run `uv run pytest backend/tests/unit/devops/test_alert_rules.py`, then `docker compose -p dcl-v2 restart prometheus`.
- No alerts arriving: check `docker compose -p dcl-v2 logs alertmanager` for `Notify attempt failed`. Alertmanager redacts the URL in its logs.

## Re-auth (alert DclGraphAuthFailure)

The delegated token expired or was revoked. Run S1's device-code sign-in CLI from the main checkout; it writes the encrypted cache into `DCL_TOKEN_DIR`. The next `dcl.sync.token_health` run (every 15 minutes) clears the alert.

## Benchmark worker (benchmark)

`worker-benchmark` runs `dcl.benchmark.*` (S2's runner) with the Answer Engine in process: one prefork child, soft limit 950 s, hard limit 1000 s, 2 GB, child recycled past 1.5 GB. Beat sends `dcl.benchmark.sweep` to it every 60 s. A case that hits the hard limit is killed and redelivered; after `MAX_DELIVERIES` it is dead-lettered. Benchmark load never waits behind sync work on `io_light`.

```bash
docker compose -p dcl-v2 logs --since 10m worker-benchmark
docker compose -p dcl-v2 exec worker-benchmark celery -A backend.celery_redis.app inspect active --timeout 10
```

## Parse workers (cpu_parse)

`worker-cpu-parse` runs the `parse` image: Docling, RapidOCR (models baked in) and Tesseract with OSD and the Latin, Cyrillic, Devanagari and Arabic script models, on CPU torch. Docling's layout and TableFormer models download into the `hf-cache` volume on first use with `HF_HUB_DISABLE_XET=1`, because Xet downloads stall on this network. The first conversion after a fresh volume takes about a minute longer.
