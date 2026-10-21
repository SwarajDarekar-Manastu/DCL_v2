# Plan: frontend/console-shell-auth — shell, Entra ID login, roles, websocket

| Field | Value |
|-------|-------|
| Feature | `frontend/console-shell-auth` (map: `.wiki/frontend/console-shell-auth.md`) |
| Session | S3 |
| Branch | claude/cranky-rhodes-0cb23f |
| Opened | 2026-10-21 |
| Delete when | rubric below is green and the map page is updated |

## Intent

Create the DCL Console SPA (SvelteKit 2 + TypeScript, static adapter, no SSR) with Entra ID login through MSAL browser (redirect + PKCE), role mapping (`viewer`, `reviewer`, `admin`), the top navigation of file 08 §4.1, placeholder pages for each area, and the websocket client. On the backend: `backend/api/auth.py` (JWT verification against Entra JWKS, role dependency other routers reuse, `GET /auth/me`) and `backend/api/ws.py` (`/ws` endpoint, first-message token auth, topic subscriptions, Redis pub/sub bridge). Must not touch `backend/main.py`, `backend/config.py` or any router owned by S1/S2/S4.

## Workspace

Files to read:
- docs/architecture/08_frontend_openwebui.md §2.3, §4.1, §4.3, §7; 10 §2, §2.1

Files to change (exact):
- `frontend/console/package.json`, `package-lock.json`, `svelte.config.js`, `vite.config.ts`, `tsconfig.json`, `.env.example`, `.gitignore`
- `frontend/console/src/app.html`, `src/app.d.ts`, `src/app.css`
- `frontend/console/src/lib/config.ts`, `src/lib/api_endpoint.ts`
- `frontend/console/src/lib/auth/` (`msal.ts`, `roles.ts`, `session.svelte.ts`)
- `frontend/console/src/lib/components/shell/` (`NavBar.svelte`, `RoleGate.svelte`)
- `frontend/console/src/routes/+layout.svelte`, `+layout.ts`, `+page.svelte`, and placeholder `+page.svelte` under `review/`, `benchmark/`, `entities/`, `audit/`, `ops/`, `settings/`
- `frontend/console/tests/` (shell tests)
- `backend/api/auth.py`, `backend/api/ws.py`
- `backend/tests/unit/api/test_auth.py`, `backend/tests/unit/api/test_ws.py`

Files explicitly out of scope (owned by another session → message them):
- `backend/main.py` (Lead: mounts `auth.router`, `ws.router`, starts `ws.redis_bridge` in the lifespan)
- `backend/config.py`, `.env.example` at the root (S4: Console auth settings requested 2026-10-21)
- `backend/api/{review,settings,entities}.py` (S1)

## Steps

1. Scaffold `frontend/console` with pinned versions; `npm ci` reproducible.
2. `config.ts` (VITE_* → typed config, dev auth only under the Vite dev server), `auth/` (MSAL init, login/logout, token acquisition, role derivation from `/auth/me`), `api_endpoint.ts` (fetch wrapper with bearer token, `getMe`, websocket client with auth message, topic subscribe, reconnect with backoff).
3. Layout + NavBar + RoleGate + placeholder pages.
4. `auth.py`: verify RS256 token (issuer, audience, expiry, tenant), map groups → roles, refuse group overage; `current_user`, `require_role(role)`; `GET /auth/me`.
5. `ws.py`: hub with per-topic subscriptions; auth within 5 s or close 4401; `publish` envelope; Redis bridge coroutine.
6. Tests: pytest with a locally generated RSA key and JWKS; vitest for roles, config, api_endpoint, NavBar, RoleGate.

## Rubric for this task

- [ ] (map) Login works for viewer/reviewer/admin groups: role derivation tested per group set, MSAL login flow exercised with a mocked MSAL client
- [ ] (map) Unauthorized routes are blocked server-side: `require_role` returns 401 without a token, 401 for a bad signature/audience/expired token, 403 for a missing role; tested
- [ ] (task) Websocket refuses a connection that does not authenticate within the deadline (close code 4401) and delivers only subscribed topics; tested
- [ ] (task) No file other than `api_endpoint.ts` calls `fetch` or opens a `WebSocket` (grep check)
- [ ] (task) `npm run check`, `npm test`, `npm run build` pass; built app renders the shell in dev auth mode (screenshot)
- [ ] Verification commands below pass

## Verification commands

```bash
cd frontend/console && npm ci && npm run check && npm test && npm run build
uv run --with fastapi --with 'pyjwt[crypto]' --with httpx --with pytest --with redis python -m pytest backend/tests/unit/api -q
grep -rnE "fetch\(|new WebSocket" frontend/console/src | grep -v src/lib/api_endpoint.ts   # must print nothing
```

## Risks and open questions

- Console auth env names are proposed, not yet in file 01 §7.1 (Lead and S4 messaged 2026-10-21). `auth.py` reads them through one dependency that tests override.
- Group overage (> 200 groups) cannot be resolved without a Graph call; refused with 403 and an admin hint.
