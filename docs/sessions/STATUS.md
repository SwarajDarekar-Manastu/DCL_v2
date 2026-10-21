# Status log

Append one entry per work block. Newest at the bottom. Keep each entry to the four lines.

Format:

```
## YYYY-MM-DD HH:MM — <session name> — <branch>
Merged / ready: <what is on the branch and tested>
Blocked on: <session or decision, or "nothing">
Needs from others: <exact request, or "nothing">
Next: <the next task from the brief>
```

---

## 2026-10-21 — DCL Lead — main
Merged / ready: architecture manual v2 (docs/architecture), session briefs (docs/sessions)
Merged / ready (cont.): .wiki map with 39 feature pages, repository initialized against github.com/SwarajDarekar-Manastu/DCL_v2
Blocked on: nothing
Needs from others: each role session to message "S<n> started"
Next: first merge round after S4 publishes the settings loader and S1 the M1 models; wiki lint at that round

## 2026-10-21 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c (S4 → this branch, kept per README)
Merged / ready: repository skeleton of file 10 §2 (packages, `backend/main.py` mounting `backend/api/*` routers by ROLE api|models|all, one stub `router = APIRouter()` per planned router for owners to fill, `/healthz`, `pyproject.toml` + `uv.lock`, `.env.example` names only, `.gitignore` data patterns root-anchored so `backend/postgres/models/` is tracked). Test: `uv sync && uv run pytest && uv run ruff check backend`
Blocked on: nothing
Needs from others: owners fill their stub routers in place (do not edit `backend/main.py`); add dependencies to `pyproject.toml` in your own merge request; `backend/api/models.py` must not load weights at import
Next: full env contract in `backend/config.py` with refusal tests; env-name questions to DCL Lead

## 2026-10-21 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: env contract loader `backend/config.py` (typed Settings with the file 01 §7.1 names, load-time refusals, `Settings.require(Group…)` at component startup, names-only error messages); real `.env` loads. Test: `uv run pytest && uv run ruff check backend` (55 passed)
Blocked on: DCL Lead answers for DCL_GEMINI_API_KEY, MinIO/Redis names, Console auth names (S3), DB URL composition; operator to add GEMINI_BACKEND and GEMINI_GATEWAY_URL to `.env`
Needs from others: consumers call `get_settings().require(Group.GRAPH)` / `(Group.GEMINI)` in their startup instead of reading os.environ
Next: Gemini gateway client + capability probe (OpenAI-compatible shape, every capability behind a flag)

## 2026-10-21 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: Gemini gateway client `backend/llm_engine/gemini_client.py` + probe `gemini_probe.py` + `gemini_capabilities.json` (all capabilities `unknown`, so only plain chat and the documented fallbacks are active until the probe runs). Test: `uv run pytest` (100 passed)
Blocked on: real probe needs `GEMINI_BACKEND` and `GEMINI_GATEWAY_URL` in `.env` (operator) and the gateway contract answers sent to DCL Lead
Needs from others: S2 builds VisionService/engine on `GeminiClient` (interface on the map page); S1 tells S4 when `llm_calls` exists so the ledger hook and budget `usage_today` are wired to it
Next: Compose stack (`backend/devops/compose.yaml`, `compose.dev.yaml`, Dockerfiles) with the GPU runtime for the ROLE=models container

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541 (S1 → this branch)
Merged / ready: backend/postgres base + naming convention, enums→CHECK, M1 registry models (6 tables), migration 0001, backend/tests/schema (21 tests) + sqlalchemy/alembic/psycopg in pyproject. Test: `DCL_TEST_DATABASE_URL=<disposable db> uv run pytest && uv run ruff check backend` (76 passed on paradedb:latest = PG 18.6, pg_search 0.26.2; also green on postgres:16)
Blocked on: nothing
Needs from others: S4 — pin the ParadeDB tag (latest is PG 18; manual says 16/17) and run the suite in CI with DCL_TEST_DATABASE_URL on a disposable DB; Lead — sync_roots has no resync-generation column (file 02 §3.5 vs file 05 §4.1), see merge request
Next: task 2, MSAL device-code sign-in, silent refresh, outside-share negative check

## 2026-10-21 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: nothing new since the gateway client entry (three merge requests open: skeleton 136603d, loader b960763, client 7591007)
Blocked on: DCL Lead decision on MinIO before the Compose stack. The official MinIO images are no longer pullable (Docker Hub repo removed, quay.io gone, GitHub minio/minio archived; last tag RELEASE.2025-10-15T17-29-55Z), so file 01 §5.5 / §6 cannot be deployed reproducibly as written. Options: (A) build MinIO from the archived pinned source tag in `backend/devops/docker/minio.Dockerfile` (unmaintained, AGPL, internal only); (B) replace it with a maintained S3-compatible store (needs a manual change: versioning, lifecycle expiry, presign, DuckDB httpfs); (C) Chainguard `minio:latest` (maintained, but not pinnable on the free tier). S4 recommends A now and B evaluated before M11. Also still open: MinIO/Redis env names, `DCL_GEMINI_API_KEY`, Console auth names, DB URL composition, `.env` location, gateway contract questions
Needs from others: DCL Lead answers; operator adds `GEMINI_BACKEND` and `GEMINI_GATEWAY_URL` and fills `DCL_DB_USER`/`DCL_DB_PASSWORD` in `.env`
Next: Compose stack (project name `dcl-v2`, because a paused DCL v1 stack on this host uses project `dcl` and host port 5432), GPU runtime for the ROLE=models container, Celery queues of file 10 §4
