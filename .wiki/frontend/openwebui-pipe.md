# Open WebUI Pipe (engine model, event mapping)

| Field | Value |
|-------|-------|
| Feature id | `frontend/openwebui-pipe` |
| Status | planned |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §2.1 |
| Last updated | 2026-10-21 |

## Purpose

The Pipe function that exposes the Answer Engine as a model, maps engine SSE events to status/source/embeds/confirmation, with Valves and UserValves.

## Location

Code:
- `frontend/openwebui/pipe_manastu_engine.py`

Tests and fixtures:
- `backend/tests/integration/openwebui/test_pipe.py`

## Interfaces

Provides:
- model 'Manastu Propulsion Engine' in Open WebUI

Consumes:
- /v1/answer SSE (backend/answer-engine)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `frontend/openwebui/pipe_manastu_engine.py`
- `backend/tests/integration/openwebui/test_pipe.py`

## Rubric (what "done" means for this feature)

- [ ] Citations render with Console deep links
- [ ] Never emits delta.tool_calls
- [ ] Error states surface in chat
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |

## Related

- `.wiki/index.md`
