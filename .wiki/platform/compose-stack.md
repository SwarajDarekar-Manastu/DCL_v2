# Docker Compose stack with GPU model services

| Field | Value |
|-------|-------|
| Feature id | `platform/compose-stack` |
| Status | in-progress |
| Owner session | S4 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §6; 09 §H.1 (MinIO); 10 §3, §4 |
| Last updated | 2026-10-22 |

## Purpose

All services of file 01 §6 in compose project `dcl-v2`: ParadeDB pg17, Redis, MinIO built from the archived pinned tag, LibreOffice headless, the models role on the only GPU reservation, the API role, beat, one Celery worker per queue of file 10 §4, and the one-shot `minio-init` and `migrate` jobs. Observability services (collector, Tempo, Prometheus, Alertmanager, Grafana) are part of it; Open WebUI and the Console SPA (port 8600) are not yet.

## Location

Code:
- `backend/devops/compose.yaml`, `backend/devops/compose.dev.yaml`
- `backend/devops/docker/backend.Dockerfile` (targets `backend`, `models` (CUDA torch), `parse` (CPU torch, Docling, RapidOCR, Tesseract scripts); builder stage compiles deps)
- `backend/devops/docker/minio.Dockerfile` (RELEASE.2025-10-15T17-29-55Z, commit-checked)
- `backend/devops/docker/libreoffice.Dockerfile` (unoserver on 2003)
- `backend/devops/minio_init.py` (buckets, versioning, lifecycle, app user; idempotent)
- `backend/celery_redis/app.py`, `queues.py`, `beat.py`
- `.dockerignore`
- `backend/devops/runbooks/stack.md`

Tests and fixtures:
- `backend/tests/unit/celery_redis/test_queues.py` (compose ↔ `queues.py` ↔ file 10 §4; GPU only on models; in-network URLs; token mount; host ports)
- `backend/tests/integration/stack/test_stack.py` (live project: `DCL_STACK_PROJECT=dcl-v2`)

## Interfaces

Provides:
- Healthy stack: `docker compose --env-file .env -f backend/devops/compose.yaml -f backend/devops/compose.dev.yaml up -d --build --wait`
- Host ports on `DCL_BIND_HOST`: 5435 PostgreSQL (`DCL_DB_PORT`), 6381 Redis, 9100 MinIO, 9101 MinIO console, 8500 models, 8200 API
- In-network URLs set per container: `postgres:5432/dcl_v2`, `redis:6379/0`, `minio:9000`, `models:8500`
- Celery: `backend.celery_redis.app.app`, queues `Queue.*`, pools `POOLS`; task modules `backend/celery_redis/tasks_*.py` are included when present; `dcl.ping`
- LibreOffice: `unoconvert --host libreoffice --port 2003 --host-location remote <in> <out>`

Consumes:
- `platform/env-contract`; S2's `/models/health` and `models` dependency group; S1's `backend.storage.minio.BUCKETS` and Alembic config

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/devops/compose.yaml`
- `backend/devops/compose.dev.yaml`
- `backend/devops/docker/`
- `backend/devops/minio_init.py`
- `backend/celery_redis/app.py`, `backend/celery_redis/queues.py`, `backend/celery_redis/beat.py`
- `.dockerignore`
- `backend/devops/runbooks/stack.md`
- `backend/tests/unit/celery_redis/test_queues.py`
- `backend/tests/integration/stack/`

## Rubric (what "done" means for this feature)

- [x] docker compose up reaches healthy (2026-10-22, real `.env`: 13 services healthy, both one-shot jobs exited 0, migrations at head)
- [x] GPU visible only to the two model services (one `models` role; integration test)
- [x] Queue memory limits match file 10 §4 (unit test; dev override only lowers them)
- [x] No `.env` or key file in the backend image (integration test)
- [x] Observability services added (2026-10-22)
- [x] Parse image: Docling + RapidOCR and Tesseract (Latin, Cyrillic, Devanagari, Arabic, OSD) OCR a scanned page correctly (2026-10-22)
- [ ] Open WebUI and Console SPA added (S3 builds)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S4 | `parse` image for cpu_parse (CPU torch via a group-scoped index; `models` and `parse` declared conflicting); `HF_HUB_DISABLE_XET=1`; observability services; `_incoming/` lifecycle rule; S1 process schedules |
| 2026-10-22 | S4 | Beat schedule for S1's sync tasks (delta 02:00 Asia/Kolkata, token health 15 min, downloads 10 min) |
| 2026-10-22 | S4 | M0 stack: images, MinIO from source, LibreOffice, models on the GPU, API, beat, six queue workers, `minio-init`, `migrate`; host ports and in-network URLs per the Lead's allocation; verified live on the dev host with the real `.env` |

## Related

- `platform/env-contract`, `platform/observability`, `platform/ci`
- `backend/embedding-service`, `backend/reranker-service`, `backend/registry-and-blobs`, `backend/schema-and-migrations`
- `.wiki/index.md`
