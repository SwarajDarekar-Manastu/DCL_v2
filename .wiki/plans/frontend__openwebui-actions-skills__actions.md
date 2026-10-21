# Plan: frontend/openwebui-actions-skills — Show trace and Report issue

| Field | Value |
|-------|-------|
| Feature | `frontend/openwebui-actions-skills` (map: `.wiki/frontend/openwebui-actions-skills.md`) |
| Session | S3 |
| Branch | claude/cranky-rhodes-0cb23f |
| Opened | 2026-10-22 |
| Delete when | rubric below is green and the map page is updated |

## Intent

One Open WebUI Action function `manastu_actions` with sub-actions (file 08 §2.2): **Show trace** looks up the trace by chat and message id (`GET /v1/traces?chat_id&message_id`, S2) and returns an inline Rich UI embed with the timeline (tool calls with durations, retrieved passages with ranks and scores, verifier verdicts, viewer links); **Report issue** asks for the reason and a comment and posts `POST /v1/traces/{id}/feedback` (S2). Calls go through `frontend/openwebui/api_endpoint.py`, the bundle through `build_functions.py`. **Add to benchmark** waits for the benchmark models (Lead question 2026-10-22). Checked against Open WebUI v0.12.3 (`utils/actions.py`, `process_tool_result`).

## Workspace

Files to change (exact):
- `frontend/openwebui/actions_manastu.py`, `frontend/openwebui/api_endpoint.py`, `frontend/openwebui/build_functions.py`, `frontend/openwebui/bundled/manastu_actions.py`
- `backend/tests/unit/openwebui/test_actions.py`

## Rubric for this task

- [ ] Show trace renders an inline embed (HTMLResponse with `Content-Disposition: inline`) with every value escaped; "no trace" and 501 become readable notifications
- [ ] Report issue maps the answer to one of the five feedback kinds and posts it signed; cancel sends nothing
- [ ] Bundle has no `frontend.` imports; tests run on source and bundle; ruff passes
