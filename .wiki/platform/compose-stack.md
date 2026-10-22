# Docker Compose stack with GPU model services

| Field | Value |
|-------|-------|
| Feature id | `platform/compose-stack` |
| Status | in-progress |
| Owner session | S4 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §6; 09 §H.1 (MinIO); 10 §3, §4 |
| Last updated | 2026-10-22 |

## Purpose

All services of file 01 §6 in compose project `dcl-v2`: ParadeDB pg17, Redis, MinIO built from the archived pinned tag, LibreOffice headless, the models role on the only GPU reservation, the API role, beat, one Celery worker per queue of file 10 §4, and the one-shot `minio-init` and `migrate` jobs. Observability services (collector, Tempo, Prometheus, Alertmanager, Grafana) are part of it; The Console production build runs on 8601 (`console`); Open WebUI comes in M9.

## Location

Code:
- `backend/devops/compose.yaml`, `backend/devops/compose.dev.yaml`
- `backend/devops/docker/backend.Dockerfile` (targets `backend`, `models` (CUDA torch), `parse` (CPU torch, Docling, RapidOCR, Tesseract scripts); builder stage compiles deps)
- `backend/devops/docker/minio.Dockerfile` (RELEASE.2025-10-15T17-29-55Z, commit-checked)
- `backend/devops/docker/libreoffice.Dockerfile` + `office_server.py` (POST /convert on 2003, one soffice run per request, recalculating profile)
- `backend/common/office.py` (the one client: `convert(data, from_ext, to, recalc=False)`)
- `backend/devops/minio_init.py` (buckets, versioning, lifecycle, app user via `policy_set`; idempotent; runs on MinIO and RustFS 1.0.3)
- `backend/celery_redis/app.py` (incl. `DclTask`: delivery count, poison stop, dead-letter list), `queues.py`, `beat.py`
- `backend/celery_redis/tasks_loadtest.py`, `backend/celery_redis/load_test.py`, `backend/devops/ci/queue_load_test.sh` (M1 queue load test)
- `console` service: built from S3's `frontend/console/Dockerfile` (build args only)
- `.dockerignore`
- `backend/devops/runbooks/stack.md`

Tests and fixtures:
- `backend/tests/unit/celery_redis/test_queues.py` (compose ↔ `queues.py` ↔ file 10 §4; GPU only on models; in-network URLs; token mount; host ports)
- `backend/tests/integration/stack/test_stack.py` (live project: `DCL_STACK_PROJECT=dcl-v2`)

## Interfaces

Provides:
- Healthy stack: `docker compose --env-file .env -f backend/devops/compose.yaml -f backend/devops/compose.dev.yaml up -d --build --wait`
- Host ports on `DCL_DATA_BIND_HOST` (default 127.0.0.1): 5435 PostgreSQL (`DCL_DB_PORT`), 6381 Redis, 9100 MinIO S3
- Host ports on `DCL_BIND_HOST` (UIs and API): 9101 MinIO console, 8500 models, 8200 API, 3300 Grafana, 8601 Console, 9443/9000 Portainer (dev)
- Redis `requirepass` from `DCL_REDIS_PASSWORD` (empty = no password); compose puts it into every in-stack `DCL_REDIS_URL`
- In-network URLs set per container: `postgres:5432/dcl_v2`, `redis://[:password@]redis:6379/0`, `minio:9000`, `models:8500`
- Dead letters: every final task failure and every task whose worker died `MAX_DELIVERIES` (3) times lands in the Redis list `dcl:dead_letter` (newest first, capped 10,000); read with `backend.celery_redis.app.dead_letters(limit)` for the Console "Failed tasks" page
- M1 load test: `backend/devops/ci/queue_load_test.sh [--project dcl-v2] --tasks 5000`
- Celery: `backend.celery_redis.app.app`, queues `Queue.*`, pools `POOLS`; task modules `backend/celery_redis/tasks_*.py` are included when present; `dcl.ping`
- LibreOffice: `backend.common.office.convert(data, from_ext, to, *, recalc=False)` → bytes; `to` ∈ pdf/docx/pptx/xlsx; inputs doc/docx/rtf/odt/ppt/pptx/odp/xls/xlsx/ods; endpoint `settings.office_url` (`DCL_OFFICE_URL`, in-stack `http://libreoffice:2003`; name pending Lead approval)

