# Open WebUI Actions, Filter and Skills publication

| Field | Value |
|-------|-------|
| Feature id | `frontend/openwebui-actions-skills` |
| Status | in-progress (all three actions built; Filter deferred by the Lead until attachments need a size cap; Skills are S2's) |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §1, §2.2, §3.1 |
| Last updated | 2026-10-21 |

## Purpose

Actions 'Show trace', 'Add to benchmark', 'Report issue'; Filter attaching user policy; publishing playbooks as Skills; the single gateway connection for plain Gemini chat.

## Location

Code:
- `frontend/openwebui/actions_manastu.py` (one Action function, id `manastu_actions`, sub-actions `show_trace`, `add_to_benchmark`, `report_issue`)
- `frontend/openwebui/api_endpoint.py` (`find_trace`, `send_feedback`, `create_benchmark_draft`, `open_webui_groups`)
- `frontend/openwebui/bundled/manastu_actions.py` (generated single file to install; `build_functions.py`)
- `frontend/openwebui/filter_policy.py` (planned; deferred, see below)
- `frontend/openwebui/skills/` (S2 publishes the playbooks)

Tests and fixtures:
- `backend/tests/unit/openwebui/test_actions.py` (source and bundle)

## Interfaces

Provides:
- "Show trace": inline Rich UI embed (HTMLResponse with `Content-Disposition: inline`) with tool calls, retrieved passages with viewer links, claims and verifier summary; every value escaped
- "Add to benchmark": asks for the suite (default `from-chat`) and posts a draft prefilled from the trace: question, verified numeric claims (value and unit parsed from the claim, 1 % tolerance), cited documents and pages, tools used, category `TELEMETRY_MATH` when `query_telemetry` ran; a reviewer approves it in the Console
- "Report issue": input dialog with five numbered reasons (wrong number, citation, missing document, unit or extraction, translation) and a comment; cancel sends nothing

Consumes:
- `GET /v1/traces?chat_id&message_id`, `POST /v1/traces/{trace_id}/feedback` (backend/api/engine.py, S2; 501 until M8)
- `POST /benchmark/drafts` (backend/api/benchmark.py, S3; signed Pipe identity)
- Open WebUI v0.12.3 Action API (`utils/actions.py`: `actions` list, `__id__`, `process_tool_result`)

The Filter of 08 §1 is deferred (Lead decision 2026-10-22): the Pipe already signs the user's groups and the engine applies policy from them; revisit only to cap attachment size.

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/openwebui/actions_manastu.py`
- `frontend/openwebui/api_endpoint.py` (trace and feedback calls)
- `frontend/openwebui/build_functions.py`, `frontend/openwebui/bundled/` (regenerate only)
- `frontend/openwebui/skills/`
- `backend/tests/unit/openwebui/test_actions.py`

## Rubric (what "done" means for this feature)

- [x] Show trace renders an inline embed from the message's trace; a missing trace or 501 is a readable notification (live 2026-10-23)
- [x] Report issue posts one of the five kinds, signed; cancel or a reply without a reason number sends nothing
- [x] 'Add to benchmark' creates a draft case prefilled from verified claims (the prefill validates as the API's `DraftFromChat`)
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
| 2026-10-23 | S3 | Live against S2's trace routes: Show trace renders as an embed; Report issue appends the feedback row and, naming a page source ([n]), opens a SOFT CONFLICT; Add to benchmark creates a draft with question, verified number, tools, cited document and trace; draft citations now carry the page from serialized anchors |
| 2026-10-23 | S3 | Installed live; Show trace, Report issue and Add to benchmark reach the engine and stop at S2's 501 trace routes (notification shown); 13 playbook skills published (S2's script) |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S3 | Show trace and Report issue actions, single-file bundle, tests |
| 2026-10-22 | S3 | Add to benchmark action against `POST /benchmark/drafts` |

## Related

- `.wiki/index.md`
- `frontend/openwebui-pipe` (shared api_endpoint.py, config.py and bundler)
- `backend/answer-engine` (trace and feedback routes)
- `frontend/benchmark-ui` (Add to benchmark drafts)
