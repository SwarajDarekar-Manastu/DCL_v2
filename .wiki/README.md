# .wiki conventions (the schema for this wiki)

## 1. What this folder is

A persistent, incrementally maintained map of the repository, inspired by the LLM-wiki pattern: the raw sources (`docs/architecture/**` and the code) are never edited to record knowledge about features; instead every feature has **one map page** here that says what it is, where it lives, which files make up its workspace, which interfaces it provides and consumes, and the rubric that defines "done". Agents read the map first and go straight to the right files instead of traversing the repository.

Three layers:

| Layer | Owner | Mutability |
|-------|-------|------------|
| Raw sources: `docs/architecture/**` (normative design), code, tests | Lead (docs), role sessions (code) | changed only by their owners for their own reasons |
| Wiki: this folder | the session that owns the feature; Lead for indexes | kept current on every change |
| Schema: this README | Lead | rarely |

## 2. Layout

```
.wiki/
  README.md            this schema
  index.md             top-level map: areas, all features, active plan sheets
  backend/index.md     + one map page per backend feature (S1 pipeline/data, S2 ML/engine)
  frontend/index.md    + one map page per frontend feature (S3)
  platform/index.md    + one map page per platform feature (S4)
  quality/index.md     + one map page per quality feature (S5)
  plans/               temporary plan sheets, one per task in progress (deleted on completion)
  _templates/          feature-map.md and plan-sheet.md
```

Feature ids are `area/slug` and double as file names (`backend/route-c-telemetry.md`).

## 3. The workflow for any task (new feature, change, fix)

1. **Open the map.** Read `index.md`, then the feature's map page. If the feature does not exist, create its map page from `_templates/feature-map.md` with status `planned` and add it to the area index and to `index.md`.
2. **Write a plan sheet** at `plans/<area>__<slug>__<short-task>.md` from `_templates/plan-sheet.md`. It contains: the intent in one paragraph; the **workspace** (the exact files to read and to change, copied from the map and trimmed or extended for this task); the steps; the **rubric** (the feature's rubric items this task must satisfy plus task-specific checks); the verification commands; risks. Add a row to "Active plan sheets" in `index.md`.
3. **Work only inside the workspace.** If the task turns out to need a file outside it, update the plan sheet first (that is the signal that the map's workspace was incomplete) and, if the file belongs to another session, message that session instead of editing.
4. **Finish against the rubric.** Every rubric item is checked by running something, not by reading the code.
5. **Update the map page**: status, location (if files moved or were added), interfaces, workspace, and a dated change-log line. Update the area index and `index.md` status.
6. **Delete the plan sheet** and its row in `index.md`. Plan sheets never reach `main`; a merge request with a plan sheet still present is sent back.
7. Append your `docs/sessions/STATUS.md` entry.

A plan sheet is the only place where task-specific thinking lives, so the original documents stay undisturbed.

## 4. Rules

- One map page per feature; no page longer than ~150 lines. Split a feature when its workspace grows past ~25 files.
- The workspace list is kept exact. It is what lets the next agent isolate a change.
- Rubrics are checkable statements, one per line, with checkboxes. "Works" is not a rubric item.
- Every map page links its spec section in `docs/architecture/`. The manual says *why and what*; the map says *where and when done*.
- Cross-feature links use the feature id. When you discover a connection, add it to both pages' "Related" sections.
- Never put secrets, data samples or long code in the wiki.
- Keep the design manual authoritative: if the code must deviate from the manual, the Lead changes the manual first; the map then follows.

## 5. Lint (Lead, at every merge round)

- Every map page's Location and Workspace paths exist in the repository (or are marked `(planned)`).
- Every map page is listed in its area index and in `index.md`; statuses agree.
- No file under `plans/` on `main`; every plan sheet on a branch has a row in `index.md`.
- Every feature with status `done` has a change-log entry and a green rubric.
- Links resolve. Dates are present.

## 6. Sessions and ownership

Each role session owns the map pages of the features it owns (see `docs/sessions/README.md`). The Lead owns the indexes and this schema and updates them at merge time. A session may add a "Related" link to another session's page; anything more goes through a message.
