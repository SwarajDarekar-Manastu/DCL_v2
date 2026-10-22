# Answer Engine playbooks as Open WebUI Skills

One folder per playbook of `docs/architecture/07_phase3_answer_engine.md` §5 (chit-chat has none). Each `SKILL.md` has front matter (`name`, `description`, `intents`, `tools`) and the procedure in plain words. Owner: S2.

- `tools` must equal the tools the engine's planner runs for `intents`. `backend/tests/unit/llm_engine/engine/test_skills.py` builds the plan for each skill and fails on drift. Change the planner and the skill together.
- Publish (idempotent, with an Open WebUI admin API key, never printed):

  ```bash
  OWUI_API_KEY=sk-... uv run python frontend/openwebui/skills/publish_skills.py --dry-run
  OWUI_API_KEY=sk-... uv run python frontend/openwebui/skills/publish_skills.py
  ```

  `OWUI_URL` defaults to `http://localhost:$DCL_OPENWEBUI_PORT`. Skills are created as `dcl-<folder>`, active and readable by every user.
- Not attached to the engine model (`meta.skillIds`). Open WebUI injects the full text of attached skills into every request unless native function calling is on, and the engine answers from the last user message only (system messages are dropped). Users can read a skill or toggle it in a chat. Whether a toggled skill should steer the engine's planner is an open question with the Lead.
