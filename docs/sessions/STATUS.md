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

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541 (S1 → this branch)
Merged / ready: backend/postgres base + naming convention, enums→CHECK, M1 registry models (6 tables), migration 0001, backend/tests/schema (21 tests) + sqlalchemy/alembic/psycopg in pyproject. Test: `DCL_TEST_DATABASE_URL=<disposable db> uv run pytest && uv run ruff check backend` (76 passed on paradedb:latest = PG 18.6, pg_search 0.26.2; also green on postgres:16)
Blocked on: nothing
Needs from others: S4 — pin the ParadeDB tag (latest is PG 18; manual says 16/17) and run the suite in CI with DCL_TEST_DATABASE_URL on a disposable DB; Lead — sync_roots has no resync-generation column (file 02 §3.5 vs file 05 §4.1), see merge request
Next: task 2, MSAL device-code sign-in, silent refresh, outside-share negative check

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: task 1 (M1 schema) at 7aac2a3, merge requested; task 2 (MSAL sign-in) not started
Blocked on: DCL Lead decision. File 02 §1 says the token cache at DCL_TOKEN_CACHE_PATH is "encrypted at rest" and the encryption key lives in the secret store, but file 01 §7.1 has no key variable, and the existing cache (shared with the v1 pipeline under DCL_SECRET_STORE) is plain MSAL JSON, mode 600, owned by `ai`, not root. Options: (a) plain JSON, mode 600 in a 700 dir, atomic writes, rely on host disk encryption, manual text amended; (b) Fernet-encrypt with a new `DCL_TOKEN_CACHE_KEY` (S4 adds it to the contract), migrate the plain cache once, v1 then needs its own cache file. S1 recommends (b). Second question: is DCL_TEST_OUTSIDE_ITEM_ID in the DCL_DRIVE_ID drive? If not, a 404 there proves nothing and the check needs the item's drive id too.
Needs from others: Lead — the two answers above
Next: task 2 once answered (auth.py with device-code + silent refresh, live read-only checks of the four roots and the outside item using the existing cache)
