# Parallel development sessions

Six Claude Code sessions work on this repository at the same time: one **Lead** (the session that wrote the manual) and five **role sessions** that map to the roles in `docs/architecture/10_development_plan.md` §1. Each role session owns a set of directories, works on its own branch in its own worktree, and talks to the others through session messages and three shared files in this folder.

| Session | Name to use in messages | Brief | Owns |
|---------|-------------------------|-------|------|
| Lead | `DCL Lead` | this file | `docs/architecture/**`, `docs/sessions/**`, `.wiki` indexes, `backend/main.py` skeleton, merges to `main`, cross-session decisions |
| S1 | `DCL S1 Backend` | [S1_backend_data.md](S1_backend_data.md) | `backend/sync`, `backend/dispatcher`, `backend/routes/{c_telemetry,a2_source,b_code,e_diagrams,g_archives}`, `backend/postgres` (models, enums, migrations), `backend/storage`, `backend/celery_redis` (tasks_sync, tasks_process, tasks_review), `backend/review`, `backend/indexing/commit.py`, `backend/api/{sync,review,settings,entities}.py`, `backend/common/units.py` |
| S2 | `DCL S2 ML` | [S2_ml_llm.md](S2_ml_llm.md) | `backend/llm_engine/{vision,enrichment,prompts,engine,local_models.py}`, `backend/routes/{a1_office,d_photos,f_video}`, `backend/indexing/{chunker,anchors,identifiers,retrieval,index_document}.py`, `backend/benchmark/{runner,metrics,judge}.py`, `backend/celery_redis/tasks_embed.py`, `backend/api/{engine,models}.py`, `frontend/openwebui/skills` |
| S3 | `DCL S3 Frontend` | [S3_fullstack.md](S3_fullstack.md) | `frontend/console` (TypeScript), `frontend/openwebui` (Pipe, Actions, Filter, `api_endpoint.py`, `config.py`), `backend/api/{viewer,assets,benchmark,ws,auth,audit}.py`, `backend/benchmark/catalog.py` (case spec and queries; S2 imports `CaseSpec` from it) |
| S4 | `DCL S4 DevOps` | [S4_devops.md](S4_devops.md) | `backend/devops` (compose files, Dockerfiles, grafana, runbooks, ci, backup), `.github/workflows`, `backend/config.py` (env contract), `.env.example`, `backend/llm_engine/gemini_client.py` + `gemini_probe.py` (gateway client), `backend/common/{telemetry,logging}.py`, `backend/celery_redis/{app,queues,beat}.py`, `backend/api/health.py` |
| S5 | `DCL S5 Quality` | [S5_sme_quality.md](S5_sme_quality.md) | `backend/tests/{fixtures,benchmark,acceptance}`, `config/*.yaml`, `config/units.txt`, `config/rules`, golden benchmark cases, acceptance checks |

Layout and coding principles: `docs/architecture/10_development_plan.md` §2 and §2.1 (one `backend/main.py`, roles not services, flat folders, one `api_endpoint.ts` + `config.ts` in the Console).

## Repository

- Remote: `https://github.com/SwarajDarekar-Manastu/DCL_v2.git` (MIT). `main` tracks `origin/main`.
- Role sessions run on **Claude Opus 5.5**; the Lead runs on Fable 5.1. If a session finds itself on another model, it says so in its first message and the user switches it in the model menu.

## Non-negotiable rules for every session

1. **Follow the plan; when in doubt, stop and ask.** If something cannot be done as the manual or your brief says, or a question cannot be resolved from the manual, the wiki and the code, do not improvise. Write the question to `docs/sessions/STATUS.md`, message `DCL Lead` with it, and end your turn. The Lead raises it with the user and comes back with the decision. Deviating silently is the one thing that is never acceptable.
2. **Blocked means idle.** If you are waiting on another session's output or on a decision, write the STATUS entry, send one message to the session you wait on, and **end your turn**. Do not poll, re-read, re-plan or "prepare" while waiting; that only spends tokens. You will be messaged when the input exists.
3. **Use the wiki.** Before any task, read `.wiki/index.md` and the feature's map page; open a plan sheet from `.wiki/_templates/plan-sheet.md`; work only inside the plan's workspace; finish against the rubric; update the map page; delete the plan sheet. The full workflow is `.wiki/README.md` §3. A merge request with a stale map page or a leftover plan sheet is sent back.
4. **Stay in your directories.** Another session's file needs a message, not an edit.
5. **Never commit secrets.** `.env` is ignored; placeholders only in `.env.example`.

