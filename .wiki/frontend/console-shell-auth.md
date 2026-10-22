# Console shell, Entra ID login, roles, websocket

| Field | Value |
|-------|-------|
| Feature id | `frontend/console-shell-auth` |
| Status | in-progress (code and tests done; waits for the Console auth settings in `backend/config.py`, S4) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §2.3, §4.1, §4.3, §7 |
| Last updated | 2026-10-21 |

## Purpose

SvelteKit SPA shell (static adapter, no SSR) with Entra ID login through MSAL browser (redirect + PKCE), server-side role mapping, the top navigation of file 08 §4.1, and the websocket channel for case updates, run progress and ops counters.

## Location

Code:
- `frontend/console/package.json`, `svelte.config.js`, `vite.config.ts`, `tsconfig.json`, `.env.example` (pinned: SvelteKit 2.70.3, Svelte 5.57, Vite 7.3, TypeScript 5.9, Vitest 4.1, MSAL browser 4.30)
- `frontend/console/src/lib/config.ts` (the only reader of `VITE_*`)
- `frontend/console/src/lib/api_endpoint.ts` (the only file that fetches or opens a websocket)
- `frontend/console/src/lib/auth/` (`msal.ts` Entra client, `roles.ts` role rank and nav, `session.svelte.ts` signed-in state)
- `frontend/console/src/lib/components/shell/` (`NavBar.svelte`, `RoleGate.svelte`)
- `frontend/console/src/routes/+layout.svelte`, `+layout.ts`, `+page.svelte`, placeholder pages `review/ benchmark/ entities/ settings/ ops/ audit/`
- `backend/api/auth.py`, `backend/api/ws.py`
- `frontend/console/Dockerfile`, `nginx.conf`, `.dockerignore` (node build → nginx; every route served by index.html so chat deep links resolve; `/healthz`; immutable cache for `/_app/immutable/`; VITE_* as build arguments). S4 wires it into compose.

Tests and fixtures:
- `frontend/console/tests/` (config, roles, api_endpoint, msal, session, NavBar, RoleGate)
- `backend/tests/unit/api/` (`conftest.py` with a local RSA key standing in for Entra JWKS, `test_auth.py`, `test_ws.py`)

## Interfaces

Provides:
- `backend.api.auth`: `ConsoleRole` (`viewer` < `reviewer` < `admin`), `ConsoleUser`, `CurrentUser` (Annotated dependency), `require_role(role)`, `verify_token`; route `GET /auth/me`
- `backend.api.ws`: `/ws` (first frame `{"type":"auth","token"}` within 5 s, then `subscribe`/`unsubscribe` topics `case` (reviewer), `run`, `ops`; close 4401 = re-authenticate, 4400 = bad frame); `Event`, `EVENTS_CHANNEL = "dcl:console:events"`, `publish_event(redis_client, event)` for workers; `redis_bridge(redis_url)` for the API lifespan
- Ops event contract used by the nav badge: topic `ops`, key `review_counts`, data `{hard, soft}`
- Console: `api_endpoint.ts` (`configureApi`, `getMe`, `openLiveChannel`, `ApiError`), `session`, `hasRole`, `RoleGate`

