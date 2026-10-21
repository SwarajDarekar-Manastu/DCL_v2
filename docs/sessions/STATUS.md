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

## 2026-10-21 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: session S3 = worktree `cranky-rhodes-0cb23f`, branch `claude/cranky-rhodes-0cb23f`. Ready: `frontend/console-shell-auth` (SvelteKit 2 shell, MSAL login, server role mapping, `GET /auth/me`, `/ws` with Redis bridge; 24 Vitest + 28 pytest tests; `npm run check` and `npm run build` clean).
Blocked on: nothing. Review UI waits for S1's `backend/review/api_models.py` (S1: third in their publish order).
Needs from others: S4 to add `console_api_audience`, `console_group_reviewers`, `console_group_admins`, `console_allowed_origins`, `redis_url` to `get_settings()` once the Lead approves the names; Lead to add `pyjwt[crypto]` and `redis` to pyproject and, in `backend/main.py`, start `ws.redis_bridge(settings.redis_url)` in the lifespan and CORS for `console_allowed_origins` if the Console is served from another origin.
Next: shared viewer (`frontend/viewer`), then Settings scaffolding.

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541 (S1 → this branch)
Merged / ready: backend/postgres base + naming convention, enums→CHECK, M1 registry models (6 tables), migration 0001, backend/tests/schema (21 tests) + sqlalchemy/alembic/psycopg in pyproject. Test: `DCL_TEST_DATABASE_URL=<disposable db> uv run pytest && uv run ruff check backend` (121 passed after merging main, on paradedb:latest-pg17 = PG 17.11, pg_search 0.26.2; also green on PG 18 and postgres:16)
Blocked on: nothing
Needs from others: S4 — run the suite in CI with DCL_TEST_DATABASE_URL on a disposable DB on the pinned pg17 tag; resync generation answered by Lead (max(drive_items.resync_gen)+1, no column)
Next: task 2, MSAL device-code sign-in, silent refresh, outside-share negative check

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: task 1 (M1 schema) at 7aac2a3, merge requested; task 2 (MSAL sign-in) not started
Blocked on: DCL Lead decision. File 02 §1 says the token cache at DCL_TOKEN_CACHE_PATH is "encrypted at rest" and the encryption key lives in the secret store, but file 01 §7.1 has no key variable, and the existing cache (shared with the v1 pipeline under DCL_SECRET_STORE) is plain MSAL JSON, mode 600, owned by `ai`, not root. Options: (a) plain JSON, mode 600 in a 700 dir, atomic writes, rely on host disk encryption, manual text amended; (b) Fernet-encrypt with a new `DCL_TOKEN_CACHE_KEY` (S4 adds it to the contract), migrate the plain cache once, v1 then needs its own cache file. S1 recommends (b). Second question: is DCL_TEST_OUTSIDE_ITEM_ID in the DCL_DRIVE_ID drive? If not, a 404 there proves nothing and the check needs the item's drive id too.
Needs from others: Lead — the two answers above
Next: task 2 once answered (auth.py with device-code + silent refresh, live read-only checks of the four roots and the outside item using the existing cache)
## 2026-10-21 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: `frontend/viewer` contract and Console UI: deep link `/docs/{id}/viewer?anchor=<kind>:<value>:<hash>` with `viewer_path()`, `ViewerPayload` models, viewer page and components (page + bbox overlays, image, table, code, text, video, fallback notice, metadata, translate toggle); 35 Vitest + 155 pytest pass. Endpoint returns 501 until wired.
Blocked on: wiring the viewer body needs S1 (`Anchor`, documents, `v_doc_locations`, page-render assets, presign) and S2 (`resolve_anchor`); both told the contract 2026-10-21.
Needs from others: S2 to emit citation links with `viewer_path()`; nothing else new.
Next: Settings scaffolding (`frontend/settings-ui`), then the Open WebUI Pipe skeleton once S2's `/v1/answer` schema is on main.
## 2026-10-21 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: nothing new since the gateway client entry (three merge requests open: skeleton 136603d, loader b960763, client 7591007)
Blocked on: DCL Lead decision on MinIO before the Compose stack. The official MinIO images are no longer pullable (Docker Hub repo removed, quay.io gone, GitHub minio/minio archived; last tag RELEASE.2025-10-15T17-29-55Z), so file 01 §5.5 / §6 cannot be deployed reproducibly as written. Options: (A) build MinIO from the archived pinned source tag in `backend/devops/docker/minio.Dockerfile` (unmaintained, AGPL, internal only); (B) replace it with a maintained S3-compatible store (needs a manual change: versioning, lifecycle expiry, presign, DuckDB httpfs); (C) Chainguard `minio:latest` (maintained, but not pinnable on the free tier). S4 recommends A now and B evaluated before M11. Also still open: MinIO/Redis env names, `DCL_GEMINI_API_KEY`, Console auth names, DB URL composition, `.env` location, gateway contract questions
Needs from others: DCL Lead answers; operator adds `GEMINI_BACKEND` and `GEMINI_GATEWAY_URL` and fills `DCL_DB_USER`/`DCL_DB_PASSWORD` in `.env`
Next: Compose stack (project name `dcl-v2`, because a paused DCL v1 stack on this host uses project `dcl` and host port 5432), GPU runtime for the ROLE=models container, Celery queues of file 10 §4

