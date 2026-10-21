# Plan: platform/compose-stack — M0 stack with the GPU models role

| Field | Value |
|-------|-------|
| Feature | `platform/compose-stack` (map: `.wiki/platform/compose-stack.md`) |
| Session | S4 |
| Branch | claude/gifted-hofstadter-0bec1c |
| Opened | 2026-10-21 |
| Delete when | rubric below is green and the map page is updated |

## Intent

One image built from one Dockerfile with two targets (`backend` for api, workers and beat; `models` adding S2's GPU dependency group), MinIO built from the archived pinned tag (file 09 §H.1), LibreOffice headless in its own container (unoserver), ParadeDB `0.26.2-pg17`, Redis, one Celery worker container per queue of file 10 §4 with its pool, concurrency, memory limit and time limits, and beat. The GPU is reserved only for the `models` service. Compose project name `dcl-v2` (a paused v1 stack uses `dcl`). `compose.dev.yaml` adds host ports on 127.0.0.1, dev credentials and reduced concurrency for this 15 GB host. Observability (OTel, Grafana, Flower) is the next task; Open WebUI and the Console SPA come with S3's builds.

## Workspace

Files to change (exact):
- `backend/devops/compose.yaml`, `backend/devops/compose.dev.yaml`
- `backend/devops/docker/backend.Dockerfile`, `backend/devops/docker/minio.Dockerfile`, `backend/devops/docker/libreoffice.Dockerfile`
- `.dockerignore`
- `backend/celery_redis/app.py`, `backend/celery_redis/queues.py`, `backend/celery_redis/beat.py`
- `backend/tests/unit/celery_redis/test_queues.py` (queues ↔ compose consistency, app config)
- `backend/tests/integration/stack/test_stack.py` (runs only against a live project)
- `backend/devops/runbooks/stack.md`
- `pyproject.toml`, `uv.lock` (celery; `models` group with S2's pins and the PyTorch cu130 index)
- `.wiki/platform/compose-stack.md`, `.wiki/platform/index.md`, `.wiki/index.md`, `docs/sessions/STATUS.md`

Out of scope: `backend/api/models.py`, `backend/llm_engine/local_models.py` (S2); bucket creation (S1 storage); task modules (S1, S2).

## Rubric for this task

- [ ] `docker compose up` from a clean checkout reaches healthy (all services)
- [ ] GPU visible only to `models` (`nvidia-smi -L` works there and fails in `api` and a worker)
- [ ] Queue memory limits, pools and concurrency in compose match `queues.py` and file 10 §4 (test)
- [ ] No `.env` or secret in any image layer (build context excludes it; grep of image filesystem)
- [ ] Runbook entry for start, stop, GPU check, models restart
- [ ] `uv run pytest` and ruff pass

## Verification commands

```bash
docker compose -p dcl-v2 --env-file <env> -f backend/devops/compose.yaml -f backend/devops/compose.dev.yaml up -d --build --wait
DCL_STACK_PROJECT=dcl-v2 uv run pytest backend/tests/integration/stack -q
```

## Risks and open questions

- Gated Hugging Face weights may need a token that is not in the env contract (ask S2).
- Base memory limits (~38 GB) exceed this host's 15 GB; dev override reduces concurrency.
