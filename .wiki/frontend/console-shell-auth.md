# Console shell, sign-in (local accounts; Entra ID later), roles, websocket

| Field | Value |
|-------|-------|
| Feature id | `frontend/console-shell-auth` |
| Status | in-progress (local accounts built and tested; end-to-end login waits for S1's `users` model and migration 0010; then the dev-token sign-in is removed) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §2.3, §4.1, §4.3, §7 |
| Last updated | 2026-10-22 |

## Purpose

SvelteKit SPA shell (static adapter, no SSR) with local password sign-in (user decision 2026-10-22; Entra ID through MSAL is future scope and stays dormant behind `VITE_AUTH_MODE=msal`), server-side roles, the top navigation of file 08 §4.1, and the websocket channel for case updates, run progress and ops counters.

## Location

Code:
- `frontend/console/package.json`, `svelte.config.js`, `vite.config.ts`, `tsconfig.json`, `.env.example` (pinned: SvelteKit 2.70.3, Svelte 5.57, Vite 7.3, TypeScript 5.9, Vitest 4.1, MSAL browser 4.30)
- `frontend/console/src/lib/config.ts` (the only reader of `VITE_*`)
- `frontend/console/src/lib/api_endpoint.ts` (the only file that fetches or opens a websocket)
- `frontend/console/src/lib/auth/` (`msal.ts` Entra client, `roles.ts` role rank and nav, `session.svelte.ts` signed-in state)
- `frontend/console/src/lib/components/shell/`: `Sidebar.svelte` (left 240 px: areas filtered by role with `aria-current`, live HARD/SOFT counts, socket state, user with highest role, sign out), `TopBar.svelte` (sticky breadcrumb from `breadcrumbs.ts`, which also sets the document title; theme menu), `ThemeToggle.svelte` (light/dark/system, `localStorage["dcl-theme"]`, applied before first paint in `app.html`), `Page.svelte` + `PageHeader.svelte` (page frame), `Notice`, `EmptyState`, `ToneBadge`, `SeverityBadge`, `RoleGate`
- `frontend/console/src/lib/components/ui/` (shadcn-svelte components, generated) and `src/app.css` (Geist tokens, Tailwind v4); design notes in `frontend/console/REDESIGN.md`
- `frontend/console/src/routes/+layout.svelte`, `+layout.ts`, `+page.svelte`, placeholder pages `review/ benchmark/ entities/ settings/ ops/ audit/`
- `backend/api/auth.py`, `backend/api/ws.py`
- `frontend/console/Dockerfile`, `nginx.conf`, `.dockerignore` (node build → nginx; every route served by index.html so chat deep links resolve; `/healthz`; immutable cache for `/_app/immutable/`; VITE_* as build arguments). S4 wires it into compose.

Tests and fixtures:
- `frontend/console/tests/` (config, roles, api_endpoint, msal, session, Sidebar, shell, RoleGate)
- `backend/tests/unit/api/` (`conftest.py` with a local RSA key standing in for Entra JWKS, `test_auth.py`, `test_ws.py`)

## Interfaces

Provides:
- `backend.api.auth`: `ConsoleRole` (`viewer` < `reviewer` < `admin`), `ConsoleUser`, `CurrentUser` (Annotated dependency), `require_role(role)`, `verify_token`; route `GET /auth/me`
- Local accounts (`backend.api.auth`): `POST /auth/login` `{email, password}` → `{access_token, token_type, expires_at, user}` (HS256 JWT signed with `DCL_AUTH_SECRET`, iss/aud `dcl-console`, claims sub = user id, email, name, roles; TTL `DCL_AUTH_TOKEN_TTL_HOURS`; `Cache-Control: no-store`); wrong password, unknown and deactivated accounts all answer 401 "wrong email or password" with the same argon2id work; 5 failures per minute per email → 429 with `Retry-After` (in memory, per API process). Every request re-reads the account (`UserStore.get`), so deactivation and role changes apply at once. Admin routes `GET/POST /auth/users`, `PATCH /auth/users/{user_id}` (`display_name`, `roles`, `is_active`, `password` reset; 409 for a duplicate email or when the last active admin would go). While `users` is empty, the first login creates the admin from `DCL_BOOTSTRAP_ADMIN_EMAIL` / `DCL_BOOTSTRAP_ADMIN_PASSWORD` (12+ chars). Passwords: argon2id (argon2-cffi 25.1.0), 12+ chars. `SqlUserStore` is the only code that queries `users` (S1's model, migration 0010). Account changes are logged, not in `audit_events` (no `user` entity type yet). HS256 tokens take the local path; any other token the dormant Entra path.
- `backend.api.ws`: `/ws` (first frame `{"type":"auth","token"}` within 5 s, then `subscribe`/`unsubscribe` topics `case` (reviewer), `run`, `ops`; close 4401 = re-authenticate, 4400 = bad frame); `Event`, `EVENTS_CHANNEL = "dcl:console:events"`, `publish_event(redis_client, event)` for workers; `redis_bridge(redis_url)` for the API lifespan
- Ops event contract used by the nav badge: topic `ops`, key `review_counts`, data `{hard, soft}`
- Console: `api_endpoint.ts` (`configureApi` with `onUnauthorized`, `login`, `getMe`, `listAccounts`/`createAccount`/`updateAccount`, `openLiveChannel`, `ApiError`), `session` (`signInWithPassword`, `signOut`, `end`), `hasRole`, `RoleGate`; `src/lib/auth/local.ts` (token in memory + `sessionStorage["dcl-session"]`, expiry checked before each call; a 401 returns to the sign-in form with a notice); `LoginForm.svelte`; Users page `/settings/users` (`UsersAdmin.svelte`, admin)

Consumes:
- `backend.config.get_settings()` attributes `auth_secret`, `auth_token_ttl_hours`, `bootstrap_admin_email`, `bootstrap_admin_password`, `tenant_id`, `console_api_audience`, `console_group_reviewers`, `console_group_admins`, `console_allowed_origins`, `redis_url`, `env`, and `console_dev_auth`, `console_dev_token`, `console_dev_roles` (S4; read with a safe default until S4's loader has them)
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
- `frontend/console/src/routes/{+layout.svelte,+layout.ts,+page.svelte}`, `frontend/console/src/routes/settings/users/`, `frontend/console/src/lib/components/settings/{UsersAdmin.svelte,SectionMenu.svelte}`
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
- [x] Local accounts: login, same 401 for wrong/unknown/inactive, 429 on the 6th failure in a minute, tampered/expired tokens refused, deactivation and role changes apply to existing tokens, admin-only user routes, last active admin kept, bootstrap only while empty (`test_local_auth.py`)
- [x] Console local sign-in: form, token survives reload, sign out clears it, 401 returns to the form; Users page creates, changes roles, deactivates, resets passwords (vitest)
- [ ] Local login end to end against the stack (needs S1's `users` model and migration 0010); then the dev-token sign-in is removed
- [ ] A login against the real tenant is demonstrated (Entra ID, future scope)
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
| 2026-10-22 | S3 | Local password accounts (user decision): login, users admin, rate limit, bootstrap admin, Console sign-in form and Users page; MSAL dormant behind VITE_AUTH_MODE=msal |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S3 | Redesign merged (Geist + shadcn-svelte, user decision): NavBar replaced by Sidebar + TopBar, theme toggle, page frame; reviewed by S3 |
| 2026-10-22 | S3 | Dev-only backend sign-in (user-approved, hardened); client-side fake user removed; hermetic config test |
| 2026-10-22 | S3 | Console container (Dockerfile, nginx SPA fallback); sign-in returns to the requested page |
| 2026-10-21 | S3 | Shell, MSAL login, server role mapping, `/auth/me`, `/ws` with Redis bridge, tests |

## Related

- `.wiki/index.md`
- `platform/env-contract` (Console auth settings)
- `frontend/review-ui`, `frontend/settings-ui`, `frontend/benchmark-ui` (use `RoleGate`, `api_endpoint.ts`, live topics)
- `backend/review-backend` (publishes `case` events and the `review_counts` ops counter; protects routers with `require_role`)
