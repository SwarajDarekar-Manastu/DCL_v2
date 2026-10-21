# Plan: platform/env-contract — service wiring and Console names, DCL_ROLE, key alias; gemini types split

| Field | Value |
|-------|-------|
| Feature | `platform/env-contract`, `platform/gemini-gateway-client` |
| Session | S4 |
| Branch | claude/gifted-hofstadter-0bec1c |
| Opened | 2026-10-21 |
| Delete when | rubric below is green and both map pages are updated |

## Intent

Follow-up requested by the Lead. Add the 2026-10-21 names of file 01 §7.1 to the loader and `.env.example`: service wiring (`DCL_ENV`, `DCL_ROLE`, `DCL_REDIS_URL`, `DCL_MINIO_*`, `DCL_MODELS_URL`, `DCL_API_BASE_URL`, `DCL_CONSOLE_BASE_URL`, `DCL_PIPE_SHARED_SECRET`), the compose-only `DCL_MINIO_ROOT_USER`/`_PASSWORD`, and the five `DCL_CONSOLE_*` names. Dev defaults apply only when `DCL_ENV=dev`; in staging/prod the values must be explicit (`require`). `ROLE` stays as a deprecated alias of `DCL_ROLE`. `GEMINI_GATEWAY_KEY` falls back to the legacy `DCL_GEMINI_API_KEY`; either is refused when it has the `AIza…` Developer-key shape. Database URL: `DCL_DATABASE_URL` wins, otherwise built from user/password with host `postgres:5432`. Separately, move the gateway client's types, enums and errors into `gemini_types.py` with no behavior change; `gemini_client` re-exports them so callers keep their imports.

## Workspace

Files to change (exact):
- `backend/config.py`, `.env.example`, `backend/main.py`
- `backend/tests/unit/config/test_settings.py`, `backend/tests/unit/test_main.py`
- `backend/llm_engine/gemini_client.py`, `backend/llm_engine/gemini_types.py` (new), `backend/llm_engine/gemini_probe.py`
- `backend/tests/unit/llm_engine/test_gateway_isolation.py` (allow-list unchanged unless the alias name needs it)
- `pyproject.toml`, `uv.lock` (httpx2 in dev deps if it resolves)
- `.wiki/platform/env-contract.md`, `.wiki/platform/gemini-gateway-client.md`, `.wiki/index.md`, `docs/sessions/STATUS.md`

## Rubric for this task

- [ ] Every new name is read, typed and listed in `.env.example` without values (test compares against file 01 §7.1)
- [ ] Dev defaults only in dev; staging/prod `require` names the missing values (tests)
- [ ] `DCL_ROLE` works, `ROLE` still works, `DCL_ROLE` wins when both are set (tests)
- [ ] Key fallback and `AIza` refusal for both names (tests); no value in messages
- [ ] Database URL composition and precedence (tests)
- [ ] `gemini_client.py` under 600 lines; existing client and probe tests pass unchanged
- [ ] `uv run pytest` and `uv run ruff check backend` pass; real `.env` loads (names-only report)

## Verification commands

```bash
uv run pytest -q && uv run ruff check backend && wc -l backend/llm_engine/gemini_client.py
```
