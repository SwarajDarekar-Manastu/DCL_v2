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

## 2026-10-21 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: session S3 = worktree `cranky-rhodes-0cb23f`, branch `claude/cranky-rhodes-0cb23f`. Ready: `frontend/console-shell-auth` (SvelteKit 2 shell, MSAL login, server role mapping, `GET /auth/me`, `/ws` with Redis bridge; 24 Vitest + 28 pytest tests; `npm run check` and `npm run build` clean).
Blocked on: nothing. Review UI waits for S1's `backend/review/api_models.py` (S1: third in their publish order).
Needs from others: S4 to add `console_api_audience`, `console_group_reviewers`, `console_group_admins`, `console_allowed_origins`, `redis_url` to `get_settings()` once the Lead approves the names; Lead to add `pyjwt[crypto]` and `redis` to pyproject and, in `backend/main.py`, start `ws.redis_bridge(settings.redis_url)` in the lifespan and CORS for `console_allowed_origins` if the Console is served from another origin.
Next: shared viewer (`frontend/viewer`), then Settings scaffolding.
