# Open WebUI Pipe (engine model, event mapping)

| Field | Value |
|-------|-------|
| Feature id | `frontend/openwebui-pipe` |
| Status | in-progress (Pipe built and tested against the recorded stream; live run waits for the engine, M8) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §2.1 |
| Last updated | 2026-10-23 |

## Purpose

The Pipe function that exposes the Answer Engine as a model, maps engine SSE events to status/source/embeds/confirmation, with Valves and UserValves.

## Location

Code:
- `frontend/openwebui/pipe_manastu_engine.py` (the Pipe: Valves, UserValves, `pipes()` → `manastu_engine.main`, event mapping)
- `frontend/openwebui/api_endpoint.py` (every backend call: signed identity headers, SSE parser, `stream_answer`, `confirm`, `get_trace`; mirror of `api_endpoint.ts`)
- `frontend/openwebui/config.py` (`build_config` from the Valves; mirror of `config.ts`)
- `frontend/openwebui/build_functions.py` → `frontend/openwebui/bundled/manastu_engine.py` (generated single file to install; never edit)
- `frontend/openwebui/install_functions.py` + `frontend/openwebui/README.md` (install into the stack's Open WebUI through its admin API; a person runs it with an API key after creating the admin account)

Tests and fixtures:
- `backend/tests/unit/openwebui/test_install.py` (fake Open WebUI admin API: idempotent, valves, actions on the engine model only, dry run)
- `backend/tests/unit/openwebui/test_pipe.py` (replays S2's `backend/tests/unit/llm_engine/engine/example_answer_stream.sse` through both the source and the bundle)

## Interfaces

Provides:
- Model "Manastu Propulsion Engine", id `manastu_engine.main` (install `bundled/manastu_engine.py` as function id `manastu_engine`)
- Valves: `ENGINE_URL`, `ENGINE_SHARED_SECRET`, `CONSOLE_URL`, `DEFAULT_THINKING_LEVEL`, `SHOW_STATUS_EVENTS`, `MAX_EMBEDS_PER_MESSAGE`, `MAX_ATTACHMENT_MB`; UserValves `strict_numbers`, `show_debug_trace`

Consumes:
- `POST /v1/answer` (SSE), `POST /v1/answer/{trace_id}/confirm` (backend/api/engine.py, S2); identity = HMAC over `DCL_PIPE_SHARED_SECRET`
- `POST /assets/upload` (backend/api/assets.py, S3): Pipe identity only; 25 MB cap (413); slot = presigned PUT + GET for `s3://dcl-exports/uploads/{user}/{uuid}`, 15 minutes; objects expire after 24 hours (S4 lifecycle rule); never indexed
- Open WebUI v0.12.3 APIs, checked against its source: `__user__`, `__event_emitter__`, `__event_call__`, `__metadata__`, `__task__`, `open_webui.models.groups.Groups.get_groups_by_member_id` (groups are not in `__user__`)

Event mapping: step → `status` (and `<details type="tool_calls">` when `show_debug_trace`); token → text; citation → one `source` per document (`document[]` = cited passages, url = Console viewer link, marks for provenance, translation and "⚠ unverified extraction"); embed → `embeds` with the iframe height script; needs_confirmation → `confirmation` dialog, only `True` counts as consent, reply sent to `/confirm` (declined if the event has no `trace_id`); done → final markdown if nothing streamed, caveats not already in the text, `chat:message:follow_ups`, final status; error / HTTP error / unreachable → yields `{"error": {"detail": …}}`, which Open WebUI shows as the message error. Skill mentions (DECISIONS 2026-10-23): Open WebUI v0.12.3 writes a $-mention into the message text as `<$skillId|label>` (or `</skillId|label>`) and lists ids in `__metadata__.chat_context.mentioned_skill_ids`; the Pipe takes the last user message's mentions in order, then the listed ids, looks each up in Open WebUI's Skills model (`api_endpoint.skill_playbook`) and sends the first skill tagged `dcl-playbook:<intent>` (S2's `publish_skills.py`) as `options.playbook_hint`; untagged skills are ignored, a failed lookup never blocks the answer, and the tags reach the engine as their labels. Open WebUI's background tasks (`__task__`: title, tags, follow-ups) never reach the engine; follow-ups are answered from the engine's last answer in that chat. Chat attachments: for each file in `__files__` owned by the requesting user (read via `open_webui.models.files.Files` and `open_webui.storage.provider.Storage`) and within `MAX_ATTACHMENT_MB`, the Pipe asks `POST /assets/upload` for a slot, PUTs the bytes and sends `{name, mime_type, url: get_url}`; a failed or oversized file is skipped with a notification and never blocks the answer.

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/openwebui/pipe_manastu_engine.py`
- `frontend/openwebui/api_endpoint.py`
- `frontend/openwebui/config.py`
- `frontend/openwebui/build_functions.py`, `frontend/openwebui/bundled/` (regenerate only)
- `frontend/openwebui/install_functions.py`, `frontend/openwebui/README.md`, `backend/tests/unit/openwebui/test_install.py`
- `backend/api/assets.py` (upload route), `backend/tests/unit/api/test_assets.py`
- `backend/tests/unit/openwebui/test_pipe.py`

## Rubric (what "done" means for this feature)

- [x] Citations render with Console deep links (one `source` per document, url = viewer link; replay test)
- [x] Never emits delta.tool_calls (only text and `{"error": …}` are yielded; replay test)
- [x] Error states surface in chat (501, 401, 502, unreachable, `error` event, missing Valves; tests)
- [x] The engine's own verifier accepts the Pipe's signed headers; a tampered body is refused
- [x] The installable bundle is current and passes the same tests
- [x] Install script for the stack's Open WebUI (create/update, activate, valves, actions on the engine model), tested against the v0.12.3 routes
- [ ] Installed in the stack's Open WebUI by the admin (after S4 brings it up and the admin account exists)
- [ ] Pilot run in a real Open WebUI against the live engine (M8/M9)
- [x] $-mentioned DCL playbook skill → `playbook_hint` (first tagged mention; tags become labels; source and bundle tests)
- [x] Attachments forwarded through `POST /assets/upload` (only the user's own files, size-capped, failures skipped with a notification)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

Verify:

```bash
uv run python frontend/openwebui/build_functions.py --check
uv run python -m pytest backend/tests/unit/openwebui
```

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | S3 | Skill mention → `AnswerOptions.playbook_hint` through the `dcl-playbook` tag; mention tags become labels |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S3 | Pipe, api_endpoint.py, config.py, single-file build, replay tests |
| 2026-10-22 | S3 | Install script and README for the stack's Open WebUI (Lead request: Open WebUI on the stack now) |
| 2026-10-22 | S3 | Chat attachments via `POST /assets/upload` (Lead decision); bundler accepts parenthesized inline imports |

## Related

- `.wiki/index.md`
- `backend/answer-engine` (the `/v1/answer` contract)
- `frontend/openwebui-actions-skills` (Show trace uses `api_endpoint.get_trace`)
- `frontend/viewer` (citation links)