## How the sessions stay consistent

1. **The manual is the contract.** `docs/architecture/` is normative. If a session needs to deviate, it messages `DCL Lead` with the proposed change; the Lead edits the manual and tells every affected session. Nobody edits the manual except the Lead.
2. **Shared code has one owner.** `backend/common/**` belongs to S1 (database models, units, MinIO client) and S4 (config loader, gateway client). Another session that needs a change there sends a message with the exact request instead of editing.
3. **Interfaces are published before implementations.** Each brief lists what the session must publish first (Pydantic models, function signatures, table names, API routes) so dependents can code against stubs. Publish = merged to `main` with tests.
4. **Status goes to one file.** Every session appends an entry to `STATUS.md` at the end of each work block (what merged, what is blocked, what it needs). The Lead reads it before each merge round.
5. **Decisions go to one file.** Anything that affects more than one session is written to `DECISIONS.md` with a date, by the Lead only, after the message exchange that produced it.
6. **Messages are for handoffs, blockers and interface questions**, not status. Address a session by its name above. Keep a message to one topic with the file path and the exact question.

## Branches and worktrees

- `main` is always green (tests pass, `alembic check` passes).
- Each role session works in its own worktree on its own branch. When the app starts a session from a task chip it creates both (`.claude/worktrees/<name>`, branch `claude/<name>`); **keep that branch name** and record the session → branch mapping in `STATUS.md`. A session started manually runs `git worktree add ../dcl_v2-s1 -b s1-backend` (adjust the suffix).
- Sessions bring their branch up to date with `main` at least daily (the app's "sync with base branch" action in app-made worktrees, otherwise `git merge main`).
- Merging to `main` is done by the Lead from a session's request (message: "ready to merge: branch, scope, test command, what it publishes"). Small, frequent merges; never a week of work in one merge.
- A session never commits secrets. `.env` stays untracked (`.gitignore`); the `.env.example` with names only is owned by S4.

## Cadence

- **Start of a work block:** read `STATUS.md` and `DECISIONS.md`; sync with `main`.
- **End of a work block:** tests pass on the branch; append to `STATUS.md`; request a merge if something is publishable.
- **Lead, once or twice a day:** merge requests in order of dependency; run the full test suite on `main`; update `DECISIONS.md`; answer interface questions.

## Milestone ownership (from file 10 §5)

| Milestone | Primary | Supporting |
|-----------|---------|------------|
| M0 Foundations | S4 | S1 (schema base), S2 (embedding/reranker services) |
| M1 Sync, gate, scope, queue load test | S1 | S4 (queue config), S5 (gate fixtures) |
| M2 Routes A2/B/C + flags | S1 | S5 (fixtures, unit tests, sanity ranges) |
| M3 Review UI (MVP) | S3 | S1 (review API) |
| M4 Common tail | S2 | S1 (commit path, migrations), S5 (retrieval query set) |
| M5 Route A1 + vision | S2 | S3 (handwriting/table panes), S5 (document set) |
| M6 Full-corpus run | S1 + S4 | S5 (backlog clearing with the SME), S2 (cost tuning) |
| M7 Routes D/E/F/G | S2 (D, F), S1 (E, G) | — |
| M8 Answer engine | S2 | S5 (golden cases), S4 (DBOS, gateway) |
| M9 Open WebUI | S3 | S2 (engine API) |
| M10 Benchmarks + CI | S3 (UI), S5 (suites) | S4 (CI gate) |
| M11 Hardening | S4 | all |

## Starting a role session

Click the task chip the Lead created for the role (the app opens the session in its own worktree), choose **Claude Opus 5.5** in the model menu, and let it run. If a chip is not available, open a new session in this repository and give it this first message, adjusting the role:

```
You are "DCL S1 Backend". Read docs/sessions/README.md, docs/sessions/S1_backend_data.md and .wiki/README.md first,
then docs/architecture/00_README.md and the architecture files your brief names.
Set your session title to "DCL S1 Backend". Work only in the directories you own, on your worktree's branch.
For every task: plan sheet first, workspace only, rubric, map page update, delete the plan sheet.
When in doubt or blocked: write STATUS.md, message DCL Lead once, end your turn.
Start with the "First tasks" list in your brief.
```

Then message `DCL Lead` once with "S1 started" so the Lead knows the session's address.
