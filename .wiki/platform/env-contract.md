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
- `backend.config.get_settings()` → frozen `Settings`, cached; reads the process env, then `.env` at the checkout root if present (process env wins)
- `Settings.require(Group.GRAPH | Group.GEMINI | Group.ALERTS, …)`: call at component startup; raises `ConfigError` naming the missing variables
- `Role`, `PermissionOption`, `ThinkingLevel`, `Group`, `ConfigError`; secrets are `SecretStr` (`.get_secret_value()` only where used)
- Load-time refusals (every process): `GOOGLE_API_KEY` present, placeholder values, `DCL_PERMISSION_OPTION` ∉ {A,B}, `DCL_AUTH_MODE` ≠ delegated, `GEMINI_BACKEND` ≠ gateway, malformed typed values, folder id/path lists of different length
- Not yet in the contract (pending Lead): MinIO, Redis, Console auth names, `DCL_GEMINI_API_KEY`, database URL composition; `pipeline_config` typed access (needs S1's DB session)

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
| 2026-10-21 | S4 | Full env contract loader: typed settings, load-time refusals, `require(Group)`, refusal tests; real `.env` loads (Gemini group incomplete: `GEMINI_BACKEND`, `GEMINI_GATEWAY_URL` absent) |

## Related

- `.wiki/index.md`
