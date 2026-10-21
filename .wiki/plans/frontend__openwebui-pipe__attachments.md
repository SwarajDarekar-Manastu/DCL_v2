# Plan: frontend/openwebui-pipe — chat attachments

| Field | Value |
|-------|-------|
| Feature | `frontend/openwebui-pipe` (map: `.wiki/frontend/openwebui-pipe.md`) |
| Session | S3 |
| Branch | claude/cranky-rhodes-0cb23f |
| Opened | 2026-10-22 |
| Delete when | rubric below is green and the map page is updated |

## Intent

Forward files attached in chat to the engine as answer-time inputs (Lead decision 2026-10-22). `POST /assets/upload` (Pipe identity, HMAC) returns a presigned PUT and GET for a fresh `s3://dcl-exports/uploads/{user}/{uuid}` object (24-hour lifecycle, S4). The Pipe reads each attached file through Open WebUI's `Files` table and `Storage` (only the requesting user's own files, size-capped), PUTs it, and sends the GET URLs as `AnswerRequest.attachments`. Uploads are never indexed.

## Workspace

Files to change (exact):
- `backend/api/assets.py`, `backend/tests/unit/api/test_assets.py`
- `frontend/openwebui/api_endpoint.py`, `frontend/openwebui/pipe_manastu_engine.py`, `frontend/openwebui/bundled/manastu_engine.py` (regenerated)
- `backend/tests/unit/openwebui/test_pipe.py`

Files explicitly out of scope:
- `backend/storage/minio.py` (`presign_put`, asked of S1 2026-10-22), lifecycle rule (S4)

## Rubric for this task

- [ ] Only a signed Pipe identity can request an upload; size above the cap → 413; key is `uploads/{sanitized user}/{uuid}` in `dcl-exports`
- [ ] The Pipe uploads only files owned by the requesting user, skips oversized ones with a notification, and sends `{name, mime_type, url}` per file
- [ ] An upload failure never blocks the answer: the file is skipped with a notification
- [ ] Unit tests, bundle check and ruff pass
