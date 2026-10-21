# Runbook: the Compose stack

Spec: docs/architecture/01 §6, 10 §3–§4. Map: `.wiki/platform/compose-stack.md`. Run every command from the repository root.

## Start and stop

```bash
docker compose --env-file .env -f backend/devops/compose.yaml -f backend/devops/compose.dev.yaml up -d --build --wait
docker compose -p dcl-v2 ps -a
docker compose -p dcl-v2 down            # keeps volumes
```

- Every `up` first runs two one-shot jobs: `minio-init` (buckets, versioning on dcl-raw and dcl-cir, lifecycle, the application user) and `migrate` (`alembic upgrade head`). Both are idempotent and must show `Exited (0)`.
- Host ports on `DCL_BIND_HOST`: PostgreSQL `DCL_DB_PORT` (5435 on the dev host), Redis 6381, MinIO API 9100, MinIO console `DCL_MINIO_CONSOLE_PORT` (9101), models 8500, API 8200.
- `.env` holds host-side URLs for operator CLIs (`127.0.0.1:5435`, …). Compose sets the in-network URLs per container (`postgres:5432`, `redis:6379`, `minio:9000`, `models:8500`). Credentials are interpolated into URLs and must be URL-safe.
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
