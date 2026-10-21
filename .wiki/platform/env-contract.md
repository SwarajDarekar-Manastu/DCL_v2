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
- `backend/config.py` (skeleton: `ROLE` only; full contract in progress)
- `.env.example`
- `.gitignore`
- `pyproject.toml`, `uv.lock` (shared dependency list; owners add their deps in their merge requests)

Tests and fixtures:
- `backend/tests/unit/config/test_settings.py` (planned)
- `backend/tests/unit/test_main.py` (ROLE handling of `backend/main.py`)

## Interfaces

Provides:
- `backend.config.get_settings()` → frozen `Settings`; `Role` (`api` | `models` | `all`); `ConfigError` raised at startup with variable names only

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

- [ ] Every refusal rule has a test
- [ ] No secret value ever appears in logs or images
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S4 | Repository skeleton of file 10 §2: packages, `backend/main.py` mounting routers by `ROLE`, stub routers, `pyproject.toml`/`uv.lock`, `.env.example` (names only), `.gitignore` data patterns anchored to the root so `backend/postgres/models/` is tracked |

## Related

- `.wiki/index.md`
