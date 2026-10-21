# Environment contract loader and .env.example

| Field | Value |
|-------|-------|
| Feature id | `platform/env-contract` |
| Status | in-progress |
| Owner session | S4 |
| Spec | docs/architecture/01_system_overview_and_tech_stack.md §7.1 |
| Last updated | 2026-10-21 |

## Purpose

Typed settings from .env per file 01 §7.1: refuses placeholders, refuses GOOGLE_API_KEY, validates DCL_PERMISSION_OPTION; .env.example with names only.

## Location

Code:
- `backend/config.py`
- `.env.example`
- `.gitignore`
- `pyproject.toml`, `uv.lock` (shared dependency list; owners add their deps in their merge requests)

Tests and fixtures:
- `backend/tests/unit/config/test_settings.py`
- `backend/tests/unit/test_main.py` (ROLE handling of `backend/main.py`)

## Interfaces

Provides:
- `backend.config.get_settings()` → frozen `Settings`, cached; process env first, then `.env` at the repository root
- `Settings.require(Group.X, …)` (also accepts the string names): `graph`, `gemini`, `alerts`, `database`, `redis`, `minio`, `models`, `links`, `console_auth`, `pipe`; raises `ConfigError` naming the missing variables
- `Settings.stack_database_url()`: `DCL_DATABASE_URL` when set, else `postgresql+psycopg://user:pass@postgres:5432/dcl`
- Dev defaults only when `DCL_ENV=dev`: `redis_url`, `minio_endpoint`, `models_url`, `api_base_url`, `console_base_url`, `console_allowed_origins`; staging/prod need explicit values
- `DCL_ROLE` (deprecated alias `ROLE`, warning logged); `GEMINI_GATEWAY_KEY` with legacy alias `DCL_GEMINI_API_KEY`
- Load-time refusals: `GOOGLE_API_KEY` present, `AIza…` in either gateway-key name, placeholders, bad `DCL_ENV`/`DCL_PERMISSION_OPTION`/`DCL_AUTH_MODE`/`GEMINI_BACKEND`, malformed values, non-Fernet `DCL_TOKEN_CACHE_KEY`, folder lists of different length
- Attribute names used by others: S3 `tenant_id`, `console_api_audience`, `console_group_{reviewers,admins,external_search}`, `console_allowed_origins`, `redis_url`; S1 `token_cache_key`, `test_outside_drive_id`
- Manual-sync tests: `.env.example` and the loader must cover every name of file 01 §7.1
- Not yet: `pipeline_config` typed access (needs S1's DB session)

Consumes:
- (none yet)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/config.py`
- `.env.example`
- `.gitignore`
- `pyproject.toml`, `uv.lock`
- `backend/tests/unit/config/test_settings.py`
- `backend/tests/unit/test_main.py`

## Rubric (what "done" means for this feature)

- [x] Every refusal rule has a test
- [ ] No secret value ever appears in logs or images (messages and repr tested; image scan comes with CI)
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S4 | Repository skeleton of file 10 §2: packages, `backend/main.py` mounting routers by `ROLE`, stub routers, `pyproject.toml`/`uv.lock`, `.env.example` (names only), `.gitignore` data patterns anchored to the root so `backend/postgres/models/` is tracked |
| 2026-10-21 | S4 | Wiring and Console names, `DCL_ENV` dev defaults, `DCL_ROLE`, key alias + `AIza` refusal, DB URL composition, S1's token-cache key and outside drive id; tests that `.env.example` and the loader match file 01 §7.1 |
| 2026-10-21 | S4 | Full env contract loader: typed settings, load-time refusals, `require(Group)`, refusal tests; real `.env` loads (Gemini group incomplete: `GEMINI_BACKEND`, `GEMINI_GATEWAY_URL` absent) |

## Related

- `.wiki/index.md`