## 2026-10-21 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: env-contract follow-up (wiring + Console names of file 01 §7.1, `DCL_ENV` dev-only defaults, `DCL_ROLE` with `ROLE` alias, `DCL_GEMINI_API_KEY` fallback + `AIza` refusal, `stack_database_url()`, S1's `DCL_TOKEN_CACHE_KEY` (Fernet-checked, in the graph group) and `DCL_TEST_OUTSIDE_DRIVE_ID`, tests that `.env.example` and the loader cover every manual name); gemini types split into `gemini_types.py` (client 590 lines); httpx2 in dev deps. Test: `uv run pytest` (156 passed, 18 skipped without a test DB)
Blocked on: nothing (MinIO decision received: build from the archived pinned tag)
Needs from others: operator fills in `.env`: `DCL_TOKEN_CACHE_KEY`, `GEMINI_BACKEND`, `GEMINI_GATEWAY_URL`, `DCL_DB_USER`/`DCL_DB_PASSWORD`, `DCL_MINIO_*` keys, Console auth names, `DCL_PIPE_SHARED_SECRET`; S2 imports types from `backend.llm_engine.gemini_types`
Next: Compose stack with the GPU runtime for the ROLE=models container, ParadeDB pinned to a pg17 tag, MinIO built from source

## 2026-10-21 19:50 — DCL S5 Quality — claude/strange-bhaskara-1dd439 (S5 → this branch, kept per README)
Merged / ready: `quality/config-data` (six `config/` data files from the manual and public references, all `sme_confirmed: false`; 152 load tests incl. RocketCEA HTP 90/98 vs published decomposition temperatures) and `quality/fixtures` synthetic half (12 fixtures for every file 10 §7 edge case, generator, expected.yaml, 30 integrity tests). Dev deps added. Test: `uv run pytest backend/tests/unit/config_data backend/tests/fixtures && uv run ruff check backend` (182 passed)
Blocked on: SME answer to the 13-slot allowlist table (sent to DCL Lead 2026-10-21); real per-format fixtures, telemetry cases and retrieval set wait for it
Needs from others: Lead decisions on three questions: (1) quantity synonyms Isp/Pc have no entity type in 04 §3.2, so where do `quantity_terms` load? (2) 04 §2 lets a vendor name alone turn a document `external_kept`, but internal reports name sensor/DAQ vendors (LabJack, Kistler); should vendors marked `internal_equipment: true` need a datasheet/brochure cue too? (3) FMEA score columns (S, O, D, RPN) are dimensionless; does 03 §C.4 step 8 really raise UNIT_AMBIGUITY SOFT on them? S1: apply `config/units.txt` alias lines before pint (pint reads `bar(g)` as bar·gram); S1 rules YAML schema for `config/rules/`
Next: on the allowlist answer, collect real fixtures with expected outcomes and the first 15 telemetry cases; meanwhile idle

