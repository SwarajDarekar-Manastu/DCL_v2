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

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: publish-first item 2: backend/dispatcher/contract.py (ProcessedDocument, ProcessedNode, ProcessedAsset, telemetry run/channel records, Mention, Flag with fingerprint, UnitHash, Anchor + the one copy of the <kind>:<value>:<hash> format) and the contract enums in backend/postgres/enums.py; 27 tests. Test: `uv run pytest && uv run ruff check backend` (470 passed, 18 skipped)
Blocked on: Lead answers of 100eae2 (permission option, pipeline_config in M1, gate source) for the delta crawl
Needs from others: S3 — import parse_anchor/format_anchor from backend.dispatcher.contract in backend/api/viewer.py and drop the local copies (one owner of the format, as S2 asked)
Next: backend/review/api_models.py (publish-first item 3, for S3), MinIO get/put for S2's vision cache, then the documents/nodes/assets models

## 2026-10-21 20:40 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: VisionService (`backend/llm_engine/vision/{service,schemas}.py`), prompt loader + nine v1 prompt files (`backend/llm_engine/prompts`), 23 tests on a mock gateway; full suite green.
Blocked on: nothing for code; real vision calls wait for S4's probe to enable image input
Needs from others: S1: `backend/storage/minio.py` get/put on dcl-cir (cache adapter), `document_nodes` model (resolve_anchor)
Next: chunker against S1's contract (ProcessedNode), anchors (make_anchor, resolve_anchor), identifiers
## 2026-10-21 20:05 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: config data + synthetic fixtures merged to main (3240cc6); branch synced; allowlist plan sheet reopened with the delegated method (S5 chooses from S1's crawl)
Blocked on: S1 folder-level listing of the real metadata crawl (requested 2026-10-21)
Needs from others: DCL S1 Backend — the listing (fields in `.wiki/plans/quality__fixtures__allowlist.md`); DCL Lead — answers to the three open questions of the previous entry
Next: on the listing, fill the 13 slots and send the table to DCL Lead for DECISIONS.md; meanwhile idle

## 2026-10-21 20:40 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `config/gate.yaml` for S1's GateConfig (file 02 §4 lists; `.1` kept as a string; `.xlsm` junk only under environment library folders, not `APS - Library`; `* (old)` quarantine), 44 tests incl. S1's real gate; config headers and the FMEA fixture aligned with the Lead's three decisions. Test: `uv run pytest backend/tests/unit/config_data backend/tests/fixtures && uv run ruff check backend`
Blocked on: S1 folder-level listing of the real crawl (allowlist); S1 rules YAML schema and CIR snapshot format (M2)
Needs from others: Lead — decide `.out` (LaTeX junk in 02 §4 vs ANSYS solver logs kept in 03 §11 step 5; archive members pass the same gate) and `.ini` (Tier-2 junk vs Tier-4 secret-scan list)
Next: allowlist from the crawl listing, then real fixtures and the first 15 telemetry cases; meanwhile idle
## 2026-10-21 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: viewer anchor codec delegated to `backend/dispatcher/contract.py` (S1 owns the format); `viewer_path()` unchanged, `parse_anchor_param` kept as an alias for S1's equivalence test; 437 backend tests pass.
Blocked on: Review UI waits for S1's `backend/review/api_models.py` (in progress); viewer body waits for S2's `resolve_anchor`; Pipe waits for S2's `/v1/answer` schema.
Needs from others: S1 may drop the equivalence test in `test_contract.py`, after which S3 deletes the alias.
Next: idle until one of the inputs above lands on main.
## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: publish-first item 3: backend/review/api_models.py (queue, case detail, the file 06 §6 resolution actions as a union on `action` with ALLOWED_ACTIONS, resolve/assign/reject/undo, dry-run, rules) + backend/api/review.py with every file 08 §4.4 review route typed and role-gated (501 until the M2 tables); review enums. Gate: S5's findings fixed (patterns must be strings; .xlsm only under lib/lib64/library/*-packages). Contract test no longer depends on viewer.py. Test: `uv run pytest && uv run ruff check backend` (498 passed, 18 skipped)
Blocked on: Lead answers of 100eae2 (permission option, pipeline_config in M1, gate source) for the delta crawl
Needs from others: nothing new
Next: backend/storage/minio.py get/put for S2's vision cache; then documents/document_sources/document_nodes/assets models (M2)



## 2026-10-21 21:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: unchanged since e109103 (gate.yaml merge requested)
Blocked on: Lead decision on dropping ".1" from the 02 §4 Tier-2 list (raised by S1): end-of-name matching junks team files such as "report_v1.1"; man pages only occur under Tier-1 paths. S5 agrees with dropping it; config/gate.yaml keeps it until the manual changes
Needs from others: Lead — the ".1" decision together with the open ".out"/".ini" question; S1 — the crawl folder listing
Next: idle until one of these arrives

## 2026-10-21 21:30 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `config/gate.yaml` without `.ini` and `.1` (manual at be5ce14), new cases for `report_v1.1` and instrument `.ini` files; 48 gate tests through S1's gate. Test: `uv run pytest backend/tests/unit/config_data backend/tests/fixtures && uv run ruff check backend` (230 passed)
Blocked on: S1 — `parent_kind` in GateConfig/GateInput (the `.wbpz` `.out` exception needs a key or a fixed rule) and the crawl folder listing
Needs from others: S1 — tell S5 whether the `.wbpz` exception is configured in gate.yaml (proposed key below in the message) or fixed in code
Next: idle until S1 answers or the listing arrives

## 2026-10-21 22:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: 31ed593 (gate.yaml header wording), not yet requested
Blocked on: Lead — the `.wbpz` `.out` exception: Lead ruled "fixed rule in code, no gate.yaml key"; S1 implemented a gate.yaml key `kept_endings_by_parent_kind` (S1 c861d3a, merge requested). S5 adds the entry and three decision cases once the Lead confirms which one stands
Needs from others: Lead — that confirmation; S1 — the crawl folder listing
Next: idle
## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: backend/storage/minio.py (BucketStore get/put for S2's vision cache, presign_get 15 min for S3, ensure_buckets, raw_key); 11 tests, the server tests green against S4's dcl-v2-minio:RELEASE.2025-10-15T17-29-55Z. Test: `DCL_TEST_MINIO_ENDPOINT=<disposable> uv run pytest && uv run ruff check backend`
Blocked on: Lead answers of 100eae2 for the delta crawl
Needs from others: S4 — CI service for a disposable MinIO with DCL_TEST_MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY, like the DB tests
Next: provisional evidence/suggestion models per flag type (S3 asked), then the M2 documents/nodes/assets models