Consumes:
- `platform/env-contract`; S2's `/models/health` and `models` dependency group; S1's `backend.storage.minio.BUCKETS` and Alembic config

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/devops/compose.yaml`
- `backend/devops/compose.dev.yaml`
- `backend/devops/docker/`
- `backend/devops/minio_init.py`
- `backend/common/office.py`
- `backend/celery_redis/app.py`, `backend/celery_redis/queues.py`, `backend/celery_redis/beat.py`
- `.dockerignore`
- `backend/devops/runbooks/stack.md`
- `backend/tests/unit/celery_redis/test_queues.py`
- `backend/tests/integration/stack/`

## Rubric (what "done" means for this feature)

- [x] docker compose up reaches healthy (2026-10-22, real `.env`: 13 services healthy, both one-shot jobs exited 0, migrations at head)
- [x] GPU visible only to the two model services (one `models` role; integration test)
- [x] Queue memory limits match file 10 §4 (unit test; dev override only lowers them)
- [x] M1 queue load test (2026-10-22, throwaway project): 5,002 tasks accounted for, routing correct on all six queues, 233 transient failures retried, 52 permanent + 2 OOM tasks dead-lettered, worker kills only in telemetry_stream, no container restart
- [x] No `.env` or key file in the backend image (integration test)
- [x] Observability services added (2026-10-22)
- [x] Parse image: Docling + RapidOCR and Tesseract (Latin, Cyrillic, Devanagari, Arabic, OSD) OCR a scanned page correctly (2026-10-22)
- [x] Console SPA added (2026-10-22: builds from compose, healthy, deep links 200, no secret value in the image)
- [ ] Open WebUI added (M9)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S4 | RustFS adoption step 1: `minio-init` sets the app policy with `policy_set` (RustFS answers `attach_policy` with AEAD id 2); full init twice + policy scope verified on RustFS 1.0.3 and MinIO |
| 2026-10-22 | S4 | Console container on 8601 from S3's Dockerfile (msal build; args `DCL_API_BASE_URL`, `DCL_TENANT_ID`, `DCL_CONSOLE_SPA_CLIENT_ID`, `DCL_CONSOLE_API_SCOPE`) |
| 2026-10-22 | S4 | Network exposure split: Postgres, Redis, MinIO S3 on `DCL_DATA_BIND_HOST` (default loopback); Redis `requirepass` from `DCL_REDIS_PASSWORD`, verified live on a throwaway project (NOAUTH without, PONG with, healthy) |
| 2026-10-22 | S4 | Object-store evaluation (`backend/devops/object_store_evaluation.md`, `backend/devops/ci/s3_compat_check.py`): RustFS 1.0.3 recommended over SeaweedFS 4.48 and Garage v2.4.1 |
| 2026-10-22 | S4 | Office conversion service + client (unoserver dropped: inline and path-based xlsx loads fail on LibreOffice 7.4); verified rtf/doc→docx, docx→pdf, xls→xlsx, xlsx recalculation (stale 999 → 81), FMEA fixture → pdf |
| 2026-10-22 | S4 | Dead-letter list and poison-task stop (`DclTask`), M1 queue load test harness (passed), 24 h lifecycle on `dcl-exports/uploads/` |
| 2026-10-22 | S4 | `parse` image for cpu_parse (CPU torch via a group-scoped index; `models` and `parse` declared conflicting); `HF_HUB_DISABLE_XET=1`; observability services; `_incoming/` lifecycle rule; S1 process schedules |
| 2026-10-22 | S4 | Beat schedule for S1's sync tasks (delta 02:00 Asia/Kolkata, token health 15 min, downloads 10 min) |
| 2026-10-22 | S4 | M0 stack: images, MinIO from source, LibreOffice, models on the GPU, API, beat, six queue workers, `minio-init`, `migrate`; host ports and in-network URLs per the Lead's allocation; verified live on the dev host with the real `.env` |

## Related

- `platform/env-contract`, `platform/observability`, `platform/ci`
- `backend/embedding-service`, `backend/reranker-service`, `backend/registry-and-blobs`, `backend/schema-and-migrations`
- `.wiki/index.md`
