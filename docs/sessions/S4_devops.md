# S4 — DevOps (stack, env contract, gateway client, CI, observability)

**Mission:** a reproducible stack and the two shared clients everyone depends on: the Compose stack with the GPU runtime for the embedding and reranker services, the `.env` contract loader, the Gemini gateway client, CI (migrations, FK-index check, image secret scan, tests, benchmark gate), observability, backups and runbooks.

## Read first

`docs/architecture/01_system_overview_and_tech_stack.md` (§5, §6, §7, §7.1), `10_development_plan.md` (§3, §4, §7, §9), `05_storage_schema.md` §3 and §6, `09_validation_gaps_and_fixes.md` §H.

## You own

`backend/devops/**`, `backend/devops/compose.yaml`, `backend/devops/compose.dev.yaml`, all Dockerfiles, `.github/**` (or the CI system in use), `backend/config.py` (env loader), `backend/llm_engine/gemini_client.py` (gateway client), `backend/common/telemetry.py` (OpenTelemetry setup), `.env.example`, `.gitignore`, backup and retention jobs, runbooks under `backend/devops/runbooks`.

## Publish first

1. `backend/config.py`: typed settings read from `.env` per file 01 §7.1 (refuses placeholders, refuses `GOOGLE_API_KEY`, validates `DCL_PERMISSION_OPTION`), plus `.env.example` with names only.
2. `backend/llm_engine/gemini_client.py`: the gateway client (`GEMINI_BACKEND=gateway`): chat/generate with structured output, function calling, thinking level, image/PDF parts, streaming; capability flags discovered by a probe; retry/backoff; `llm_calls` logging hook; budget guard. S2 builds VisionService and the engine on it.
3. `backend/devops/compose.yaml` with every service of file 01 §6 (PostgreSQL ParadeDB image, MinIO, Redis, Celery pools per file 10 §4, FastAPI services, embedding and reranker services on the GPU, LibreOffice, OTel collector, Grafana) and `backend/devops/compose.dev.yaml` overrides.
4. CI pipeline: lint, unit tests, `alembic upgrade head` + `alembic check` on the pinned ParadeDB image, the FK-without-index query, image layer secret scan, later the benchmark gate.

## Depends on

S1 for migration files; S2 for the model-service images; S3 for the Console build; S5 for test fixtures used in CI.

## Milestones

M0 (primary), M1 queue configuration (supporting), M6 full-corpus run (primary with S1), M8 DBOS runtime setup (supporting), M10 CI gate (supporting), M11 (primary).

## First tasks

1. Repository skeleton per file 10 §2, `.gitignore` (`.env`, worktrees, data), `.env.example`.
2. Settings loader with tests for every refusal rule.
3. Gateway client with a recorded-response test suite and the capability probe; publish the probe result to `DCL Lead` for file 09 §H.1.
4. Compose stack on the GPU host; NVIDIA container toolkit; GPU visible only to the two model services; health checks; named volumes on local disk.
5. OpenTelemetry across FastAPI, Celery and the engine; Prometheus metrics of file 02 §10; Grafana dashboards; alert routing to `DCL_ALERT_WEBHOOK_URL` for the operational alerts only.
6. Backups (PostgreSQL base + WAL, MinIO versioning), retention jobs, runbooks (re-auth, 410 resync, worker OOM, Gemini outage, model-service restart).

## Definition of done

Wiki: map page updated and plan sheet deleted (see below). Then:

`docker compose up` from a clean checkout reaches healthy; CI green; secrets never in images (scan passes); runbook entry; status entry; merge request.

## Wiki duty (applies to every task)

Read `.wiki/index.md` and your feature's map page first. Open a plan sheet (`.wiki/_templates/plan-sheet.md`) with the exact workspace and rubric; work only inside it; when done, update the map page (status, location, interfaces, workspace, change log), update the area index, delete the plan sheet. Your map pages are listed in `.wiki/<area>/index.md` under your session id.

## When in doubt or blocked

Write the question or the blocker to `docs/sessions/STATUS.md`, message `DCL Lead` (or the session you wait on) once, and end your turn. Never improvise around the manual and never keep working "on the side" while waiting.

## Coordination rules

- Secrets live only in `.env` on the host; never in `pipeline_config`, images or the repo.
- The gateway client is the only module that knows the gateway URL; nothing else imports an HTTP client for Gemini.
- Queue and memory limits per file 10 §4 are configuration you own; a route that needs more memory asks you, it does not raise its own limit.

## Handoff from the Lead, 2026-10-23 (read before the next redeploy)

Done on the live stack by the Lead, at the user's request: pg_dump taken (kept by the Lead until the user confirms), migration **0013** (`documents.minhash`) and **0014** (CONFLICT evidence `relation`; the assembler's orphan-file notes leave the queue) applied with `docker compose run --rm --no-deps migrate alembic … upgrade <rev>`; `api` rebuilt and recreated; `console` rebuilt and recreated (it now needs the repository's `asset/` folder). Order mattered and is the rule from now on: **additive column first → API with the new code → data migration**, because every contract model is `extra="forbid"`, so an old API cannot read rows a data migration has already reshaped.

Update 2026-10-24: migration **0015** (rule proposals) applied on the stack DB after a pg_dump; `api` and `console` rebuilt and recreated again. Workers still run the older image: Route C there does not yet call `proposals.refresh`, so a newly halted file shows no rule proposal until they are recreated. Earlier update, same day as the first handoff: `api` was rebuilt and recreated a second time (new review endpoints `/review/rules/preview` and `/review/folders`; no migration) and `console` a third time. The workers below are still on the earlier image.

Open for S4:

1. **Workers still run the previous image** (`worker-io-light`, `beat`, `worker-telemetry-stream`, `worker-vision-batch`, `worker-embed`, `worker-benchmark`; `worker-cpu-parse` and `worker-media` use their own tags). Rebuild and recreate them at a quiet moment (A1 PDFs take about 5 minutes each; do not cut a running conversion). Until then newly landed files are still assembled by the old dispatcher, which raises "not included by any master" as a CONFLICT flag again. Nothing is lost; the next 0014-style cleanup or the redeploy ends it.
2. **Console sign-in mode is a build variable.** The Console on 8601 uses password login (DECISIONS 2026-10-22), but Compose defaulted to `msal`, so a plain `docker compose build console` produced a Console that cannot sign in ("missing VITE_ENTRA_CLIENT_ID"; the Lead hit this and rebuilt). `compose.yaml` now reads `${VITE_AUTH_MODE:-msal}`: build the standing Console with `VITE_AUTH_MODE=local docker compose … build console`. Consider making `local` the default in compose.dev.yaml while Entra ID is future scope.
3. **Console build context.** `backend/devops/compose.yaml` gives the `console` service `additional_contexts: asset: ../../asset`, and `frontend/console/Dockerfile` does `COPY --from=asset . /asset`. A CI step that builds the Console image must pass the same named context (`docker build --build-context asset=asset frontend/console`), and a build outside Compose must too, or `npm run build` cannot resolve `$asset`.
4. **Runbook line** for backend/devops/runbooks: before running a migration that rewrites stored JSON, deploy the API that reads both shapes; take a `pg_dump -Fc` first (the Lead's was `docker exec dcl-v2-postgres-1 pg_dump -U dcl_v2 -d dcl_v2 -Fc --exclude-table-data=llm_calls`).
5. After the workers are recreated: S1 runs `python -m backend.indexing.near_duplicates backfill` once so documents indexed before 0013 get a MinHash signature.