Consumes:
- `backend.config.get_settings()` attributes `tenant_id`, `console_api_audience`, `console_group_reviewers`, `console_group_admins`, `console_allowed_origins`, `redis_url`, `env`, and `console_dev_auth`, `console_dev_token`, `console_dev_roles` (S4; read with a safe default until S4's loader has them)
- Entra ID: one SPA app registration (redirect URI = Console origin) and one API registration exposing `access_as_user`, `accessTokenAcceptedVersion = 2`, groups claim limited to groups assigned to the application

Role rule: any authenticated user of the tenant is `viewer`; `dcl-reviewers` adds `reviewer`; `dcl-admins` adds `reviewer` and `admin`. Roles always come from the server (`/auth/me`), never from the client token. Tokens with group overage are refused with 403. Nav visibility: Review and Audit need reviewer, Settings needs admin, the rest viewer.

After a redirect sign-in MSAL returns to the page that asked for it (`navigateToLoginRequestUrl`, `redirectStartPage`), so a citation opened while signed out lands on that citation.

Dev-only sign-in (user-approved exception, DECISIONS 2026-10-22): the backend accepts `Authorization: Bearer <DCL_CONSOLE_DEV_TOKEN>` as a fixed dev identity (`dev-sign-in`, roles from `DCL_CONSOLE_DEV_ROLES`) only when `DCL_ENV=dev` and `DCL_CONSOLE_DEV_AUTH=true`; constant-time comparison; every use logged as a warning; the flag outside dev answers 503 with a critical log (S4's loader also refuses to start); a token shorter than 32 characters or an unknown role answers 503. The Entra path is unchanged and still answers 503 naming missing settings. `VITE_AUTH_MODE=dev` works only under the Vite dev server: `vite.config.ts` defines `VITE_DEV_TOKEN` from the repository `.env` when serving in development only, so builds never contain it (checked by grepping the build). The user and roles come from `GET /auth/me`; there is no client-side fake user. The websocket accepts the dev token the same way.

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/console/{package.json,package-lock.json,svelte.config.js,vite.config.ts,tsconfig.json,.env.example,.gitignore}`
- `frontend/console/src/{app.html,app.d.ts,app.css}`
- `frontend/console/src/lib/config.ts`
- `frontend/console/src/lib/api_endpoint.ts`
- `frontend/console/src/lib/auth/`
- `frontend/console/src/lib/components/shell/`
- `frontend/console/src/routes/{+layout.svelte,+layout.ts,+page.svelte}`
- `frontend/console/{Dockerfile,nginx.conf,.dockerignore}`
- `frontend/console/vite.config.ts` (dev sign-in token, dev server only)
- `backend/api/auth.py`
- `backend/api/ws.py`
- `frontend/console/tests/`
- `backend/tests/unit/api/`

## Rubric (what "done" means for this feature)

- [x] Login works for viewer/reviewer/admin groups (server role mapping per group set; MSAL redirect, silent token and interaction fallback with a mocked MSAL client; production build shows the sign-in screen)
- [x] Unauthorized routes are blocked server-side (`require_role`: 401 without or with a bad token, 403 for a missing role; websocket topics gated by role)
- [x] Websocket refuses unauthenticated sockets (4401) and delivers only subscribed topics
- [x] Only `api_endpoint.ts` fetches or opens a websocket (grep)
- [x] `auth.py` runs against the real settings object
- [x] Dev-only sign-in: guards tested (env, flag, token length, roles, wrong token), end to end with the real API app and the Vite dev server, no token in builds
- [ ] A login against the real tenant is demonstrated (after the user registers Entra ID)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

Verify:

```bash
cd frontend/console && npm ci && npm run check && npm test && npm run build
uv run --with 'pyjwt[crypto]' --with redis python -m pytest backend/tests/unit/api
```

Known: `npm audit` reports a low-severity advisory in `cookie` (pulled in by SvelteKit's server cookie handling); the Console is a static SPA without a SvelteKit server, so it does not apply.

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S3 | Dev-only backend sign-in (user-approved, hardened); client-side fake user removed; hermetic config test |
| 2026-10-22 | S3 | Console container (Dockerfile, nginx SPA fallback); sign-in returns to the requested page |
| 2026-10-21 | S3 | Shell, MSAL login, server role mapping, `/auth/me`, `/ws` with Redis bridge, tests |

## Related

- `.wiki/index.md`
- `platform/env-contract` (Console auth settings)
- `frontend/review-ui`, `frontend/settings-ui`, `frontend/benchmark-ui` (use `RoleGate`, `api_endpoint.ts`, live topics)
- `backend/review-backend` (publishes `case` events and the `review_counts` ops counter; protects routers with `require_role`)