## 2026-10-21 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: `frontend/settings-ui` scaffolding (admin-gated layout, nine sections of 08 §3.2 with their `pipeline_config` keys, redirect and 404); 39 Vitest pass, build clean.
Blocked on: Review UI waits for S1's `backend/review/api_models.py`; Settings editing waits for S1's settings API; viewer body waits for S1 models/presign and S2 `resolve_anchor`; Open WebUI Pipe waits for S2's `/v1/answer` schema.
Needs from others: S1 and S2 to message S3 when those land on main; Lead to merge this branch (shell, viewer, settings scaffolding).
Next: idle until one of the inputs above arrives; then switch `get_auth_config` to S4's `require("console_auth")` once S4's settings merge is on main.

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: task 2: backend/sync/auth.py (Fernet-encrypted MSAL cache, mode 600/700, atomic writes, v1 cache refused untouched; silent-first TokenProvider; device-code sign-in that rejects any account but DCL_DELEGATED_USERNAME; check_access for the roots and the outside item) + GET-only backend/sync/graph_client.py; 28 unit tests; device flow verified live against the tenant with scope A. Test: `uv run pytest && uv run ruff check backend` (159 passed, 18 skipped)
Blocked on: nothing for code. Live sign-in and `check` need S4's config fields on main (S4 merge request 14c8c4d) and the operator: in .env set DCL_TOKEN_CACHE_PATH to a NEW v2 file under a 700 DCL_TOKEN_DIR (it still points at v1's cache, which the code refuses), add DCL_TOKEN_CACHE_KEY (Fernet key), optionally DCL_TEST_OUTSIDE_DRIVE_ID; then run `uv run python -m backend.sync.auth sign-in` and complete the code as ai@manastuspace.com, then `uv run python -m backend.sync.auth check`
Needs from others: Lead — merge S4's config fields; relay the operator step above to the user. Open for the health-check task: file 02 §1 probes `GET /me/drive`, which option A may refuse; I will confirm live once signed in
Next: task 3, delta crawl of the four roots (metadata only), folder tree and paths, gate tiers 1–3, HELD_BY_SCOPE

## 2026-10-21 20:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: `backend/llm_engine/local_models.py` + `backend/api/models.py` (EmbeddingGemma 2 text+image 768-d, bge-reranker-v2-m3, `ModelsClient`), 27 unit tests + 5 GPU tests green; throughput in `.wiki/backend/embedding-service.md`. Branch mapping: S2 = claude/infallible-swartz-58c96b.
Blocked on: nothing
Needs from others: S4: GPU image pins (torch 2.14.1 cu130, transformers 5.20.2, sentence-transformers 6.1.0, torchvision 0.29.1, pillow, numpy), HF cache volume, compose healthcheck on `/models/health` with ~60 s start period. Lead: pyproject `models` dependency group with the same pins.
Next: chunker + anchors + identifiers (S3 waits on `resolve_anchor`), then VisionService on S4's gateway client
## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: task 3 part 1: backend/sync/gate.py (tiers 1–3, reasons in the file 05 format) + scope.py (download-scope matcher), 49 unit tests. Test: `uv run pytest && uv run ruff check backend`
Blocked on: DCL Lead, for the rest of task 3 and the live sign-in. (1) The app dcl-reader-delegated has admin consent only for delegated Files.Read.All (v1 docs/GRAPH_SETUP.md, 13 Oct). .env sets DCL_PERMISSION_OPTION=A, which requests Files.SelectedOperations.Selected, so sign-in will most likely stop at "Need admin approval". Either set B (the security sign-off of file 02 §1 applies) or have an admin consent to A and grant the four folders. (2) M1 code reads sync.download_scope and processing.scope from pipeline_config, but file 05 §7 creates that table in M2–M3. Proposal: migration 0002 creates pipeline_config + v_config_current in M1. Who owns typed reads (file 10 §2 puts them in backend/config.py, S4)? (3) Gate source: config/gate.yaml (brief; S5 owns config/*.yaml, while my map page lists it in S1's workspace) seeds pipeline_config gate.* (file 05 lists gate.* keys)? (4) bbox convention for the contract: proposal `{page_no, x0, y0, x1, y1}` normalized 0..1 with a top-left origin, a list per node
Needs from others: S5 — config/gate.yaml in the GateConfig schema (docstring of backend/sync/gate.py; a test copy is in backend/tests/unit/sync/gate_test_config.yaml)
Next: backend/dispatcher/contract.py (publish-first item 2: S2 and S3 wait on it), then the delta crawl once (1)–(3) are answered

## 2026-10-21 20:05 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: config data + synthetic fixtures merged to main (3240cc6); branch synced; allowlist plan sheet reopened with the delegated method (S5 chooses from S1's crawl)
Blocked on: S1 folder-level listing of the real metadata crawl (requested 2026-10-21)
Needs from others: DCL S1 Backend — the listing (fields in `.wiki/plans/quality__fixtures__allowlist.md`); DCL Lead — answers to the three open questions of the previous entry
Next: on the listing, fill the 13 slots and send the table to DCL Lead for DECISIONS.md; meanwhile idle
