# Open WebUI Actions, Filter and Skills publication

| Field | Value |
|-------|-------|
| Feature id | `frontend/openwebui-actions-skills` |
| Status | in-progress (Show trace and Report issue built; Add to benchmark waits for the benchmark models; Filter deferred pending the Lead) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §1, §2.2, §3.1 |
| Last updated | 2026-10-21 |

## Purpose

Actions 'Show trace', 'Add to benchmark', 'Report issue'; Filter attaching user policy; publishing playbooks as Skills; the single gateway connection for plain Gemini chat.

## Location

Code:
- `frontend/openwebui/actions_manastu.py` (one Action function, id `manastu_actions`, sub-actions `show_trace`, `report_issue`)
- `frontend/openwebui/api_endpoint.py` (`find_trace`, `send_feedback`, `open_webui_groups`)
- `frontend/openwebui/bundled/manastu_actions.py` (generated single file to install; `build_functions.py`)
- `frontend/openwebui/filter_policy.py` (planned; deferred, see below)
- `frontend/openwebui/skills/` (S2 publishes the playbooks)

Tests and fixtures:
- `backend/tests/unit/openwebui/test_actions.py` (source and bundle)

## Interfaces

Provides:
- "Show trace": inline Rich UI embed (HTMLResponse with `Content-Disposition: inline`) with tool calls, retrieved passages with viewer links, claims and verifier summary; every value escaped
- "Report issue": input dialog with five numbered reasons (wrong number, citation, missing document, unit or extraction, translation) and a comment; cancel sends nothing

Consumes:
- `GET /v1/traces?chat_id&message_id`, `POST /v1/traces/{trace_id}/feedback` (backend/api/engine.py, S2; 501 until M8)
- Open WebUI v0.12.3 Action API (`utils/actions.py`: `actions` list, `__id__`, `process_tool_result`)

Not yet: "Add to benchmark" needs the benchmark enums and tables (Lead question 2026-10-22). The Filter of 08 §1 is deferred: the Pipe already signs the user's groups and the engine applies policy from them (proposal to the Lead 2026-10-22).

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/openwebui/actions_manastu.py`
- `frontend/openwebui/api_endpoint.py` (trace and feedback calls)
- `frontend/openwebui/build_functions.py`, `frontend/openwebui/bundled/` (regenerate only)
- `frontend/openwebui/skills/`
- `backend/tests/unit/openwebui/test_actions.py`

## Rubric (what "done" means for this feature)

- [x] Show trace renders an inline embed from the message's trace; a missing trace or 501 is a readable notification
- [x] Report issue posts one of the five kinds, signed; cancel or a reply without a reason number sends nothing
- [ ] 'Add to benchmark' creates a draft case prefilled from verified claims
- [ ] Only Gemini credentials exist in Open WebUI (deployment check with S4)
- [x] Tests listed above pass; status entry written; this map updated; plan sheet deleted

Verify:

```bash
uv run python frontend/openwebui/build_functions.py --check
uv run python -m pytest backend/tests/unit/openwebui
```

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S3 | Show trace and Report issue actions, single-file bundle, tests |

## Related

- `.wiki/index.md`
- `frontend/openwebui-pipe` (shared api_endpoint.py, config.py and bundler)
- `backend/answer-engine` (trace and feedback routes)
- `frontend/benchmark-ui` (Add to benchmark drafts)