## 2026-10-21 21:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: `backend/indexing/{chunker,anchors,identifiers}.py` (chunk_document, build_embed_texts, IndexNode, extract_identifiers, make_anchor, resolve_among), 47 tests; vision media resolution aligned with 03 §3.
Blocked on: S1 `document_nodes` model for `resolve_anchor` (S3's viewer waits on it)
Needs from others: S1: route node conventions in `.wiki/backend/chunker-and-anchors.md` (text as parent/child, every node needs a locator, run summaries t_start_ms 0); `IndexNode` is the commit input
Next: enrichment (extract, entities, numeric facts), then index_document and retrieval

## 2026-10-21 22:30 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `config/gate.yaml` with `kept_endings_by_parent_kind: {wbpz: [".out"]}` per the Lead's ruling; 5 archive-member decision cases through the documented rule and S1's gate (58 gate tests). Test: `uv run pytest backend/tests/unit/config_data backend/tests/fixtures && uv run ruff check backend`
Blocked on: S1 crawl folder listing (allowlist)
Needs from others: nothing else
Next: idle until the listing arrives

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: publish-first item 4: backend/review/rules.py (precedence resolver, typed bodies per rule_type incl. channel_map, config/rules YAML format); RuleDraft.body validated; also typed flag evidence (3db8ffa), MinIO store (e75440c), gate parent_kind (c861d3a). Test: `uv run pytest && uv run ruff check backend` (600 passed, 24 skipped)
Blocked on: Lead answers of 100eae2 (permission option, pipeline_config in M1, gate source) for the delta crawl and the downloader's dispatch step
Needs from others: nothing new
Next: downloader core (streamed SHA-256 + local quickXorHash, conflict-safe blob insert), job_key builder; then the M2 documents/nodes/assets models

## 2026-10-21 22:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: 31ed593 (gate.yaml header wording), not yet requested
Blocked on: Lead — the `.wbpz` `.out` exception: Lead ruled "fixed rule in code, no gate.yaml key"; S1 implemented a gate.yaml key `kept_endings_by_parent_kind` (S1 c861d3a, merge requested). S5 adds the entry and three decision cases once the Lead confirms which one stands
Needs from others: Lead — that confirmation; S1 — the crawl folder listing
Next: idle
## 2026-10-22 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `config/sanity_ranges.yaml` v2 for S1's channel_map body (a7cf42d): ordered ranges keyed by `physical_quantity` + `canonical_name_glob`, first match wins, same four manual values; selection cases on S1-style names. Test: `uv run pytest backend/tests/unit/config_data backend/tests/fixtures && uv run ruff check backend` (246 passed)
Blocked on: S1 crawl folder listing (allowlist); S1 CIR snapshot format (with the CIR writer)
Needs from others: nothing else; `config/rules/` stays empty until operator rules exist (format now known from S1)
Next: idle until the listing arrives

## 2026-10-21 22:45 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: `/v1/answer` SSE contract in `backend/api/engine.py` (request, seven event models, `to_sse`, HMAC identity, TraceView, example stream), 9 tests; endpoints 501 until M8.
Blocked on: S1 for enrichment (EntityType/NumericFactSource/Quantity enums, M4 entity models, `backend/common/units.py`) and for `resolve_anchor` (`document_nodes` model)
Needs from others: Lead: add `rapidfuzz` and `pint` to main dependencies and a `models` group (torch 2.14.1, torchvision 0.29.1, transformers 5.20.2, sentence-transformers 6.1.0)
Next: enrichment extraction schema, prompt and grounding (no DB), then entity normalization once S1's enums land
## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: task 4 core: backend/sync/downloader.py land_item() (zero-download link, tokenless 302 fetch, one-pass SHA-256 + quickXorHash, verify, content-addressed copy, conflict-safe blob insert); backend/postgres/session.py; Job.key_for(); quickxorhash dep. Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest && uv run ruff check backend` (627 passed, 3 skipped with both servers)
Blocked on: Lead answers of 100eae2 for the crawl and for dispatch after landing (processing.scope)
Needs from others: Lead — may the M4 entity tables (entities, entity_aliases, entity_mentions, numeric_facts) be created now? S2 is building enrichment in parallel and asked for the models
Next: backend/common/units.py (pint + config/units.txt, S2 needs it), S2's entity enums

## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: backend/common/units.py (pint + config/units.txt with S5's aliases, gauge/absolute from the spelling, canonical units bar/N/K/g/s/W, gauge→absolute, fits_quantity); enums EntityType, EntityCreatedBy, AliasCreatedBy, NumericFactSource, Quantity (one vocabulary for numeric facts, Route C and sanity ranges). Test: `uv run pytest && uv run ruff check backend` (640 passed, 28 skipped)
Blocked on: Lead answers of 100eae2 (crawl) and on whether the M4 entity tables may be created now (S2 asked)
Needs from others: nothing new
Next: M2 models documents/document_sources/document_relations/document_nodes/assets once the Lead confirms the table timing; otherwise Tier 4 (magic bytes, secret scan)

## 2026-10-21 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: `frontend/review-ui` MVP against S1's review API: queue (filters in the URL, impact sort, j/k/Enter, aging, live refresh), case view (typed evidence panes, consoles from `allowed_actions`, dry-run gate, folder-scoped rule in one resolve, assign/reject/undo), rules page; types generated from OpenAPI (`npm run gen:api`); `GET /assets/url` presign route. 75 Vitest, backend unit suite green; browser run against a mock API.
Blocked on: end-to-end resume needs S1's M2 tables; Audit page needs the audit route (proposed to Lead); viewer body needs S2's `resolve_anchor` DB wrapper.
Needs from others: Lead decision on GET /audit owner; S4 note: presigned URLs use DCL_MINIO_ENDPOINT, which must be reachable from browsers (or a public endpoint setting).
Next: Open WebUI Pipe against S2's /v1/answer contract (S2 branch 13c7c94, merge pending).

## 2026-10-22 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `config/sanity_ranges.yaml` v2 for S1's channel_map body (a7cf42d): ordered ranges keyed by `physical_quantity` + `canonical_name_glob`, first match wins, same four manual values; selection cases on S1-style names. Test: `uv run pytest backend/tests/unit/config_data backend/tests/fixtures && uv run ruff check backend` (246 passed)
Blocked on: S1 crawl folder listing (allowlist); S1 CIR snapshot format (with the CIR writer)
Needs from others: nothing else; `config/rules/` stays empty until operator rules exist (format now known from S1)
Next: idle until the listing arrives

## 2026-10-21 23:15 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: `backend/llm_engine/engine/{sanitizer,verifier}.py` (outbound IP sanitizer, numeric claim string check), 24 tests; GPU tests now skip when the shared card has < 3 GiB free (S4's dcl-v2-models container holds ~1 GiB while loading).
Blocked on: nothing (S1's enums and units.py are on their branch, merge requested)
Needs from others: S1: entity tables when the Lead rules on M4 timing
Next: enrichment extraction (schema, prompt, grounding, unit validation with S1's units.py)
## 2026-10-21 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: type resolution (4d9d56e) and the Tier 4 secret scan (pure functions, redacted previews). Test: `uv run pytest && uv run ruff check backend`
Blocked on: Lead answers: 100eae2 questions (permission option, pipeline_config in M1, gate source); creating the M2/M4 tables now; the document_nodes bbox column name
Needs from others: S4 — libmagic1 in the images, a disposable MinIO in CI
Next: after the answers: delta crawl, dispatch after landing, M2 tables, review flags write path

## 2026-10-22 — DCL Lead — main
Merged / ready: OneDrive delegated sign-in completed by the user (option B); v2 encrypted token cache exists; access check: all four roots HTTP 200, outside-share item 404 (pass). Gateway contract verified live and written to file 09 §H.1.
Blocked on: nothing
Needs from others: S4 to build ManastuGatewayAdapter per 09 §H.1; S1 to run the metadata crawl when it resumes
Next: merge rounds; relay S1's crawl listing to S5 for the allowlist
## 2026-10-21 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: not yet requested. Compose stack is on the branch and verified live: 13 services healthy (ParadeDB 0.26.2-pg17, Redis 8.6.7, MinIO built from the pinned archived tag, LibreOffice/unoserver, models with GPU, api, beat, six queue workers per file 10 §4), GPU visible only to `models`, all workers answer ping, no `.env`/key files in the backend image. `uv run pytest` green; `DCL_STACK_PROJECT=dcl-v2 uv run pytest backend/tests/integration/stack` 9 passed
Blocked on: nothing (session paused on usage limit)
Needs from others: nothing new
Next: add `libmagic1` to the backend image (S1 request), CI service MinIO + DCL_TEST_MINIO_* (S1 request), finish the compose-stack map page, delete plan sheet `platform__compose-stack__m0-stack`, request merge; tell S2 the models service uses `/models/health` with a 900 s start period and the `hf-cache` volume

## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: Compose stack (project `dcl-v2`) running on the dev host with the real `.env`: ParadeDB 0.26.2-pg17 (host 5435, db `dcl_v2`, migrated to head by the one-shot `migrate`), Redis (6381), MinIO from the pinned archived tag (9100/9101; `minio-init` creates the five buckets, versioning on dcl-raw/dcl-cir, vision-cache lifecycle, separate app user), LibreOffice/unoserver, models on the only GPU (8500), API (8200), beat, six queue workers per file 10 §4; in-network URLs set per container; token dir mounted only into `worker-io-light`; libmagic1 in the image; builder stage compiles `quickxorhash`. Test: `uv run pytest` green; `DCL_STACK_PROJECT=dcl-v2 uv run pytest backend/tests/integration/stack` 11 passed
Blocked on: nothing
Needs from others: S3 — Console SPA and Open WebUI service definitions (port 8600) when their builds exist
Next: gateway client rework to the verified Manastu contract (ManastuGatewayAdapter, X-API-Key, /generate, /stream; production-patterns checklist; real probe run), then CI (incl. disposable MinIO for S1's tests), observability, MinIO replacement comparison by end of M4

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: migration 0002 pipeline_config (+ typed access, gate seeding from config/gate.yaml), migration 0003 (document, node, asset, entity, fact, audit tables; HNSW), metadata crawl backend/sync/delta.py, S5's folder listing backend/sync/folder_listing.py, reviewer may deactivate rules. Test: `DCL_TEST_DATABASE_URL=… uv run pytest && uv run ruff check backend`
Blocked on: nothing. Live crawl of the four real roots is running against a disposable DB (read-only Graph, metadata only); the listing goes to S5 when it finishes; the crawl into the stack DB (5435/dcl_v2) follows once 0002/0003 are on main and the stack's migrate service has run
Needs from others: Lead — merge so the stack migrates to 0003
Next: tasks_sync.py (crawl/delta/download tasks on io_light), BM25 migration with S2, review_flags/rules tables

## 2026-10-22 01:05 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: allowlist chosen from S1's crawl listing: 11 folder-id entries, about 247 files (table in `.wiki/plans/quality__fixtures__allowlist.md`, sent to DCL Lead for DECISIONS.md); synthetic `c_telemetry/unlabeled_npy` fixture with a numpy cross-check (not yet requested; merges with the allowlist close-out)
Blocked on: Lead — (1) drop the `.npy` slot (all 6 corpus .npy are under `_to_delete`) or have the user move one; (2) accept the APU Heater substitute (no telemetry under that root); (3) non-English library documents: S1 first-page language/DOI check after download, or a ruling on M5's "two non-English brochures"
Needs from others: Lead — the three rulings and the DECISIONS.md entry; S1 — the library language/DOI check if the Lead agrees
Next: on the rulings, close the allowlist sheet, then copy small real fixtures from the allowlisted folders (user approval) and verify the first 15 telemetry cases with own Python over the raw .dat

## 2026-10-22 01:30 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: allowlist close-out (recorded by the Lead in DECISIONS.md; plan sheet deleted) and the synthetic `c_telemetry/unlabeled_npy` fixture that replaces the dropped .npy slot. Test: `uv run pytest backend/tests/unit/config_data backend/tests/fixtures && uv run ruff check backend`
Blocked on: nothing for the next task
Needs from others: S1 — first-page language/DOI check over the downloaded library PDFs (Lead ruling 3), and word when the allowlisted blobs have landed in MinIO
Next: real fixtures from E1–E11 (user approves the copies; nothing proprietary in git) and the first 15 telemetry cases verified with own Python over the raw .dat of E1–E3

## 2026-10-22 02:30 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `quality/acceptance` M1: checklist (M1.md) mapping all ten criteria; five automated read-only checks (crawl bands, decided-with-reason, downloads complete, scope = DECISIONS allowlist, dispatch only in scope) opt-in via `DCL_ACCEPTANCE=1`; snapshot/compare CLI for the rename/modify/410/re-run procedures; seven proofs on a disposable DB; M2 draft. Test: `DCL_TEST_DATABASE_URL=<disposable> uv run pytest backend/tests/acceptance` (7 passed; live checks skipped without opt-in)
Blocked on: S1 — E1–E11 downloads, the read-only `export_blobs` command, the file-level listing (real fixtures, telemetry cases); a 410-resync command and the M1 load-test harness (procedures 8, 10)
Needs from others: Lead — run the M1 live checks once downloads finish (`DCL_ACCEPTANCE=1 DCL_DATABASE_URL=<stack db> uv run pytest backend/tests/acceptance`), or give S5 a read-only DB URL
Next: idle until S1's export and listing arrive. Local test container `dcl-s5-test` (ParadeDB 0.26.2-pg17, 127.0.0.1:55435, throwaway credentials) runs for the seeded-DB proofs

## 2026-10-21 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: Review UI MVP merge requested (head 0d428b2) plus e0255ef (removed the parse_anchor_param alias). Open WebUI Pipe not started in code; research done against Open WebUI v0.12.3 source:
- `__user__` = user.model_dump() with `valves` = UserValves; no groups, which come from `await open_webui.models.groups.Groups.get_groups_by_member_id(user_id)` (`.name`). Manifold `pipes()` → model id `manastu_engine.main`. `__task__` is set for title/tags/follow-up calls, which must not reach the engine.
- Errors raised while the stream is consumed are not caught by Open WebUI. Yield `{"error": {"detail": ...}}` to get the error state (middleware: no choices + error). Events are status, source/citation (`{source:{id,name,url}, document:[...], metadata:[{source,name,url}]}`), embeds (`{embeds:[...], replace?}`), `chat:message:follow_ups`. A confirmation `__event_call__` returns the browser reply or `{"error": ...}`, so accept only `True`.
- Single-file install: functions cannot import siblings, so config.py and api_endpoint.py get inlined by a build script into dist/.
Blocked on: S2 to add trace_id to ConfirmationEvent (asked); owner of a chat-attachment upload endpoint (to raise with the Lead); Lead answers on GET /audit and on the GET /assets/url uri form.
Next: Pipe plan sheet, then frontend/openwebui/{config.py, api_endpoint.py, pipe_manastu_engine.py, build script}, with tests replaying S2's example_answer_stream.sse.

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: `frontend/openwebui-pipe`. The Pipe against S2's /v1/answer contract has config.py, api_endpoint.py (signed identity mirroring engine.sign_identity, SSE parser, confirm, trace), the event mapping checked against Open WebUI v0.12.3 source, and a single-file bundle in frontend/openwebui/bundled (build_functions.py --check). 27 tests replay S2's recorded stream through the source and the bundle; the engine's own pipe_identity accepts the Pipe's headers.
Blocked on: nothing for the Pipe; a live run waits for the engine (M8). Confirmations use trace_id once S2's c1641d5 lands (declined until then).
Needs from others: the Lead to decide the owner of a chat-attachment upload endpoint (the Pipe sends attachments=[]).
Next: GET /audit (approved, owner S3, 501 until S1's audit_events model) and the Audit page; then Actions (Show trace, Add to benchmark, Report issue) and the Filter.
## 2026-10-22 01:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: enrichment (`backend/llm_engine/enrichment/{extract,entities,numeric_facts}.py`, prompt `enrichment/parent.v1.md`), 37 tests; `resolve_anchor` over document_nodes; trace_id on ConfirmationEvent; torch-free local-model tests; vision cache on BucketStore; `indexing/tables.py`.
Blocked on: nothing
Needs from others: S1: who seeds `config/aerospace_synonyms.yaml` into entities/entity_aliases, and whether `sanity_ranges` is seeded into pipeline_config; your commit consumes `EntityDecisions` and `FactDecision`s
Next: index_document (chunk → enrich → normalize → facts → embed → hand to commit), then retrieval and the BM25 DDL for S1
## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: sync Celery tasks (tasks_sync.py), host download CLI + read-only export, sanity_ranges seeding (seed-config), get_session dependency for routers. Live in the stack: crawl into 5435/dcl_v2 matches the first run (110,867 items, 5,073 accepted, 0 orphans); processing.scope = the 11 E1–E11 folder ids, sync.download_scope = []; gate.* and sanity_ranges seeded; the 247 accepted files of E1–E11 landed in MinIO. Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest && uv run ruff check backend`
Blocked on: nothing
Needs from others: S4 — beat entries for the sync tasks (sent); S2 — BM25 DDL, entities.load_seed() on main for the seed-entities command
Next: download the rest of the accepted items (H11), Tier 4 on landed blobs, dispatcher (folder context, assembler, route gating, CIR writer), then Route C
## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: gateway client rework to the verified contract (ManastuGatewayAdapter default with X-API-Key, /generate, /stream; native and OpenAI adapters kept); production checklist on `.wiki/platform/gemini-gateway-client.md` implemented (retry classification incl. upstream codes in 502, jittered backoff, Retry-After, circuit breaker, per-model concurrency, idempotency key, timeouts, 20 MB inline guard, thought-signature echo, temperature dropped for 3.6+, estimated usage, quota stop); tests on recordings from the real gateway; real probe run wrote `gemini_capabilities.json`; beat schedule for S1's sync tasks. Test: `uv run pytest` green except S2's vision tests until S2 lands a one-line conftest fix (sent)
Blocked on: S2 conftest change (`GEMINI_API_STYLE="openai"` in their vision test settings) before this can merge green
Needs from others: operator — `.env` has `GEMINI_API_STYLE=gemini`; it must be `manastu` (or removed, the default) for the real gateway
Next: CI pipeline (incl. disposable MinIO for S1's tests), observability, MinIO replacement comparison by end of M4

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: 410 + forced resync (delta.py, CLI `resync`), downloader lock re-check, migration 0004 BM25 (S2's DDL). E1–E11 downloads landed (247). M1 procedure commands sent to S5. Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest && uv run ruff check backend`
Blocked on: nothing; asked the Lead whether to land the remaining ~4,826 items host-side or wait for the workers
Needs from others: S2 — seed_rows() on main (then seed-entities)
Next: dispatcher (folder context, assembler, route gating, document rows, CIR writer), Route C, queue load test
## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: CI pipeline v1 (`.github/workflows/ci.yml`: lint; disposable ParadeDB 0.26.2-pg17 + MinIO with `DCL_TEST_*`; schema gate = upgrade head + `alembic check` + FK-without-index; pytest; image build + layer secret scan), every step a script in `backend/devops/ci/` verified on the dev host; all four images clean against the real `.env` values. Correction to the previous entry: S2 needs no conftest change (S2's 455f896 replaces their mock), so merge S2's branch with or before this one
Blocked on: nothing
Needs from others: Lead — merge order S2 455f896, then this branch; first GitHub run happens after the merge
Next: observability (OTel, Prometheus metrics of file 02 §10, Grafana, alert routing), then backups/retention/runbooks, MinIO replacement comparison by end of M4


## 2026-10-22 03:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: nothing new; real-sample list (Tier A 12 files to git, ~570 KB incl. two trimmed .dat; Tier B local-only working copies) sent to DCL Lead for the user
Blocked on: the user's approval of the sample list and whether the repository is private; DCL Lead or S1 running `backend.sync.export_blobs` into S5's scratchpad (S5 does not use stack credentials, Lead ruling)
Needs from others: Lead — the approval and the export run
Next: on approval, trim and commit Tier A with expected.yaml; verify the first 15 telemetry cases from Tier B with own Python

## 2026-10-22 03:40 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `config/sanity_ranges.yaml` per the Lead ruling (feed/valve/tank 0–400 bar, general pressure 0–700 bar, `checks_external_kept` so external facts see only the general range; Route C values unchanged); M1.md procedures 6–9 with S1's commands. Test: `uv run pytest backend/tests/unit/config_data backend/tests/fixtures && uv run ruff check backend`
Blocked on: the user's answer on the sample list (repository is public: Lead recommends Tier B only)
Needs from others: S2 — read `checks_external_kept` for external facts and the role id for internal facts (message sent)
Next: on the answer, export and verify the telemetry cases; meanwhile idle

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: viewer endpoint wired to real tables (`build_viewer_payload` over documents, document_sources, drive_items, assets and S2's `resolve_anchor`; 404/400; page render with cited boxes, code, photo, video, text views); `GET /audit` over audit_events (reviewer, filters, cursor) and the Console Audit page with a case History link; Pipe replay test updated for the confirmation now in S2's example stream. 80 Vitest, 918 backend unit, 12 integration tests on a disposable ParadeDB (container dcl-s3-test, 127.0.0.1:55436).
Blocked on: nothing. Open: `open_flags`/`review_case_key` in the viewer and the end-to-end re-index check wait for S1's review_flags and commit path; chat-attachment upload owner (Lead).
Needs from others: nothing new.
Next: Open WebUI Actions (Show trace, Add to benchmark, Report issue) and the Filter.

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: nothing new since the viewer/audit merge request.
Blocked on: Open WebUI Actions. Show trace needs GET /v1/traces?chat_id&message_id and Report issue needs POST /v1/traces/{id}/feedback (both asked of S2 2026-10-22). Add to benchmark and the Benchmark UI need the benchmark enums (category, case/run status, failure class) in backend/postgres/enums.py and the benchmark_cases/runs/results models (S1's area; owner and timing asked of the Lead).
Needs from others: Lead decision on the Filter of 08 §1, which the signed groups in the Pipe make redundant today (proposal: defer it until attachments exist).
Next: idle until S2's trace routes or the benchmark models land.

## 2026-10-22 02:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: hybrid retrieval `backend/indexing/retrieval.py` (exact/HNSW dense, per-language BM25 on pg_search 0.26.2, RRF, parent collapse, rerank + fallback, near-dup collapse), 11 DB tests on a disposable ParadeDB; `seed_rows()` for S1; triage thinking settled with S4.
Blocked on: nothing
Needs from others: S1: the BM25 migration with the DDL sent today (field names verbatim); S5: `retrieval_set.yaml` (40 queries with gold anchors) for recall@30
Next: index_document (end-to-end tail into S1's commit), then the Retrieval-lab data for S3, then Route A1
## 2026-10-22 04:10 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `config/sanity_ranges.yaml` general fallback per quantity (Lead ruling): force_general 0–5,000 N, temperature_general 0–3,500 K, mass_flow_general 0–5 kg/s, power_general 0–50 kW, `pressure` renamed `pressure_general`; role ranges keep the Route C values and no longer check external facts. Test: `uv run pytest backend/tests/unit/config_data && uv run ruff check backend`
Blocked on: the user's answer on the sample list
Needs from others: nothing new (S2 told of the id rename)
Next: on the answer, export and verify the telemetry cases; the retrieval set once allowlisted documents are indexed (S2's anchor format received)

## 2026-10-22 03:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: `backend/indexing/index_document.py` (ProcessedDocument → IndexPlan: chunk, enrich per parent, entities, facts, route mentions, question proxies, headers, vector reuse, image vectors, aggregation), 11 tests; trace lookup and feedback routes for S3; sanity range by origin and role.
Blocked on: nothing
Needs from others: S1: `commit.py` consuming `IndexPlan` (shape in `.wiki/backend/chunker-and-anchors.md`); the pipeline task that calls `index_document`
Next: Retrieval-lab data for S3, `tasks_embed.py`, then Route A1 (pre-flight, triage, Docling by script)

## 2026-10-22 04:40 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: fixture generator pins openpyxl's standard-library writer, so the byte-stable check passes with lxml installed (S2 finding; verified with `uv run --with lxml`). Test: `uv run pytest backend/tests/fixtures && uv run ruff check backend`
Blocked on: the user's answer on the sample list
Needs from others: nothing new
Next: idle until the answer

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: download fixes (temp version removal, ASCII metadata, resilient host run), presign_put, migration 0005 (rules, review_flags), 0006 (benchmark tables, S3 unblocked), Tier 4 on landed blobs (inspect.py), UTF-16 text detection. Live: 726 landed items inspected, 0 secrets, 3 real mismatches (JPEG bytes in .png). Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest && uv run ruff check backend && uv run ruff format --check <S1 paths>`
Blocked on: nothing. Accepted corpus = 5,072 items, 24.0 GB (19.45 GB downloadable + one 4.57 GB held video; videos 13.4 GB in total); host download in progress
Needs from others: S2/S5 — `ruff format --check backend` fails on 4 of their files (llm_engine/vision/service.py, tests/acceptance/m1_state.py, tests/acceptance/test_m1_checks_on_seeded_db.py, tests/fixtures/test_fixture_integrity.py)
Next: dispatcher (folder context, assembler, route gating, documents/document_sources rows, CIR writer), then Route C
## 2026-10-22 04:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: Route A1 pre-flight and page triage (`backend/routes/a1_office/{preflight,triage}.py`), 19 tests on S5's fixtures; Retrieval-lab endpoint `POST /v1/retrieval/search`.
Blocked on: nothing
Needs from others: Lead: a `parse` dependency group (pypdfium2==5.14.0, pikepdf==10.17.0; docling next) — tests skip without them; S4: Tesseract (osd + Latin/Cyrillic/Devanagari/Arabic traineddata) and RapidOCR in the parse image; S5: openpyxl lxml writer makes byte-stable xlsx fixtures drift once pikepdf (lxml) is installed (told S5)
Next: A1.3 Docling conversion by script group, then tables QA, figures, handwriting, page map
## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready (after S1's presign_put lands): Open WebUI actions Show trace and Report issue (manastu_actions bundle, against S2's trace routes); chat attachments in the Pipe (only the user's own files, size cap, failures skipped) and `POST /assets/upload` (Pipe identity, 25 MB, slot in dcl-exports/uploads/{user}/{uuid}). 57 Open WebUI tests pass on source and bundle.
Blocked on: S1's presign_put (2827fa9, merge requested). backend/api/assets.py imports it, so this branch is not mergeable until it is on main.
Needs from others: Lead answers on the benchmark enums/tables owner and the Filter deferral.
Next: on S1's message, sync, run the asset tests and full suite, delete the attachments plan sheet, request the merge.

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: Open WebUI actions (Show trace, Report issue), chat attachments via `POST /assets/upload` (now on S1's presign_put), format-stable bundles, regenerated Console API types. Backend unit 998 passed, integration 11, frontend 80; ruff check and format clean on S3 paths.
Blocked on: Benchmark API waits for S1's migration 0006 (benchmark tables, merge requested); Retrieval lab screen waits for S2's /v1/retrieval/search (merge requested).
Needs from others: nothing new.
Next: Benchmark API the day 0006 lands, then the Benchmark UI with the Retrieval lab.

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: dispatcher v1 (folder context, assembler, routing with gating and flags, dcl.process.dispatch), migrations 0006 (benchmark) and 0007 (documents.route nullable). Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest && uv run ruff check backend` (1,144 passed with servers)
Blocked on: Lead — `drive_items.previous_blob_sha256` column for supersession (asked)
Needs from others: nothing
Next: after the merge: live dispatch over E1–E11 on the stack DB; supersession once answered; then Route C. Host download stopped (stack workers continue the remaining ~4,100 at ≤8 parallel)

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: supersession per the Lead's decision: migration 0008 drive_items.previous_blob_sha256, land_item rule, apply_supersessions after each dispatch, sweep_documents safety net (task dcl.process.sweep_documents). Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest && uv run ruff check backend` (295 S1 DB tests)
Blocked on: S4 — stack redeploy from main before the live dispatch over E1–E11
Needs from others: S4 — beat entries dcl.process.dispatch (every 30 min) and dcl.process.sweep_documents (daily)
Next: live dispatch + counts; Route C

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: Benchmark API over migration 0006. backend/benchmark/catalog.py (CaseSpec, models, queries; S3 file in S2's package, flagged to the Lead) and backend/api/benchmark.py (15 thin routes). It covers suites, versioned cases with audit, Pipe-only chat drafts, run snapshots, results, compare, and export/import. 1018 backend unit tests and 16 ParadeDB integration tests pass; Console types regenerated (benchmark `CaseList` renamed `BenchmarkCaseList` to avoid the OpenAPI clash with review).
Blocked on: nothing.
Needs from others: S2 to confirm the runner contract (queued → running → completed, results with failure_class and metrics, aggregate keys); S5 to author suites in the SuiteExport format.
Next: Benchmark UI screens and the Retrieval lab.
## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: live dispatch over E1–E11 on the stack DB (0008): 182 documents WAITING_FOR_ROUTE (A1 25, A2 23, B 4, C 40, D 84, E 2, F 4), 44 parts, 1 visual twin, 8 SOFT CONFLICTs, 0 HALTED. Fixes from the live run: ZIP-member typing in dispatch (18 xlsx/docx had gone to G; repaired with `retype`), .scdoc, LaTeX includes vs ancestor folders, orphan wording; `reassemble` command. Downloads (stack workers): 1,729 landed, 3,343 pending
Blocked on: nothing
Needs from others: nothing
Next: Route C

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: Route C step 1 for LabJack .dat/.dat_fail. A run streams to `dcl-telemetry/{run_uuid}/raw.parquet` (ZSTD, 100k-row groups), with per-channel stats, actual rate, gaps and duplicates. `v*` channels are volts; every other channel resolves through `channel_map` rules or gets UNIT_AMBIGUITY HARD. The validation gate (`backend/review/staged.py`) then halts the document with a staged payload. New: the adapter registry, release of parked documents on dispatch, and `dcl.process.route_c` on telemetry_stream. pyarrow, duckdb, numpy, pint, pyyaml, openpyxl and nptdms are now main dependencies, so the backend image needs a rebuild. Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest` (1,210 passed, 20 skipped).
Read-only census of the stack: 20 of the 40 waiting C documents are LabJack (18 .dat, 2 .dat_fail, 819 MB). The other 20 (12 xlsx, 4 cfg, 2 csv, 2 tdms) wait for step 2 adapters. Dry run on real data: 628 MB, 3.79 M rows in 3.7 s; 16 channels per file, 8 of them y* with no unit.
Blocked on: merge + stack image rebuild, then `routes.C.enabled = true` on the stack and a re-dispatch (live counts follow)
Needs from others: Lead: approval for the `telemetry_runs`/`telemetry_channels` migration (step 2); S4: rebuild the worker image after the merge
Next: live Route C run and counts; then step 2 (normalized Parquet, t0, metrics, catalog tables, commit path) and the A1/D/F adapter wiring S2 published

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: Benchmark UI. Suites, cases with drafts to approve, the case editor covering every CaseSpec field (edit = new version), the results dashboard with a baseline ribbon, failure classes, per-category counts and newly failing cases, the drilldown, compare runs and the Retrieval lab over S2's /v1/retrieval/search; run pages refresh on the live `run` topic. 90 Vitest; check and build clean; browser run against a mock API.
Blocked on: nothing. A real benchmark run waits for S2's runner (M10).
Needs from others: S2 to publish `run` events (progress, finished) through publish_event when the runner lands.
Next: Open WebUI "Add to benchmark" action against POST /benchmark/drafts; Settings editing once S1 publishes the settings API.

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: "Add to benchmark" Open WebUI action. It prefills a draft from the trace (verified numeric claims, cited pages, tools) and posts it to POST /benchmark/drafts; the prefill is tested against the API's DraftFromChat model. 68 Open WebUI tests pass on source and bundles.
Blocked on: nothing. Settings editing waits for S1's settings API; live Pipe and actions wait for the engine (M8).
Needs from others: nothing new.
Next: idle until S1's settings API, or new tasks.
## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: observability (telemetry module + metric catalogue of file 02 §10, collector, Prometheus + 7 operational alerts with promtool tests, Alertmanager → Teams, Tempo, Grafana dashboard; verified live in a throwaway project); `parse` image for cpu_parse (Docling 2.141 + RapidOCR + onnxruntime on CPU torch, Tesseract OSD + Latin/Cyrillic/Devanagari/Arabic; scanned page OCR'd correctly by both engines); `HF_HUB_DISABLE_XET=1` in model images; `_incoming/` lifecycle rule; S1's process schedules; parse image in CI scan. Stack on the host runs main 65dd09f at migration 0008. Test: `uv run pytest` green (alert-rule tests need Docker)
Blocked on: nothing
Needs from others: Lead — approve `DCL_GRAFANA_ADMIN_PASSWORD` (secret) and compose-only `DCL_GRAFANA_PORT` (default 3300); note `models`/`parse` groups now conflict in uv (sync one at a time); S1 — call `backend.common.telemetry.METRICS` from the sync code; host disk at 91%
Next: backups (PostgreSQL base + WAL, MinIO versioning checks), retention jobs, remaining runbooks; MinIO replacement comparison by end of M4

## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: nothing new since a19ad4f (merge requested)
Blocked on: DCL Lead / user decision before backups (brief task 6, file 05 §6, 10 §3 prod): (1) backup destination off this host's NVMe (disk at 91%; same-disk copies do not survive a disk loss): NAS path, second disk, or an S3-compatible bucket elsewhere; (2) RPO/RTO targets; (3) tool: S4 recommends WAL-G (base backups + continuous WAL to an S3-compatible target, point-in-time restore) over pgBackRest for its smaller footprint; (4) `backend/sync/retention.py` sits under S1's `backend/sync` although the backups map lists it for S4 — who owns it?
Needs from others: answers above; approval of `DCL_GRAFANA_ADMIN_PASSWORD` / `DCL_GRAFANA_PORT`
Next: backups and restore drill once answered; MinIO replacement comparison by end of M4

## 2026-10-22 06:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: Route A1 for PDFs end to end (`backend/routes/a1_office/{convert,structure,metadata,figures,tables_qa,handwriting,route}.py`): Docling runs by OCR plan with the second pass and `transcribe_page`, structure with references as mentions, L1 metadata, figure readings, table A/B QA, handwriting with critical-field HARD flags, CIR and assets; 67 route tests (Docling on S5's digital fixtures).
Blocked on: nothing
Needs from others: S1: the dispatcher's adapter call into `process_pdf` and `IMPLEMENTED_ROUTES` (signature in `.wiki/backend/route-a1-office.md`); `critical_field_patterns` from pipeline_config
Next: A1.0 visual twin + page map, DOCX/PPTX, rotation; then Routes D and F; then the answer workflow

## 2026-10-22 05:10 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: M1.md row 10 with S4's queue load-test procedure and expected report (from S4, at the Lead's request)
Blocked on: the user's answer on the sample list
Needs from others: nothing new
Next: idle until the answer
## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: dead-letter list + poison-task stop for every task (`DclTask` in `backend/celery_redis/app.py`; `Queue.DEAD_LETTER` removed, the list is `dcl:dead_letter`, read with `dead_letters()`); M1 queue load test harness `backend/devops/ci/queue_load_test.sh` + `backend.celery_redis.load_test` — passed on a throwaway project (5,002 tasks, no loss, no misrouting, 54 dead letters as planned, kills confined to telemetry_stream); 24 h lifecycle on `dcl-exports/uploads/` (applied live). Test: `uv run pytest` green
Blocked on: backups questions (destination, RPO/RTO, tool, retention ownership) with DCL Lead
Needs from others: S5 — add the load-test command and expected output to `backend/tests/acceptance/M1.md` row 10 (sent); S3/S1 — Console "Failed tasks" page reads `dead_letters()`
Next: office conversion client for S1/S2 (`backend/common/office.py`, env name pending Lead), then backups once answered
## 2026-10-22 07:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: Route D (`backend/routes/d_photos.py`, `classify_image` capability) and Route F (`backend/routes/f_video.py`), 17 tests; Route A1 for PDFs requested earlier.
Blocked on: nothing (A1 DOCX/PPTX waits for S4's `backend/common/office.py`, signature agreed)
Needs from others: Lead: parse/media deps pillow-heif==1.8.1, imagehash==4.3.2, faster-whisper==1.2.1; S1: dispatcher calls for `process_photo` (with `cluster_photos` in the assembler) and `process_video`
Next: the Answer Engine workflow (query analysis, planner, tools T1–T6/U1–U2, synthesis, verifier, DBOS)

## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: office conversion for S1 and S2: `backend/common/office.py` `convert(data, from_ext, to, *, recalc=False)` against the libreoffice container, which now runs `office_server.py` (one soffice run per request, profile that recalculates formulas on load) instead of unoserver (unoserver cannot load .xlsx on LibreOffice 7.4, inline or by path). Verified live: rtf/doc → docx, docx → pdf, xls → xlsx, xlsx recalculation (stale 999 → 81), S5's FMEA fixture → pdf; PPT/PPTX untested (no sample). Env name `DCL_OFFICE_URL` used, pending Lead approval. Test: `uv run pytest` green
Blocked on: backups questions with DCL Lead
Needs from others: Lead — approve `DCL_OFFICE_URL`, `DCL_GRAFANA_ADMIN_PASSWORD`, `DCL_GRAFANA_PORT`; merge 31eb0be + this
Next: backups once answered; MinIO replacement comparison by end of M4
## 2026-10-22 09:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: engine tools T1 search_documents, U1 get_document, U2 catalog_lookup, T4 code and diagrams, T5 physics_calculator (`backend/llm_engine/engine/tools/`), 17 tests; one `Provenance` enum (adds `calculation`); retrieval test on migration 0004. (Route wiring now goes through S1's adapter registry in `backend/dispatcher/adapters.py`, not IMPLEMENTED_ROUTES.)
Blocked on: nothing
Needs from others: S1: telemetry_runs/channels and Parquet for T2; the diagram catalog shape in `.wiki/backend/answer-engine.md` for Route E; S4: whether the gateway proxies Google Search grounding for T6
Next: T2/T3/T6, then query analysis, synthesis, entailment verifier, workflow + DBOS, /v1/answer streaming

## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: Google Search grounding capability (e911384; probe re-run with the real `.env`, 9 capabilities enabled); office client (96cec91); dead letters + M1 load test (31eb0be); observability + parse image (a19ad4f) — all on this branch, merge requested
Blocked on: backups questions with DCL Lead
Needs from others: Lead approval of `DCL_OFFICE_URL`, `DCL_GRAFANA_ADMIN_PASSWORD`, `DCL_GRAFANA_PORT`
Next: MinIO replacement evaluation, hands-on (bucket versioning, prefix lifecycle, presigned GET, DuckDB httpfs, via the same minio-py client) against pinned candidates rustfs/rustfs:1.0.3, chrislusf/seaweedfs:4.48, dxflrs/garage:v2.4.1, MinIO as baseline; written comparison to the Lead by end of M4

## 2026-10-22 05:40 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: real samples local only (decision 2026-10-22): `backend/tests/fixtures/real_samples.yaml` (93 files of E1–E11, registry sha256), export procedure in the fixtures README (git-ignored `data/samples/<entry>/`), `test_real_samples.py` (manifest checks; local copies when present). Test: `uv run pytest backend/tests/fixtures && uv run ruff check backend`
Blocked on: an operator export into S5's worktree `data/samples/` (S5 has no stack credentials)
Needs from others: DCL Lead — run the README export commands with the output under /home/ai/Desktop/Swaraj_/dcl_v2/.claude/worktrees/strange-bhaskara-1dd439/data/samples/
Next: verify the copies, then the first 15 telemetry cases with own Python (Flash-Lite id for any model-naming case: gemini-3.1-flash-lite)

## 2026-10-22 06:10 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: real-sample manifest moved to git-ignored `data/samples/real_samples.yaml`; committed `real_samples.template.yaml` (91 distinct files, no names) checked by sha256; README export wrapper loads `.env`; E1–E3 copies verified against the registry. Test: `uv run pytest backend/tests/fixtures && uv run ruff check backend`
Blocked on: nothing
Needs from others: nothing now (E4–E11 export later, on request)
Next: the first 15 telemetry cases from E1–E3 with own Python verification

## 2026-10-22 07:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: real samples trimmed per the user rule (one file per supported type, chosen by extension and name only, plus the telemetry runs of the benchmark cases): 18 files, ~69 MB; README export list cut to E1–E7. Test: `uv run pytest backend/tests/fixtures && uv run ruff check backend && uv run ruff format --check backend`
Blocked on: S1 — one `.pptx` and one `.zip` from the registry (not in the allowlist folders)
Needs from others: Lead — export E4–E7 into S5's `data/samples/` when convenient
Next: telemetry suite (option b: values in git-ignored data/benchmark/) and the two halt behaviour cases

## 2026-10-22 08:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: first 15 TELEMETRY_MATH golden cases + 2 HALTED_DATA_BEHAVIOR cases (TP7 Test 01, Injector 10, Injector 14): committed template without values, `telemetry_metrics.py` verification + `build`, recompute test; values in git-ignored `data/benchmark/` (option b); all 17 validate against S3's `CaseCreate`; TP7 values match the team workbook. Test: `uv run pytest backend/tests/benchmark && uv run ruff check backend && uv run ruff format --check backend`
Blocked on: Lead — index-state precondition for the numeric cases (runs halt until SME channel-map rules) and whether S5 drafts those rules; hold-out subset to record
Needs from others: Lead — tell S4 the suite exists (`data/benchmark/telemetry.json`); export X1/X2 samples
Next: remaining golden categories and the 40-query retrieval set (need indexed documents and S2's engine mode)

## 2026-10-22 14:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: Answer Engine workflow increment. Planner `backend/llm_engine/engine/playbooks.py`, `AnswerWorkflow` in `backend/llm_engine/engine/workflow.py` (analysis → plan → tools in parallel → insufficient-evidence check → synthesis + verification; chit-chat, clarification, extractive fallback; trace record), `POST /v1/answer` streams it (`backend/api/engine.py`, 503 when unconfigured or not installed). Prompts `physics_args.v1`, `chitchat.v1`. Runs under DBOSRuntime (tables in schema `dbos` of the DCL database, self-migrated). Under DBOS stream writes arrive out of order, so frames carry `seq` and `ordered()` restores them. 15 new unit tests + 1 DBOS DB test. Flash-Lite = gemini-3.1-flash-lite (a125d60, probed: MINIMAL works).
Blocked on: nothing
Needs from others: S4: dependency group with `llama-index-workflows==2.25.0`, `llama-agents-dbos==0.7.0`, `dbos==2.31.1`, verified together (dbos 3.0–3.3 break llama-agents-dbos 0.7.0: "Queue objects cannot be constructed directly"; workflow tests skip until installed); GEMINI_MODEL / GEMINI_LITE_MODEL settings. Lead: call `start_engine()` / `stop_engine()` from the API lifespan in `backend/main.py` (role api|all). S1: `answer_traces` table (M8) for the trace record (columns in `.wiki/backend/answer-engine.md`); until then traces are logged.
Next: engine restart-resume test, T2 query_telemetry when S1's telemetry tables land, T6 external_search (grounding, sanitized query only), T3; Skills markdown

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: Route C step 1 is on main (1d7eae6). routes.C stays off on the stack until S4 confirms the worker image rebuild.
Blocked on: Lead / SME decision. The approved channel_map derivation from "Data format.xlsx" cannot be done. That workbook is a template for the report's summary metrics, for example "Feedline Pressure - Before Firing (Bar) [Gauge]" and "AUC Mean Thrust (N)". It never names a LabJack channel. Setup.xlsx lists the instruments, also without channels. The folder's LJStreamM.cfg (file 03 §C.0) carries only the scaling per channel, for example `y=a*24.943-12.385`. The y* columns in the .dat already have it applied, which I verified on real data. No file in E1–E11 gives a channel's quantity or unit. The slopes do match Setup.xlsx: y0–y2 are about 25 bar/V (100 bar sensor, 0.5–4.5 V), y3–y4 are 2.995 bar/V (30 bar sensor, 0–10 V) and y6 is 50.044 N/V (the load cell, per the TP37 spec). y5 (120·v + 0.721) and y7 (10·v) match no listed instrument.
Question: (A, recommended) The .cfg scaling and these slope matches go into each UNIT_AMBIGUITY flag as evidence and suggested resolutions. The flags stay HARD, and one operator rule per folder or root in the Review Console resolves all its runs. No derived rule claims a unit that no file states. Or (B): the SME supplies the y0–y7 assignment per rig (canonical name, quantity, unit, gauge/abs), which I load as operator rules. Or both: B for the known rigs, A for everything else.
Needs from others: Lead: choose A, B or both; for B, the SME's channel table
Next: on the answer: the telemetry_runs/telemetry_channels migration (approved), normalized Parquet, t0, metrics, the commit path

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: nothing new
Blocked on: nothing. The question in the entry above is withdrawn on the user's instruction: the plan and decisions stand. Channels with no stated unit stay UNIT_AMBIGUITY HARD until an operator rule resolves them (file 06). The folder's .cfg scaling is attached as evidence (file 03 §C.0/C.1). Nothing is derived from Setup.xlsx or Data format.xlsx, because not every folder has them.
Needs from others: nothing
Next: Route C step 2: the telemetry_runs/telemetry_channels migration (approved), .cfg scaling evidence, normalized Parquet, t0, metrics, the commit path
## 2026-10-22 09:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: proposed channel-map rules for E1–E3 in `config/rules/proposed/` (names, quantities, units, sensor ranges; status proposed, never applied until confirmed); `test_config_rules.py` (S1 loader, units, sanity-range selection); precondition in every numeric golden case's notes. Test: `uv run pytest backend/tests/unit/config_data backend/tests/benchmark && uv run ruff check backend && uv run ruff format --check backend`
Blocked on: nothing
Needs from others: S1 — keep the future config/rules loader to the top level (never `proposed/`) or add an explicit status field; SME — confirm the proposals in the Review UI
Next: remaining golden categories and the retrieval set once allowlisted documents are indexed (S2 engine mode)

## 2026-10-22 09:40 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `open_threshold: 2.5` on the valve channel of the three proposed channel maps (S1 field, ab00628); verification README states the full valve-open window (`valve_signal = 1`). Merge AFTER S1's ab00628: on current main the rules test fails because the field is unknown there; on S1's code all 7 rule tests pass
Blocked on: S1's ab00628 reaching main
Needs from others: Lead — merge order S1 ab00628, then this branch
Next: idle until indexed documents and S2's engine mode exist

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: Route C step 2 (merge requested). It adds:
- migration 0009 for telemetry_runs and telemetry_channels;
- the folder .cfg scaling as flag evidence;
- normalized.parquet (SI units, t_rel_ms, t_from_ignition_ms, a separate *_bar_abs column, valve state 0/1 at open_threshold);
- t0 per §C.6, the three-tier metrics, S5's sanity bounds, and the first commit path (backend/indexing/commit.py with S2's index_document);
- resume of a HALTED run from its own raw.parquet, a retroactive pass per rule, and ExportedRule.status (only operator rules load).
Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest` (1,353 passed).
Live Route C step 1 on the stack: routes.C enabled after S4's rebuild, then re-dispatched. 20 LabJack runs processed, 0 FAILED, all 20 HALTED with 160 UNIT_AMBIGUITY HARD (8 y* channels each). That is 4,936,500 rows, 4,852.8 s of data, 256 MB of raw Parquet, 1017.3 Hz everywhere, no gaps or duplicate timestamps, and 2 FAILED_RUN (.dat_fail). The other 20 C documents (12 xlsx, 4 cfg, 2 csv, 2 tdms) stay parked for their adapters. Four TP7 phase files (Test 01 priming, main, priming_i, purging) share the label TP07_T01; the commit renames them with a CONFLICT SOFT.
Blocked on: nothing
Needs from others: S4: apply 0009 on the stack DB after the merge and redeploy; an SME confirmation of S5's proposed channel maps (each confirmed rule resumes its runs through dcl.process.resume_for_rule); the telemetry workers need EmbeddingGemma's tokenizer (transformers) for index_document's token counts, or the models role exposes a token count
Next: the review API resolve endpoint (rule creation → resume_for_rule), then the xlsx/csv/tdms adapters; A1/D/F adapter wiring for S2's routes
## 2026-10-22 10:30 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: behaviour suite (6 cases: Isp with a dead thrust channel and a non-existent test plan → insufficient evidence; out of scope; clarification of "Test 01"; Moog thrust range and TP7-vs-vendor → external labelling) and `build_suites.py` (committed template + git-ignored fragments; `numeric_from` reuses telemetry values); tool names checked against the engine's ToolName. Test: `uv run pytest backend/tests/benchmark && uv run ruff check backend && uv run ruff format --check backend`
Blocked on: indexed allowlist documents (doc lookups, code, failure/visual, multilingual, the retrieval set's gold anchors) and standards in the processing scope (STANDARDS cases)
Needs from others: Lead — a ruling on STANDARDS cases: no ECSS/standards folder is in the allowlist, so those cases wait for M6 or a scope addition
Next: page-cited FACT_LOOKUP and CODE cases from the exported E3–E5 documents
## 2026-10-22 16:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: restart-resume test (`backend/tests/integration/llm_engine/engine/test_workflow_restart.py` + `_restart_worker.py`): an engine process killed inside the tool step is recovered by a new process; query analysis is replayed from the DBOS journal (asked once), the tool reruns, the run ends SUCCESS with the same trace id and the trace is saved. Engine map rubric item checked; durability note on the map.
Blocked on: nothing
Needs from others: S4's 07965fd (GEMINI_MODEL / GEMINI_LITE_MODEL) on main, then I switch vision, analysis, synthesis, enrichment to the settings
Next: T6 external_search (grounding, sanitized query only, external_queries in the trace), T2 when S1's telemetry tables land, T3, Skills

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: E12 on the stack, per the Lead's revised ruling. processing.scope now holds the 11 folder ids plus 8 ECSS path globs, one file each. The first, whole-folder E12 dispatch (141 WAITING A1 documents, before the correction arrived) was undone: 133 untouched documents were removed, with no flags and nothing derived, and the 8 standards stay. A re-dispatch creates nothing. Stack documents: A1 33, A2 23, B 4, C 40 (20 HALTED, 20 waiting for adapters), D 84, E 2, F 4.
Blocked on: nothing
Needs from others: nothing new
Next: as in the entry above

## 2026-10-22 12:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: documents suite (12 FACT_LOOKUP + 3 FAILURE_ANALYSIS, page-cited, from the TP-23 and TP12 reports) and code suite (8 CODE cases on the TP7 test-plan creator); questions committed without facts or file names, answers and citations local; a test finds every expected number/entity in the cited PDF page or source file. E12 chosen: 8 ECSS standards as path globs (sent to S1). Golden set now 44 cases (15 telemetry incl. 2 halt-behaviour… see map). Test: `uv run pytest backend/tests/benchmark && uv run ruff check backend && uv run ruff format --check backend`
Blocked on: indexing of E12 standards (STANDARDS cases); indexed corpus for CONFLICT and the retrieval set
Needs from others: S1 — E12 globs into processing.scope
Next: visual/handwriting cases from the exported TP7 sheets and E7 photos; multilingual cases (none in the allowlist: synthetic German/Japanese fixtures only)

## 2026-10-22 13:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: visual suite (5 VISUAL handwriting reads, 2 FAILURE_ANALYSIS, 1 CONFLICT_BEHAVIOR from the TP7 preheat and de-integration sheets); image-only citations must have a recorded visual reading (local); proposals carry `status: proposed` per rule. Golden set: 54 local cases (telemetry 17, behaviour 6, documents 15, code 8, visual 8). Test: `uv run pytest backend/tests/benchmark backend/tests/unit/config_data && uv run ruff check backend && uv run ruff format --check backend`
Blocked on: E12 standards indexed (5 STANDARDS cases); a non-English library document (MULTILINGUAL); indexed corpus (retrieval set)
Needs from others: S1/S2 — note: the TP7 preheat sheet's printed footer says Test Plan 6 (image-only page), so the plan-id CONFLICT can only come from OCR of the footer, not from folder context
Next: STANDARDS cases once the 8 ECSS documents are indexed; retrieval set with gold anchors

## 2026-10-22 14:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: standards suite (5 STANDARDS cases from the E12 ECSS standards: E-ST-32-02C pressure-vessel and heat-pipe factors, E-ST-35-06C NVR A/10, E-ST-35-10C elevated corrosion-test conditions, Q-ST-70C tin finish), each answer found on its cited page; number check accepts decimal commas. Golden set: 59 local cases. Test: `uv run pytest backend/tests/benchmark && uv run ruff check backend && uv run ruff format --check backend`
Blocked on: S1's library language/DOI check (MULTILINGUAL), indexed corpus (retrieval set with gold anchors)
Needs from others: nothing new
Next: idle on MULTILINGUAL and the retrieval set until their inputs exist (Lead ruling)

## 2026-10-22 19:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: T6 `external_search` (`backend/llm_engine/engine/tools/external.py`, prompts `external_intent.v1`, `external_search.v1`): generic needs from the question alone, sanitized, isolated grounded Gemini call (only the sanitized query; rule confirmed by the Lead), arXiv for literature, ≤ 3 queries, `external_queries` in the trace, benchmark mock; planner goes external on request or for a design-synthesis gap; policy from `pipeline_config` (`answer.external_search_enabled`, `answer.external_allowed_groups`, `answer.proprietary_terms`). Live check: grounding returned 6 sources, all redirect links resolved.
Blocked on: nothing
Needs from others: S1 / Lead: seed `answer.external_allowed_groups` (e.g. the `dcl-external-search` group name the Pipe sends) and `answer.proprietary_terms`; until then nobody goes external. New key `answer.external_search_enabled` (kill switch, default on) for file 05's key list.
Next: A1 transcribe_page v2 with furniture + test-plan CONFLICT (Lead confirmed), then T3, T2, Skills

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: frontend/openwebui/install_functions.py with a README. It creates or updates and activates both functions, sets the valves (ENGINE_URL http://api:8200, CONSOLE_URL from DCL_CONSOLE_BASE_URL, secret from DCL_PIPE_SHARED_SECRET) and attaches the actions to manastu_engine.main only. It is idempotent, has a dry run, and is tested against a fake of the v0.12.3 admin routes. Also the Console container (frontend/console/Dockerfile and nginx.conf, SPA fallback for deep links, /healthz; image built and checked), and sign-in now returns to the requested deep link.
Blocked on: syncing with main. The app refuses the merge because main changes .claude/launch.json and the repository origin is not yet confirmed by the user (Help › Troubleshooting › Review Pinned Git Origins).
Needs from others: S4 to wire the Console container into compose (build args VITE_*, a published port matching DCL_CONSOLE_BASE_URL, healthcheck /healthz) and to tell me when Open WebUI is up; the user to create the Open WebUI admin account and API key, then run the install script. Lead: the decision on the dev-only backend sign-in (option b) is with the user.
Next: verify the install against the running Open WebUI once the admin account exists.
## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready (merge requested, 029d022, merges clean into main):
- Route C adapters for .tdms, .csv, workbooks and .cfg, so the remaining 20 parked C documents can move. All use a shared series path: channels resolve by operator rule, then by the unit the file itself states (header cell, TDMS unit_string), else HARD UNIT_AMBIGUITY.
- TDMS: when units are missing, the units of the sibling DAQ CSV export are attached as evidence.
- CSV: 100 rows or more becomes a series, otherwise a table.
- Workbooks: LibreOffice recalculation when needed, blocks becoming tables with row nodes, a SOFT CONFLICT for formula errors, and time-series blocks becoming runs.
- Configuration files become config documents.
- Resume now works for any single series run, rebuilt from schema.json and raw.parquet.
- Commit: token counts come from the models role (POST /tokenize/count); a clean run is parked when the role is unreachable. A test-plan id read from the content that differs from the folder keeps both ids and raises a CONFLICT SOFT.
- seed-config writes answer.external_allowed_groups and answer.external_search_enabled, on first start only.
Test: `uv run pytest` (1,376 passed).
Blocked on: the app refuses to sync this worktree with main because main changes a protected file (.claude/launch.json) and the repository origin is not confirmed. The branch still merges clean.
Needs from others: Lead: merge; S4: redeploy, then I re-dispatch on the stack and report the counts; S5: a "Deg C" alias in config/units.txt (NI's spelling; the TDMS adapter maps it locally meanwhile)
Next: live run of the 20 parked C documents; A1/D/F adapter wiring for S2's routes

## 2026-10-22 15:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: `config/units.txt` aliases for LabVIEW/NI unit strings (`Deg C`, `Deg F`, `Deg K`; S1 request) with tests; verification README notes that the TP7 TDMS files halt (empty unit_string) and the cases use the DAQami CSV. proprietary_terms draft (17 terms) kept git-ignored in data/config/, sent to the Lead for the user
Blocked on: S1's language check (MULTILINGUAL), indexed corpus (retrieval set), user confirmation of the proprietary-terms draft
Needs from others: nothing new
Next: idle until messaged


## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready:
- Dev-only backend sign-in (user-approved, hardened). auth.py accepts the DCL_CONSOLE_DEV_TOKEN bearer as the dev identity only with DCL_ENV=dev and DCL_CONSOLE_DEV_AUTH=true; the comparison is constant-time and every use logs a warning. The flag outside dev, a short token or an unknown role answers 503. The websocket works the same way.
- vite.config.ts defines VITE_DEV_TOKEN from the repository .env under the dev server only; no build contains it (grep-checked). The client-side fake user is removed, so roles come from /auth/me. The session config test is hermetic.
- Checked end to end with the real API app and the Vite dev server: signed in as reviewer, live channel open.
- Tests: backend unit 1163 passed, frontend 91.
Blocked on: nothing. S4 adds console_dev_auth, console_dev_token and console_dev_roles plus the start-up refusal; auth.py reads them with a safe default (off) until then.
Needs from others: S4 as above.
Next: review and merge the Lead's background Console redesign branch when it arrives; Settings editing after S1's settings API.
## 2026-10-22 21:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: A1 page furniture and the test-plan CONFLICT (file 03 §A1.3 as amended): `transcribe_page.v2` returns printed headers/footers as `furniture` (live-checked on S5's fixtures: the DOI paper's running head and the German datasheet's footer land in furniture, not in the body); `plan_conflicts` raises CONFLICT SOFT for a plan id in furniture or page-1 text that differs from the folder's (folder value stays). A Gemini error on `transcribe_page` now keeps the OCR text with LOW_CONFIDENCE SOFT instead of failing the document; seen live: a first wording of v2 got `block_reason=SAFETY` on the HTP paper, the neutral wording passes 3/3.
Blocked on: nothing
Needs from others: S5: the real TP7 sheet through A1 once the samples are local, to confirm the footer reaches furniture on that scan
Next: T3 inspect_visuals, T2 query_telemetry (S1's telemetry tables), Skills
## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: object-store evaluation `backend/devops/object_store_evaluation.md` + reusable `backend/devops/ci/s3_compat_check.py`: RustFS 1.0.3 passes every data-plane check and enforces lifecycle (recommended, pending a RustFS-native way to create the app user/policy); SeaweedFS 4.48 does not enforce lifecycle and has no admin API; Garage v2.4.1 has no versioning. Stack redeployed from main 72ae92f at migration 0009. Backups map marked deprecated (user decision)
Blocked on: nothing
Needs from others: Lead — decision on the object store before M6
Next: Open WebUI service (DCL_OPENWEBUI_PORT 8300), Portainer in compose.dev.yaml, Console service with S3

## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready: dev-only Console sign-in settings (`console_dev_auth`, `console_dev_token`, `console_dev_roles` default viewer,reviewer,admin; refused unless DCL_ENV=dev and the token has 32+ chars); Portainer service in compose.dev.yaml (reuses volume dcl-v2-portainer-data, password from DCL_PORTAINER_PASSWORD as a compose secret); object-store evaluation + `s3_compat_check.py`. Open WebUI container dropped (stays in M9). Test: `uv run pytest` green; real `.env` loads
Blocked on: nothing
Needs from others: Lead — merge; S3 — Console Dockerfile on main (a9b26db) for the compose wiring
Next: redeploy workers from main b9cf8f2 for S1; switch the running Portainer to the compose service; Console service wiring

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready: the 20 parked Route C documents ran on the stack (S4's redeploy from 69dd28a) and match the dry-reading expectation. There were 0 FAILED, and all indexed documents are embedded (models role and /tokenize/count working).
- 4 .cfg became ACTIVE config documents.
- DAQami CSV with 22 rows became an ACTIVE table: 22 row nodes.
- DAQami CSV with 115 rows is the first committed telemetry run: 115 rows at 2 Hz over 57 s, 8 thermocouple channels (333–1,226 K) in telemetry_channels. Its t0 came from a temperature slope at 25.5 s with confidence 0.35, which raised a CONFLICT SOFT per §C.6.
- 2 TDMS files are HALTED with 8 UNIT_AMBIGUITY HARD each (AI0–AI7 have an empty unit_string; the CSV units are evidence).
- 12 workbooks became table documents: 3 ACTIVE and 9 ACTIVE_WITH_SOFT_FLAGS (numeric columns that state no unit). Their kinds are 7 engineering_table, 4 test_plan and 1 risk_assessment.
Route C on the stack: 22 HALTED (20 LabJack, 2 TDMS), 7 ACTIVE, 11 ACTIVE_WITH_SOFT_FLAGS.
Blocked on: nothing
Needs from others: an SME confirmation of channel maps (S5's proposals) to resume the 22 HALTED runs
Next: the settings API for S3, then the library PDF language check

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready:
- Benchmark runs (file 08 §5.5): the suite page runs all active cases or a picked subset; the case editor has "Run this case now"; a queued or running run page shows a progress bar and re-reads the run every 5 s until the status is final, so it works whether or not S2's runner publishes websocket `run` events. No API change.
- `.wiki/frontend/m9-pilot-walkthrough.md`: the M9 acceptance criteria as browser steps with pass conditions, operator preconditions and the SQL checks.
- Tests: npm run check 0 errors, npx vitest run 94 passed, npm run build ok, uv run pytest -q exit 0.
Blocked on: Settings editing (backend/api/settings.py is still S1's stub). The "Failed tasks" Ops page needs a `GET /ops/failed-tasks` route over `dead_letters()`; file 10 §2 puts ops routes in S1's `backend/api/sync.py`, which is a stub. Owner question sent to the Lead.
Needs from others: S1: settings API; Lead: owner of the failed-tasks route.
Next: the Failed tasks page once the route owner is decided; Settings editing once S1's API is on main; review the Console redesign branch when it arrives.

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready:
- `GET /ops/failed-tasks?limit=100` (admin, 1–500) in the new `backend/api/ops.py` (Lead ruling). It reads S4's `dead_letters()` newest first and imports the Celery app only when the route runs. Malformed entries are skipped, and Redis down answers 503. No retry.
- The router is registered in `backend/main.py` for the api role; this is the Lead-accepted change of two list entries.
- The Console Ops page has a "Failed tasks" section (admin only, Refresh, empty state). New map page `frontend/ops-page`.
- The live read against the stack's Redis works; the list is currently empty.
- Tests: backend `uv run pytest -q` exit 0 (5 new route tests); Console check 0 errors, vitest 97, build ok.
Blocked on: Settings editing (S1's settings API).
Needs from others: S1: settings API. Regenerated types show S1's new `note` on unit_telemetry evidence; the Review UI does not display it yet (next small S3 task).
Next: show the evidence `note` in the unit pane; Settings once S1's API is on main; review the Console redesign branch when it arrives.
## 2026-10-22 22:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: T3 `inspect_visuals` (`backend/llm_engine/engine/tools/visuals.py`, prompt `vision/relook.v1`): T1 hybrid search restricted to the node types of the requested kinds, optional RRF with an image-embedding kNN from `similar_to_asset_id` (reference excluded), presigned web + thumb URLs (15 min) and the containing document, no node ids. Relook sends the top ≤ 4 images with the question and returns an answer-time observation (`source: relook`, `persisted: false`), nothing written. The planner uses T3 for visual lookups (with relook) and failure investigations (damage photos); the stream carries a `photo_strip` embed. `start_engine` wires MinIO presign/fetch; without MinIO, T3 returns readings without links. Live relook check on the gateway passed.
Blocked on: nothing
Needs from others: S4: the gateway client's per-capability `safety_settings` pass-through (DECISIONS 2026-10-22) is not on main yet; I wire the flag for the extraction capabilities once it lands
Next: T2 query_telemetry over `telemetry_runs`/`telemetry_channels`, then Skills for Open WebUI
## 2026-10-22 16:30 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: read-only M2 acceptance checks for Route C and the TP7 footer CONFLICT check (`backend/tests/acceptance/m2_state.py`, `test_m2_acceptance.py`, M2.md). Route C status counts 22/7/11 and status ⇔ open-flag consistency; every .dat/.tdms is a committed run or a HALTED UNIT_AMBIGUITY HARD case with evidence (1b) and a suggested_resolution (1c); one committed csv run whose normalized Parquet (MinIO GET) and telemetry_channels are in canonical SI; no duplicate (doc_id, fingerprint). TP7: A1 document in a TP07 folder with CONFLICT SOFT on page 1, side a TP07 from folder[n]/filename, side b TP06 from page-1 furniture "Test Campaign 2 - Test Plan 6", test_plan_id stays TP07. 11 seeded-DB proofs (good passes, bad fails). Test: `DCL_TEST_DATABASE_URL=<disposable> uv run pytest -q` (exit 0); live: `DCL_ACCEPTANCE=1 DCL_DATABASE_URL=… DCL_MINIO_ENDPOINT=… DCL_MINIO_ACCESS_KEY=… DCL_MINIO_SECRET_KEY=… uv run pytest backend/tests/acceptance/test_m2_acceptance.py -v`
Blocked on: nothing
Needs from others: expected live failures, for the owners: TP7 check needs Route A1 in the dispatcher's adapter table (S1) and the sheet processed; 1c fails until Route C fills `suggested_resolution` on UNIT_AMBIGUITY (S1, file 06 §5); A1 persists page furniture only inside the CONFLICT evidence, not in the CIR (S2, informational)
Next: idle until messaged (MULTILINGUAL and the retrieval set parked)

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: the Review case view shows S1's unit_telemetry evidence `note` (why a mapped channel cannot be used) under the channel heading, only when it is non-empty; EvidencePane component tests. Console check 0 errors, vitest 99, build ok; backend pytest exit 0.
Blocked on: Settings editing (S1's settings API).
Needs from others: S1: settings API.
Next: Settings once S1's API is on main; review the Console redesign branch when it arrives.
## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c
Merged / ready (4 commits on main d9a720b): network split + Redis password (d2da4e4: Postgres/Redis/MinIO S3 on `DCL_DATA_BIND_HOST`, Redis `requirepass` from `DCL_REDIS_PASSWORD` carried in every in-stack URL, loader refuses a `DCL_REDIS_URL` without it; empty password = today's behaviour); Console container on 8601 (218c011, S3's Dockerfile, msal build, `DCL_CONSOLE_SPA_CLIENT_ID`/`DCL_CONSOLE_API_SCOPE` in loader and .env.example); `safety_settings` pass-through (30caf39, `EXTRACTION_SAFETY`, default off, live gateway call accepted); RustFS step 1 (c978013, `minio-init` uses `policy_set`; full init twice + policy scope green on RustFS 1.0.3 and MinIO). Test: `uv run pytest` 1269 passed, 244 skipped
Blocked on: nothing
Needs from others: Lead — merge; add `DCL_DATA_BIND_HOST`, `DCL_REDIS_PASSWORD`, `DCL_CONSOLE_SPA_CLIENT_ID`, `DCL_CONSOLE_API_SCOPE` to file 01 §7.1; S2 — wire the per-capability flag to `safety_settings=EXTRACTION_SAFETY`
Next: redeploy from main after the merge; RustFS step 2 (one-day lifecycle watch) and step 3 (M6-scale load test)

## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready (merge requested):
- Settings API for S3 (79a0b7b). Endpoints in `backend/api/settings.py`: `GET /settings?prefix=`, `GET /settings/{key}/history`, `POST /settings/preview`, `PUT /settings` (atomic batch, `expected_version` → 409) and `POST /settings/rollback`. Admin only.
  - Every write appends a version and writes an `audit_events` config row with before and after.
  - Keys are validated against file 05's list: `gate.*` through GateConfig, `telemetry.*`, `sanity_ranges`. Errors come back as 422 `{errors: {key: reason}}`.
  - Previews: held items that would download, landed files entering or leaving processing.scope, parked documents per route, and landed files a new gate would reject.
  - Apply: download-scope release or hold; a dispatch starts after scope or route changes.
  - No Gemini cost estimate: no `llm_calls` ledger or price table exists. The preview returns `estimated_cost_usd: null` with the reason.
- Lead's M2 item 1 (ac27e8e): Route A1 (PDF) is in the adapter table, sent to `dcl.process.route_a1` on cpu_parse. `backend/dispatcher/office_run.py` calls S2's `process_pdf` (VisionService, Stores, critical_field_patterns, OCR engine table), then gate, index and commit, or parks the result. DOCX/PPTX/PPT stay WAITING. The parse image imports the task and Docling (checked).
- Lead's M2 item 2 (067cd91): every telemetry UNIT_AMBIGUITY gets a `suggested_resolution`. A unit is proposed only when a file states it: the raw unit, a sibling unit for the same channel name, or a unit in the channel name. Otherwise it gets an explicit "no suggestion" with the .cfg scaling as context, per the 2026-10-22 ruling. `Suggestion.resolution` is now optional; the Console already guards null, and S3 should regenerate `api_schema.d.ts`.
- Wiki: the stale plan sheet catalog-commit is closed; its open live item moved to the Route C rubric. The labjack-dat sheet was already gone.
Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest -q`: 1,640 tests, 0 failures, 73 skipped.
Blocked on: nothing
Needs from others: Lead: merge. S4: redeploy the workers (cpu_parse included). Then I set `routes.A1.enabled = true` (33 A1 documents waiting), dispatch, resume the 22 HALTED Route C documents so their flags get suggestions, and run the M2 live check.
Next: the live M2 check after the redeploy; then the library PDF language/DOI check (started: 814 landed library PDFs; first-page text with pypdfium2, script and stopword detection, since no fastText or langdetect dependency exists)
## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: the Console redesign, reviewed and merged into this branch (a fast-forward from worktree-agent-a84765e1105962288), plus review fixes.
- Run status tones now come from an exhaustive map over the five run statuses, replacing the word matching.
- Viewer overlay regions are keyboard-focusable buttons.
- console-shell-auth map now names Sidebar + TopBar.
- The redesign changes nothing in API calls, routes, auth, config.ts, live.svelte.ts or the backend. Its only build change is the Tailwind plugin in vite.config.ts.
- Live check on 8600 with the dev sign-in: every page renders against the real API, and the viewer shows a real document with its fallback notice. Ops shows the live (empty) failed-task list.
- Not checkable live: queue rows and the case view. On main, `/review/cases` answers 501 ("review tables arrive in M2"), so these rest on the component tests.
- Tests: Console check 0 errors, vitest 107, build ok; backend pytest exit 0.
Blocked on: Settings (S1's settings API); live review data needs S1's review API on main.
Needs from others: S1: review and settings APIs.
Next: the viewer should use the `table` view for table documents (a real engineering_table document showed its HTML table markup in the text view, escaped); Settings once S1's API is on main.

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: the viewer opens table documents as a `table` view, with cell text parsed from the HTML table node. A row anchor or a cells anchor is highlighted. Content without a table still falls back to the text view. This was checked in-process against the stack DB on de504f83. uv run pytest exit 0.
Blocked on: S1's users model and migration 0010 for local auth. Lead: argon2-cffi version for pyproject (in the merge message).
Needs from others: S1: `users` model and migration 0010.
Next: local auth (auth.py login, me and users routes, Console login page and Users admin page), then Settings over S1's /settings API.
## 2026-10-22 23:45 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: (1) per-capability extraction safety flag (9b4e3f1): `pipeline_config` `vision.extraction_safety` (`true` or a list of capability names; default off) makes the seven extraction capabilities send `EXTRACTION_SAFETY`; triage, photo and classify never do; unknown names refused; `extraction_safety_from(session)` for whoever builds VisionService in a worker. (2) T2 `query_telemetry` over `telemetry_runs`/`telemetry_channels`: DuckDB SQL from one template over `normalized.parquet` (catalog column names only), peaks that reproduce Route C's stored values exactly, steady/valve-open/user windows, value_at_t, comparison as UNION ALL, halted runs reported with their case keys; `telemetry_args.v1`; the planner runs T2 for telemetry metric, run comparison and failure investigation with a test plan; `start_engine` builds DuckDB connections with httpfs and a MinIO secret. Live: DuckDB read `s3://dcl-telemetry/…` of the stack's one committed run (a thermocouple run; no chamber pressure/thrust run is committed yet, 22 C documents halted).
Blocked on: nothing
Needs from others: Lead: new `pipeline_config` key `vision.extraction_safety` for file 05's key list (S1 seeds nothing; absent = off). S4: the API image has DuckDB without the httpfs extension; `INSTALL httpfs` downloads it on first use, so please bake it into the image for offline hosts. The Matplotlib plot embed of T2 is not built (no matplotlib dependency); `plot=true` returns a warning.
Next: Skills for Open WebUI

## 2026-10-23 00:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: T2 plot embed. With `plot=true`, T2 renders one PNG per run (Matplotlib Agg, a panel per channel over time from ignition, window shaded, peak marked). It writes the PNG to `dcl-assets` at `plots/{run_uuid}/{sha16}.png` through `put_asset` (the same question overwrites the same key), and the stream carries a `plot` embed frame with the presigned URL. `start_engine` wires `put_asset` from MinIO. Live: plot rendered from the stack's committed run.
Blocked on: nothing
Needs from others: Lead: the `plots/{run_uuid}/…png` key prefix for file 05's dcl-assets layout (answer-time only, no `assets` row). S1, through the Lead: `office_run.default_build()` should pass `extraction_safety=extraction_safety_from(session)` to VisionService. Observation for S1: on the stack's committed thermocouple run, t0 lands at the temperature peak (detection at 2 Hz); the rise starts about 11 s earlier.
Next: Skills for Open WebUI

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready (step 2 of 3, code complete): local password sign-in.
- POST /auth/login: argon2id, HS256 JWT. Wrong password, unknown and inactive accounts get the same 401; 5 failures per minute per email answer 429.
- Every request re-reads the account, so deactivation and role changes apply to existing tokens at once.
- Admin routes /auth/users: create, set roles, deactivate, reset password. The last active admin is kept.
- The bootstrap admin is created while `users` is empty.
- Console: local mode is the default, with a login form, the token in sessionStorage and a Users page under Settings. MSAL stays dormant.
- Tests: backend pytest exit 0 (10 new), Console check 0 errors, vitest 124, build ok.
Blocked on: the live end-to-end login, and with it the dev-token removal, needs S1's `users` model and migration 0010.
Needs from others: S1: `backend.postgres.models.User` with the agreed columns, plus migration 0010. S4: a redeploy after the merge.
Next: step 3, Settings over S1's /settings API, while waiting for 0010.
## 2026-10-23 01:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: Open WebUI Skills. `frontend/openwebui/skills/` holds 13 playbook `SKILL.md` files, one per file 07 §5 row except chit-chat. Each has front matter (`name`, `description`, `intents`, `tools`). `test_skills.py` builds the planner's plan for each skill and fails when the tools drift; I broke one skill on purpose to check it fails. `publish_skills.py` is idempotent: it creates or updates `dcl-<folder>`, active and readable by every user, with a dry run, and never prints the key. Live on a disposable Open WebUI v0.12.3 container (since removed): 13 created, a second run made 13 updates, and the public read grant reads back.
Blocked on: a Lead ruling (question sent)
Needs from others: Lead: should the skills be attached to `manastu_engine.main` (file 08 §1 says attached), and should a toggled skill steer the planner? Details in the message.
Next: idle until the ruling

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready:
- Step 3: the Settings pages edit pipeline_config over S1's /settings API. Typed editors, then Preview showing impacts (counts, bytes, extensions), then Apply with a reason and the versions the editor saw. 422 reasons show per key; a 409 reloads the current values. Each key has its history with Restore.
- Live on the stack: an edit of gate.junk_names was applied and then restored. Both writes are audited.
- Account changes now write audit_events (entity_type `user`; Lead ruling).
- Tests: Console check 0 errors, vitest 137, build ok; backend pytest exit 0.
Blocked on: local login end to end and dev-token removal wait for S1's 0010 and S4's redeploy (the Lead will say when). The cost estimate in the preview waits for S1's llm_calls price ledger.
Needs from others: S1: migration 0010 (users, `user` audit type).
Next: end-to-end local login and dev-token removal when told; otherwise idle.

## 2026-10-23 02:15 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: playbook hint (ruling (c), my side). `AnswerOptions.playbook_hint` is an `Intent` or null. Each SKILL.md has `dcl-playbook: <intent>` in its front matter, also published as the tag `dcl-playbook:<intent>`. `playbooks.apply_hint` adds the hinted intent to the analysed ones; a chit-chat reading gives way to it.
Blocked on: nothing
Needs from others: S3 (M9): map `chat_context.mentioned_skill_ids` (`dcl-<folder>`) to the hint, either from the skill's `dcl-playbook:` tag or from the front matter; send only one hint (the first mentioned).
Next: benchmark runner, metrics, judge (file 08 §5, M10)
## 2026-10-22 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready (merge requested):
- Review API (c82b518), reviewer role, over `backend/review/cases.py`:
  - `GET /review/cases`: open cases by default, with every Console filter; sort by impact (halted files in the same folder), age or severity; open HARD/SOFT totals.
  - `GET /review/cases/{key}`: flags with evidence, suggestions and allowed actions; locations with folder ids; siblings.
  - `POST` assign, resolve and reject; rules list, create and deactivate.
  - A telemetry `set_unit` writes an operator channel_map rule (the request's, else one scoped to the file) and starts `resume_for_rule` for every HALTED match.
  - Every action writes `audit_events`. Dry run, undo and simulate still answer 501.
- Migration 0010 `users` (f0c0ca4 and the follow-up commit): the columns S3's store uses. `roles` text[] has a CHECK that each element is viewer, reviewer or admin; `email` is lower-case (CHECK) and unique. The model is `backend.postgres.models.User` and the enum `UserRole`. `audit_events.entity_type` gains `user`. My first-admin bootstrap was removed because S3's `auth.py` already has `ensure_bootstrap_admin`.
- S2 notes: A1 builds its VisionService per document with `extraction_safety_from(session)` (80c8b2c). Telemetry t0 on coarse data (f44bb9c): the sustain test now needs at least 2 samples, and t0 is the rise onset. On a synthetic 2 Hz rise starting at 20 s, the old code gave 26.5 s and the new code gives 20 s. kHz data is unchanged, and weak confidence still raises the CONFLICT SOFT.
- Library language/DOI check (14545d7, `backend/sync/language_check.py`). Over the 814 landed library PDFs: 733 English, 54 undetermined, 19 with no text layer, 108 with a DOI on pages 1–2, and 8 non-English, each confirmed by reading the first-page text:
  - ISP Tech: 2 German patents.
  - Staged Vapour Ignition: 3 Chinese, 1 Japanese and 1 Korean patents.
  - Valves/Electromagnetic: 1 Russian paper.
  The TSV is in git-ignored `data/library_languages.tsv` on my worktree. Choosing the MULTILINGUAL folder is S5's call under the delegated allowlist; Staged Vapour Ignition alone covers zh/ja/ko.
- Live (S4's redeploy): `routes.A1.enabled` set through the audited settings path. Dispatch released 27 A1 PDFs; the 6 non-PDFs stay WAITING. The 22 HALTED Route C documents were resumed and are still HALTED, now with suggestions on every unit flag. The M2 live check passes 7 of 8; the TP7 footer CONFLICT waits for A1 to finish (3 of 27 done so far, about 5 minutes per PDF on CPU; Tesseract OSD errors on one datasheet for S2 to look at).
Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest -q`: 1,700 tests, 0 failures, 73 skipped, plus 10 new language-check tests.
Blocked on: nothing
Needs from others: S3: regenerate `api_schema.d.ts` (review routes live, `Suggestion.resolution` nullable); users store emails must be lower-case (S3 lowercases on create; keep it on update). S5: pick the MULTILINGUAL folder from the 8.
Next: report the A1 counts and the M2 TP7 check when the A1 batch ends

## 2026-10-22 17:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: MULTILINGUAL set chosen by file name from S1's language check: 6 library patents as E13 (zh ×3, ja, ko from Staged Vapour Ignition; de ×1 from ISP Tech); path globs sent to the Lead for S1's processing.scope
Blocked on: E13 indexed (Lead confirms), then the 6 remaining golden cases (library and multilingual)
Needs from others: S1: add the E13 globs to processing.scope
Next: idle until the Lead confirms E13 is indexed

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready:
- Local login proven live on the stack. The first login bootstrapped the admin. A reviewer created on the Users page signed in, opened the real queue and a halted case, and the live channel was on. That reviewer got 403 on admin routes and 401 right after deactivation, and the audit rows were written.
- The dev-token sign-in is removed everywhere in S3 code, and from config.py and .env.example (Lead request). The dev server runs with VITE_AUTH_MODE=local and no token.
- Tests: Console check 0 errors, vitest 136, build ok.
Blocked on: nothing. The merge needs the Lead to drop docs/architecture/01 line 216 (the dev sign-in names) in the same merge; until then 2 env-contract tests fail.
Needs from others: Lead: that manual row, and the three names out of the stack .env.
Next: idle until messaged.
## 2026-10-23 04:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: benchmark runner, metrics and judge (`backend/benchmark/{metrics,judge,runner,tasks}.py`, prompt `benchmark/judge.v1`, map `backend/benchmark-runner`).
- The runner claims a queued run and snapshots the model config, pipeline version and ACTIVE document count. It answers each case through `AnswerWorkflow` in process, with external search mocked: no network, checked by a test.
- It scores each case per file 08 §5.4, classifies failures, writes `benchmark_results`, keeps the aggregate current and publishes `run` progress and finished events.
- A cancelled run stops between cases. A redelivered run resumes only the cases without a result.
- Celery on io_light, one task per case (soft limit 300 s): `dcl.benchmark.start`, `dcl.benchmark.case`, and `dcl.benchmark.sweep` (starts queued runs; re-enqueues the cases of a run whose Redis heartbeat expired).
- Also in this merge:
  - Retrieval no longer fails a whole search on a node without a locator; it skips the node with a warning. Seen live: Route C table and table_row nodes (503 rows) carry no page, line, time or cells.
  - T2 pressure units are now `barg`/`bara`, because pint read "bar g" as bar·gram.
  - `engine_deps(settings)` is shared by the API and the runner.
- Live: one benchmark answer went through the stack (Gemini, models, DB), was scored and its citations resolved to file names (76 s).
Blocked on: nothing
Needs from others: S4: add `backend.benchmark.tasks` to `TASK_MODULES` and a beat entry `dcl.benchmark.sweep` every 60 s on io_light. Optional: a queue with a longer soft limit if 300 s per case proves short (one live answer took 76 s). S1: Route C `table`/`table_row` nodes need a locator (`sheet_name` + `cell_range`, or `line_start` for CSV rows); until then they cannot be cited. S3 (optional): send `dcl.benchmark.start` on `POST /benchmark/runs` so a run starts without waiting up to a minute for the sweep.
Next: idle until messaged

## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: POST /benchmark/runs now sends dcl.benchmark.start(run_id) after the commit (lazy Celery import, best effort; the sweep covers a broker outage). The row stays QUEUED for the runner. 4 new tests; uv run pytest exit 0.
Blocked on: the live run-page check waits for S4 to register the benchmark tasks (the Lead will say).
Needs from others: S4: workers load backend.benchmark.tasks.
Next: check the run page against a real run when told.
## 2026-10-22 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c-bench
Merged / ready: c50df0a on claude/gifted-hofstadter-0bec1c-bench (from main 5ce1602): backend.benchmark.tasks in TASK_MODULES, beat benchmark-sweep every 60 s on io_light. Test: uv run pytest 1378 passed, 305 skipped
Blocked on: nothing for this part; the main S4 branch waits for the lifecycle watch (2026-10-24 00:00Z)
Needs from others: Lead — merge; then I redeploy beat and io_light from main
Next: redeploy beat and worker-io-light after the merge
## 2026-10-23 05:30 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready:
- 69e28b5: the A1 OSD error on doc 1539b6b4 is benign. Docling runs Tesseract orientation detection on every OCR'd page, fails on near-empty pages ("Too few characters") and then OCRs with our explicit script model anyway. It is now logged as INFO; other OSD failures stay errors.
- Same commit: Docling converters are cached per OCR plan, because the log showed 25 pipeline rebuilds for one document. Measured in the parse worker: 13.1 s → 2.1 s per text-layer run, 5.9 s → 3.7 s per Tesseract run; peak memory 2.2 GB with two converters.
- NUL fix: A1 strips NUL bytes from its output. Doc 206e1884 (j.ijheatmasstransfer) FAILED in the commit with "PostgreSQL text fields cannot contain NUL".
A1 batch read (27 tasks): 18 indexed (13 ACTIVE, 5 with SOFT low-confidence flags), 8 HALTED, 1 FAILED. The 6 E13 patents are not in `documents` yet.
- All 8 ECSS standards (E12) are HALTED as PARSE_FAILURE "encrypted". They open without a password: owner-password restrictions only.
- `sync_roots.cloud_allowed` is false on all four roots, so the batch made no Gemini call at all. That means no triage, so no language, script or rotation: every `documents.language` is null and one title is upside-down text. It also means no figure or handwriting reading and no transcribe_page; cost per document is 0.
- OCR therefore ran Tesseract Latin on every image-only page (56 OCR nodes against 2323 printed ones).
- There is no `llm_calls` table on the stack and no LLM metrics in Prometheus, so cost per document cannot be measured even once Gemini runs.
- Durations: 0.05 s (halted) to 1190 s (420 pages); an 8-page paper took 687 s (formula and code enrichment on CPU).
Blocked on: Lead/user rulings (sent): cloud_allowed for the roots; owner-password-only PDFs
Needs from others: S1 (or Lead): the `llm_calls` table and the client's ledger hook, for cost per document
Next: after the rulings, re-run A1 on the 27 + 6 E13 documents, report OCR engine per script and cost, then the M5 handwriting calibration on the TP7 sheets (it needs Gemini)

## 2026-10-23 06:15 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: owner-password PDFs. A1 pre-flight now decrypts in memory a PDF that opens without a password, and Docling gets the decrypted bytes (`Preflight.decrypted`). PARSE_FAILURE stays only for PDFs that need a user password (file 03 §A1.1 as amended). Plan sheet skipped for this small fix.
Blocked on: S1's re-dispatch of the A1 documents with cloud_allowed true (206e1884 and the 8 ECSS standards after this merge)
Needs from others: S1: re-run; `llm_calls` with the client's ledger hook
Next: OCR engine per script and cost report, then the M5 handwriting calibration on the TP7 sheets

## 2026-10-23 07:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Committed, not mergeable yet: failure classes after the first scored run (56 cases, 1 passed).
- The 38 failed results without a class were all engine errors, not unscored misses:
  - 24 asyncio errors ("Event loop is closed", "bound to a different event loop"). This was my bug: each io_light thread called `asyncio.run` on the shared gateway client. Fixed: one process-wide loop, `tasks.run_async`.
  - 14 workflow timeouts at 300 s.
- New classes: MISSING_DOCUMENT (expected document not indexed), INSUFFICIENT_EVIDENCE, ENGINE_ERROR (raised or timed out), and RETRIEVAL_MISS also when no tool returned an expected document. Every failed result now has a class.
- The DB test fails on `ck_benchmark_results_failure_class` until S1 adds the three values.
Blocked on: S1: add MISSING_DOCUMENT, INSUFFICIENT_EVIDENCE, ENGINE_ERROR to `FailureClass` with a CHECK migration (and the Lead to file 08 §5.4)
Needs from others: as above; S1's A1 re-run
Next: merge this after S1's migration; answer latency (p50 160–230 s on run 1) needs a look; then the OCR and cost report and the handwriting calibration
## 2026-10-22 21:00 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: M10 baseline from scored run 1 (`backend/tests/benchmark/BASELINE.md`, summary on `.wiki/quality/benchmark-suites.md`): 56 cases, 1 pass; 26 runner/metric bug, 15 engine error, 14 pipeline gap, 0 confirmed gold error. Five runner findings for S2 (null class on 38 errored cases, RETRIEVAL_MISS unreachable without gold anchors, must_label_external web-only, insufficient-evidence check mode-only, halted data hidden as SYNTHESIS_ERROR). Hold-outs not reported
Blocked on: E13 indexed (MULTILINGUAL and library cases)
Needs from others: S2: the runner findings; Lead: is the TP12 report PDF among the 18 indexed A1 PDFs (2 cases depend on it); the weather case's answer text (gold or metric)
Next: idle until messaged

## 2026-10-23 08:00 — DCL S2 ML — claude/infallible-swartz-58c96b
Ready, waiting on S1's enum migration: the runner findings of S5's BASELINE.md.
- (1) All case tasks of a worker share one event loop (`tasks.run_async`); per-answer timeout 900 s (`runner.ANSWER_TIMEOUT_S`).
- (2) Every errored case has a class: TOOL_ERROR for an exception, TIMEOUT for a timeout.
- (3) RETRIEVAL_MISS also without gold anchors, when no tool returned an expected document. A document that is not indexed is MISSING_DOCUMENT; an unrequested insufficient-evidence answer is INSUFFICIENT_EVIDENCE.
- (4) `must_label_external` accepts labelled external_kept library citations.
- (5) HALTED_DATA when a tool reports the asked run halted.
- Engine: an out-of-scope question is refused in mode insufficient_evidence (`chitchat.v2`), and a halted-run warning is named in the answer as a `> Note:` line.
- The integration test `test_runner_db` fails on `ck_benchmark_results_failure_class` until S1 adds the new values.
Blocked on: S1: MISSING_DOCUMENT, INSUFFICIENT_EVIDENCE, TIMEOUT, HALTED_DATA in `FailureClass` and its CHECK (migration)
Needs from others: S4 (through the Lead): a `benchmark` queue with a limit of at least 1000 s
Next: answer latency (225–236 s per answered case on run 1 against 76 s in my single live check) needs a profile; then the OCR and cost report and the handwriting calibration after S1's A1 re-run
## 2026-10-22 — DCL S3 Frontend — claude/cranky-rhodes-0cb23f
Merged / ready: the Benchmark pages now match S2's real runner output.
- Checked against the six real runs.
- The aggregate and metric keys match the runner's; recall was never shown before.
- Runner errors are their own outcome, and a running run's pass rate says how much is scored so far.
- The drilldown follows score_case.
- Compare counts only cases scored in both runs and warns about cross-suite comparisons.
- A whitespace bug in four components is fixed.
- Tests: Console 138, backend pytest exit 0, compare integration tests pass on a scratch DB.
Blocked on: nothing.
Needs from others: S2 (via the Lead): 38 of 56 real results are runner errors, either "RuntimeError: <asyncio.locks.Event> is bound to a different event loop" (likely the lru_cached RunnerDeps reused across asyncio.run calls in tasks.py) or a 300 s WorkflowTimeoutError. Answered cases took about 225 to 236 s.
Next: idle.

## 2026-10-23 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c-benchq
Merged / ready: fbd84af on claude/gifted-hofstadter-0bec1c-benchq (from main a067dca): queue `benchmark` (prefork 1, 950/1000 s, 2 GB), worker-benchmark, TASK_ROUTES for dcl.benchmark.*, beat sweep moved. Test: uv run pytest 1384 passed, 306 skipped
Blocked on: nothing for this part; the main S4 branch waits for the lifecycle watch (2026-10-24 00:00Z)
Needs from others: Lead — merge; add the `benchmark` row to file 10 §4. S2 — set `queue=str(Queue.BENCHMARK)` (or drop `queue=`) on dcl.benchmark.start/case/sweep in backend/benchmark/tasks.py
Next: redeploy beat, worker-io-light and worker-benchmark from main after the merge
## 2026-10-23 — DCL S1 Backend — claude/competent-brahmagupta-3a5541-0011
Merged / ready (quick merge request): migration 0011. `FailureClass` gains MISSING_DOCUMENT, INSUFFICIENT_EVIDENCE, TIMEOUT and HALTED_DATA (enum and benchmark_results CHECK; the downgrade nulls those values first). It is on its own branch cut from main, so it merges ahead of the rest of my work.
Test: `DCL_TEST_DATABASE_URL=… DCL_TEST_MINIO_ENDPOINT=… uv run pytest -q`: 1,688 tests, 0 errors; schema tests green. The 2 office_run failures came from this fresh venv missing the parse group (pikepdf); with it, they pass.
Blocked on: nothing
Needs from others: Lead: merge. S4: apply 0011 on the stack.
Next: the A1 re-run counts and the M2 live check. Then on claude/competent-brahmagupta-3a5541: locators, NUL guard, 0012 (answer_traces, llm_calls, prices; my llm_calls migration moves from 0011 to 0012), Route A2, Route B.
## 2026-10-23 11:40 — DCL S2 ML — claude/infallible-swartz-58c96b
Ready for merge: the runner findings of S5's BASELINE.md, with main 61f228c (S1's 0011) merged in.
- `dcl.benchmark.start`, `case` and `sweep` run on the `benchmark` queue (S4's prefork worker, soft limit 950 s). The stale-run heartbeat is 30 min.
- Test: `DCL_TEST_DATABASE_URL=<disposable paradedb:0.26.2-pg17> uv run pytest` gives 1769 tests, 0 failed, 120 skipped (MinIO, sample exports, live stack). `test_runner_db` passes on the new CHECK. `ruff check backend` is clean.
Latency profile (run 1: 225–236 s per answered case):
- The models container runs bge-reranker and EmbeddingGemma on CPU in float32 (`/models/health`: `"device":"cpu"`).
- The cause is compose `models` → `deploy.resources.reservations.devices.capabilities: [gpu, utility]`. Without `compute` the NVIDIA runtime mounts only nvidia-smi and NVML. `libcuda.so` is a 0-byte file, `/dev/nvidia-uvm` is missing, and torch reports "no NVIDIA driver".
- Run 1 in Tempo: 58 `/rerank` spans, p50 20.6 s, all between 20 and 23 s. `/embed/text` has p50 66 ms, but its tail reaches 217 s while it queues behind rerank on the one model lock.
- Same image and code, 50 passages of 2400 chars: CPU float32 takes 35.6 s per rerank (30 passages: 22–27 s). GPU bf16 (`--gpus all`) takes 0.56 s (30 passages: 0.32 s).
- Each answer runs one rerank per search call, plus the time spent waiting on other cases' reranks. The Gemini time cannot be separated for run 1: no `llm_calls` table, traces only logged, no benchmark spans in Tempo.
Blocked on: S4 (through the Lead): `capabilities: [gpu]` (or `[gpu, compute, utility]`) on the models service, then recreate it. Verify `/models/health` reports `"device":"cuda","dtype":"bfloat16"`.
Needs from others: S1's A1 re-run
Next: re-time one live case after the GPU fix to get the Gemini share; then the OCR-per-script and cost report after S1's A1 re-run; then the handwriting calibration

## 2026-10-23 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: targeted synthesis repair (DECISIONS 2026-10-23).
- Only the claims the verifier rejected go back to Gemini, each with its evidence items (`repair.v1`, thinking MEDIUM). The corrected sentence replaces the old one in place, a null removes it, and only the changed claims are verified again. The verifier's rules are unchanged.
- TP23 question on the stack, one run each: before 110.6 s (repair synthesis 75.4 s), after 45.6 s (repair 16.8 s). Gemini is 97–99 % of answer time.
- Warm query embedding on the GPU: 0.02–0.03 s (first call 0.14–0.26 s).
Blocked on: nothing
Next: A1.9–A1.10 office formats and the twin page map, then the queue (D/F readiness, A1 report, handwriting calibration, Gemini split, trace writer, prompt registry, translation, re-embed counts)
## 2026-10-23 12:30 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: public samples for formats the corpus lacks in git-ignored data/samples/web/ (21 files: STL ×2, STEP, DXF ×2, draw.io ×2, SVG ×2, VSDX ×2, PPTX, DOCX ×2, notebook, MATLAB, C, zip with nested folders and a .DS_Store junk member, tar.gz, synthetic TDMS with unit strings) with SOURCES.md (URL, license, sha256); none for DWG (no permissive source) or .wbpz (no public sample). data/samples (real + web, 286 files) copied to the s6-routes worktree. Formats suite: 13 golden cases (A1, B, C, E, G), answers verified in the local samples. Test: `uv run pytest -q backend/tests/benchmark`
Blocked on: nothing
Needs from others: S6: index the web samples so the formats suite can run
Next: idle until messaged

## 2026-10-23 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: A1.9–A1.10 and A1.0.
- `process_office` is the A1 entry for every format. Word-family files go LibreOffice → PDF → the PDF pipeline (ruling a), with tracked changes, comments, footnotes and embedded objects read from the DOCX.
- Slides (PPTX, PPT, ODP) are read natively: one slide node per slide, chart data from the chart XML, speaker notes, `describe_slide` when graphics cover more than 25 % of the slide.
- `twin.py` gives S6's Route A2 the page map, the page renders, and the PDF-only pages run through A1 as an appendix.
- Live: 2 real DOCX from the corpus in the parse worker (17 pages in 122 s, 16 pages in 62 s); Apache POI's public PPTX, PPT and pie-chart samples (data/samples/web, URLs in SOURCES.md) through the stack's LibreOffice and Gemini.
Blocked on: nothing
Needs from others: S1: in `office_run`, build = `process_office` and lift the PDF-only gate, so the six waiting DOCX process. S6: call `twin.process_twin` from A2 for visual twins.
Next: Routes D/F readiness on the stack, then the queue
## 2026-10-23 — DCL S6 Routes — claude/s6-routes
Merged / ready: Route A2 (9bc72fb). `process_latex` and `process_json` in `backend/routes/a2_source/route.py` take the assembler's plan (primary, parts, visual_twin as `SourceFile`) and return a `ProcessedDocument`. On E4 TP12: 163 nodes; the 11 sections and appendices A and B; 16 figure assets; refs resolved; twin page map (Overview p6, Test Setup p8). E3 JSON: section set → test_report; single section files → SCHEMA_UNKNOWN (no schema matches the creator's `{id,title,content}` shape, which S5 can add). Pandoc is replaced by pylatexenc (file 01 lists both) because the source map needs positions.
Test: `uv sync --frozen --group parse --group dev && uv run pytest -q` exit 0; A2 tests 28 passed.
Blocked on: nothing for A2.
Needs from others: S1: the `dcl.process.route_a2` runner and adapters. Lead: dependency pins for A2/B/E/G.
Next: Route B once the grammar pins are in; then E, then G.
## 2026-10-23 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready (merge requests, one per item, stacked in this order on the branch):
- Locators (51813e6): Route C table and table_row nodes carry sheet + one-row cell_range (workbooks) or line_start/line_end (CSV). Also fixed: tables with a Unit column lost their first data row. One-off backfill task `dcl.process.relocate_route_c_tables`, to run after the redeploy.
- NUL guard (b9ca0f9), plus the entity fix 2562a9e: `strip_nul()` at the start of `commit_document`. New entities are now `created_by = system`; the old value 'llm' failed the commit of A1 doc 8a7080bd.
- Derived blobs (0228dd8):
  - `ProcessedDocument.derived_blobs` and one shared `register_derived_blobs()` for S2's A1.9 and S6's Route G.
  - `dispatch_derived` turns children into documents; `primary_location()` gives them their parent's location.
  - Low-confidence evidence gains `page_ocr_text` and per-crop `ocr_text`.
- 0012 (18fdcca): `llm_calls` (ledger hook `db_ledger`) and `answer_traces`. Prices are the `models.prices` config key, not a table; the preview estimates the cost of widening the scope from priced `llm_calls`.
- Real-time sync (1162a9e): `dcl.sync.poll_deltas` (S4: every 300 s) and `dcl.sync.renew_subscriptions` (hourly, a no-op until webhooks are on); receiver `POST /sync/webhook` behind `sync.webhooks_enabled`.
Test: `uv run pytest -q` with test servers: 1,791 tests, 0 failures, 73 skipped (before the main merge). After the merge: api, schema, benchmark and celery tests green.
Live: A1 re-run with cloud_allowed and the 6 E13 patents is still running. KR20110128394A FAILED: RapidOCR cannot read `ch_PP-OCRv5_det_mobile.onnx` in the parse image (Permission denied, S4). 7 runs parked while the models role was loading after the stack restart; they are re-enqueued.
Blocked on: nothing
Needs from others: S4: readable RapidOCR models in the parse image; apply 0012 after the merge; beat entries for the two tasks; then I run the locator backfill.
Next: A1 counts and the M2 live check when the batch ends; item 6 (review dry run, undo, simulate)

## 2026-10-23 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: (6) the prompt registry API (file 08 §3.3) over the prompt files: list with latest/in_use/variables, show, diff, and run on sample (reviewers; one Gemini call logged as `console.prompt_preview`). Plan sheet skipped (small).
Blocked on: nothing
Next: (7) translation, then derived_blobs in A1.9, then the answer_traces writer

## 2026-10-23 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready (2 commits):
- (7) On-the-fly translation for the viewer: `translate_passages` with a content-hash cache, and `POST /v1/translate {doc_id, page_no | anchor, target_language}`. Content under a root without cloud permission is never sent (403).
- A1 stack defects:
  - every image asset carries width, height and bytes;
  - a figure node is never empty: caption, else a unique placeholder;
  - the twin page map skips a text table of contents.
- Existing documents: no separate backfill; S1's A1 re-dispatch rewrites the assets and figure nodes.
Blocked on: nothing
Next: answer_traces writer, with the /v1/traces routes and the feedback write
## 2026-10-23 — DCL S6 Routes — claude/s6-routes
Merged / ready:
- A2 twin through S2's `process_twin` (7b83583). Nodes get `page_no` from the twin; page renders and PDF-only appendix pages come from `twin_appendix`. My page_map.py is removed.
- Route B (bc8db82): `process_code` for .py/.c/.h/.m (Tree-sitter), .ipynb, .md, .txt/.bat/.cmd and requirements files.
Test: `uv run pytest -q` exit 0 (on main f6238e4 merged). B: 15 tests pass, A2: 28.
Blocked on: nothing.
Needs from others:
- S1: B adapter and runner.
- S2: twin.page_map maps every heading to a contents page that lists them (headings 1, 2, 2.1 all land on page 2). A page that matches many headings should be skipped.
Next: Route E (plan sheet open), then G.

## 2026-10-23 13:30 — DCL S5 Quality — claude/strange-bhaskara-1dd439
Merged / ready: config/gate.yaml no longer lists `.c` as junk (Lead ruling after S1's finding); `.o`, `.a`, `.so` stay junk and C sources under Tier-1 environment folders are still skipped; gate tests pin all four against the documented rule and S1's gate_item. Test: `uv run pytest -q` (exit 0)
Blocked on: nothing
Needs from others: Lead: file 02 §4 line 127 still lists `.c` (manual amendment); `.obj` and `.d` were never in the list and I did not add them (`.obj` is also the Wavefront 3D mesh format)
Next: idle until messaged
## 2026-10-23 — DCL S6 Routes — claude/s6-routes
Merged / ready: Route E. `process_diagram` reads draw.io, XSD, SVG, .vsdx and DXF into one graph in `documents.catalog`, with page summaries, component nodes, renders and a read_schematic cross-check.
Test: `uv run pytest -q` exit 0; E: 13 tests pass.
Blocked on: nothing.
Needs from others: S1: the E adapter, runner and .svg/.vsdx/.dxf kinds.
Next: Route G (archives with bomb guard, members as derived_blobs, .wbpz, .scdoc/.dwg as cad_reference, STL/STEP measured with trimesh).

## 2026-10-23 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: the `answer_traces` writer and the trace routes. Each answer's trace is written with question, chat, message and user ids, and with `mode` inside model_config. GET /v1/traces/{id} and GET /v1/traces?chat_id&message_id serve the caller's own traces (404 otherwise). POST /v1/traces/{id}/feedback appends in one statement; `wrong_unit` on a cited page opens a SOFT CONFLICT flag. Live: one stack answer wrote its row. Also in this branch: `image_fields` moved to the dependency-free `a1_office/assets.py`, so Route F imports without the parse group (the Lead's importorskip guard is removed), and the translate test is ruff-formatted.
Blocked on: nothing
Needs from others: S6: `test_route_b.py::test_web_samples_c_matlab_notebook` fails in any checkout that has a `data/samples/web` folder without S6's files; it should skip per missing file
Next: citation markers = citation events, then attachments

## 2026-10-23 — DCL S4 DevOps — claude/gifted-hofstadter-0bec1c-media
Merged / ready: a739eb3 on claude/gifted-hofstadter-0bec1c-media (from main ec8e76f): media image target for worker-media (media group, ffmpeg, Whisper medium int8 baked, whisper-cache volume); av pinned to 18.0.0 (faster-whisper 1.2.1 breaks on PyAV 19). api redeployed from ec8e76f (traces routes live). Gateway exposes no prices; models.prices not seeded. Test: uv run pytest 1438 passed, 334 skipped
Blocked on: nothing for this part; the main S4 branch waits for the lifecycle watch (2026-10-24 00:00Z)
Needs from others: Lead — merge; user — gateway per-model rates for models.prices
Next: after the merge, build the media image and recreate api and every worker from main (ledger writes from all clients)

## 2026-10-23 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: chat attachments (file 07 §9.7). The engine fetches each presigned upload once (25 MB cap, up to 5 files) and reads it as user-provided evidence labelled "<name> (your attachment)", provenance `user_provided`; nothing is indexed.
- Text files are used as they are; PDFs and images are read by Gemini (`attachment.v1`); office files go through LibreOffice to PDF first.
- An attached photo with a visual question also runs T3 by its image embedding.
- Live: an attached PDF was read through the gateway.
Blocked on: nothing
Needs from others: S3: the Pipe's provenance label map can add `user_provided` → "your attachment" (it falls back to the raw value meanwhile)
Next: D/F stack test when S4 and S1 say so; the A1 OCR and cost report after S1's re-run; then the Gemini time split per answer from llm_calls
## 2026-10-23 — DCL S6 Routes — claude/s6-routes
Merged / ready:
- Route G (4e0a981): archives with the bomb guard and the gate, members as derived_blobs, .wbpz, .scdoc/.dwg cad_reference, STL/STEP measured.
- Same commit: Lead's test-hygiene fix. Sample tests skip per missing file; the C and MATLAB grammar imports are guarded.
Test: `uv run pytest -q` exit 0. G: 19 tests. One xfail: TP12 exact twin pages.
Blocked on: nothing.
Needs from others:
- S1: G adapter and runner, register_derived_blobs, REFERENCES relations from catalog.references, and kinds for .stl/.step/.stp/.igs/.iges/.dwg. Today .step resolves to Route C, and .c/.m members resolve to C.
- S2: twin.page_map's contents-page check counts number-stripped headings, so TP12 Overview maps to page 1 instead of 6.
Next: all four S6 routes are built; idle until messaged.
## 2026-10-23 — DCL S6 Routes — claude/s6-routes
Merged / ready: the samples smoke test (ed1692a), `backend/tests/unit/routes/test_samples_smoke.py`. Every accepted file in data/samples passes with vision off, in ~14 s. One summary line per route:
- A2: 28 files, 475 nodes
- B: 11 files, 121 nodes
- E: 10 files, 69 nodes
- G: 6 files, 6 nodes
Blocked on: Lead: pin `resvg-py==0.5.0` in the parse group for SVG renders (Route E follow-up 1).
Needs from others: as above.
Next: SVG render and read_schematic, after the pin.

## 2026-10-23 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: 9db42e9 (the chat-feedback flag uses the document's route; Gemini time split in TraceView; repair output capped).
Blocked on: S1's A1 re-run. On the stack, 26 A1 documents are still PROCESSING, 7 are ACTIVE with a language, and the parse worker logged no vision call in the last 30 min.
- So far llm_calls holds only engine and test calls, nothing with doc_id. Once the re-run runs, I check that the workers' vision calls reach llm_calls with doc_id; per-document tokens depend on it.
Next: the A1 OCR-per-script and token report, then the handwriting calibration (medium vs high) on the TP7 sheets
## 2026-10-23 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready (merge requests, stacked on the branch):
- Review API, item 6 (5f42ee4): dry run (a telemetry set_unit's stats converted to SI against S5's sanity range), undo (the last resolution within 30 days; a rule only that resolution used is retired; junked locations restored; committed documents rebuilt), simulate. No review route answers 501 now.
- File kinds (2e8761a): DXF/SVG/VSDX → E; STL/STEP/IGES/DWG → G; .m/.c/.h → B.
- Runners and adapters for all eight routes (aafb9d3): one shared runner; A1 on `process_office` (the DOCX released); A2, B, E, G (S6) and D, F (S2) tasks.
  - G's archive members are registered as derived blobs; CAD references become REFERENCES relations.
  - D: one model reading per photo burst.
- Revision supersession (274e0d2): the newer revision of a drawing in the same folder SUPERSEDES the older; equal revisions raise CONFLICT SOFT.
- Live: the locator backfill is done. 0 of 567 Route C table/row nodes lack a locator.
Test: `uv run pytest -q --ignore=backend/tests/integration/benchmark/test_runner_db.py` with test servers: 1,963 tests, 0 failures, 83 skipped. S2's file leaves a Session open (line 174), which hangs the teardown downgrade; reported.
Blocked on: nothing
Needs from others: S4: redeploy cpu_parse and media after the merge; then the routes can be switched on (A2, B, E, G now; D, F once the media image is live). S5: `.c` out of the gate's junk list.
Next: the A1 counts and the M2 live check when the batch ends; Console API items 8–11
## 2026-10-23 — DCL S6 Routes — claude/s6-routes
Merged / ready: SVG render in Route E. The SVG is rasterized with resvg-py at the draw.io size rule and read_schematic runs on it.
Test: `uv run pytest -q` exit 0; E: 14 tests pass.
Blocked on: nothing.
Needs from others: nothing.
Next: idle until messaged.

## 2026-10-23 — DCL S1 Backend — claude/competent-brahmagupta-3a5541
Merged / ready (merge requests, one per item):
- Route tolerance (b7ab8ed): a flag whose route is not a Route (S2 once wrote "answer") opens with route null and a warning.
- Items 8 and 9 (45caa72):
  - `GET /sync/roots` serves Sources and the Ops page: auth, delta times, webhook or poll, counts, waiting files, errors.
  - Device-code sign-in through `dcl.sync.sign_in` on io_light (`POST|GET /sync/sign-in`).
  - `POST /sync/process-everything` goes through the audited settings path.
  - `GET|POST /sync/redispatch?route=X` counts, then re-runs a route's committed documents.
- Item 10 (1a706e2): `GET /entities`, `POST /entities/merge`, `POST /entities/split`, with audit rows.
- Item 11 (339722b): the settings preview counts the nodes an embedding-model change re-embeds.
Test: `uv run pytest -q --ignore=backend/tests/integration/benchmark/test_runner_db.py` with test servers: 1,993 tests, 0 failures, 88 skipped.
Live: A1 re-run in progress. ECSS-E-ST-35-06C FAILED on the cpu_parse soft time limit (1,800 s) during formula enrichment on CPU.
Blocked on: nothing
Needs from others: S4: cpu_parse time limit for large standards (or S2 caps formula enrichment); redeploy, after which I switch on A2/B/E/G.
Next: A1 counts and the M2 check when the batch drains; A2/B/E/G on the stack after S4's word

## 2026-10-23 — DCL S2 ML — claude/infallible-swartz-58c96b
Merged / ready: A1 formula and code enrichment cap and per-stage timings. This addresses ECSS-E-ST-35-06C, which FAILED past cpu_parse's soft limit.
- `process_pdf(enrichment_max=…)` caps Docling's CodeFormula items per document; the default of 200 is the Lead's figure. Skipped items keep their layout text, and a SOFT LOW_CONFIDENCE flag names the count. The parameter is fed from pipeline_config `routes.A1.formula_enrichment_max`.
- The CIR gets `timings.json`: seconds per route stage, per Docling run (with Docling's own stage profile) and the enrichment counts.
- Measured on CPU (a 3-formula page): about 30 s per formula. Batching gives no speed-up (batch 1: 79–107 s, batch 5: 113 s, batch 16: 117 s), so Docling's batch size stays. With 200 formulas, enrichment alone would take about 100 minutes.
Blocked on: nothing
Needs from others: S1: pass pipeline_config `routes.A1.formula_enrichment_max` from office_run to `process_pdf(enrichment_max=)`. Lead: a lower default (about 30 formulas, roughly 15 min) or GPU enrichment, given about 30 s per formula on CPU
Next: the four A1 crop defects (clip to the region bbox, handwriting crop gate, table crops, contact sheet)
