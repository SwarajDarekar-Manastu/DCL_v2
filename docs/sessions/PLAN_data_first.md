# Plan: good data first, then the answer engine

User order, 2026-10-23 (reframed by the Lead). Rule for every stage: do not start the next one until the "done when" line is true.

## Precondition (not a task)

Resume the agents on the `dcl-role` agent (Sonnet 5.5, high). The user says when. Nothing below starts until then.

## Tasks

- [x] **2. Scratch run, all eight routes (Route G: its CAD kinds only).** Throwaway Postgres and MinIO (`backend/devops/ci/test_services.sh up`, separate ports, no link to the real stack). Ingest 1 to 2 real files per route, A1 to F including the live ones, and the G CAD samples (`data/samples/G`). 
  Done when: each route has run route → flags → commit → embed against the scratch store and the results are listed per route.
  Done 2026-10-24 (user: scratch too heavy, real database used and its data kept; Route G on a throwaway database because its samples include web files). Per-route results: DECISIONS.md 2026-10-24 rows and the Lead's report.
- [x] **3. Review test on the scratch store, per flag type.** For every flag that fires: the help icon appears and reads right, the resolution works, undo works. .
  Done when: each of the nine flag types is either exercised or marked "never fires on our data".
  Done 2026-10-24: exercised UNIT_AMBIGUITY, SCHEMA_UNKNOWN, LOW_CONFIDENCE_EXTRACTION, CONFLICT; never fires on our data SENSITIVE_CONTENT, PARSE_FAILURE (both rehearsed, rolled back), UNSUPPORTED_FORMAT, HELD_LARGE_FILE, CLOUD_RESTRICTED.
- [ ] **4. Preset rules.** From each resolved flag, create a rule the reviewer can make once and apply to every matching flag ("replace X with Y": unit by column name, column mapping, source choice, supersession). Use the dry run to show what it would change, then apply and undo. 
  Done when: for each flag type that fires, one preset rule resolves a second, different file without a click.
  Blocked 2026-10-24 (user decision): only Route C reads rules, and under the 2026-10-24 ruling a rule only proposes; `ignore_pattern`, `supersession`, `schema_mapping`, `origin_override` are stored and read by nothing.
- [ ] **5. Cheapest model that works for the suggestions.** Where a model suggests a unit, a column or a source, test gemini-3.1-flash-lite on the gold data; if it misses, step up to 3.8-flash, and record the choice per task. Rules themselves are deterministic; the model only proposes.
  Done when: each suggestion task has a measured accuracy and a chosen model.
  Blocked 2026-10-24 (user decision): no suggestion is made by a model today (Route C's are deterministic; the Gemini fallback of file 06 §4 is not built) and the gold has no unit, column or source labels.
- [ ] **6. Delete the scratch stores.** Remove the throwaway Postgres and MinIO containers and volumes after tasks 2 to 5 pass. 
  Done when: no scratch container or volume remains; the real stack is untouched.
  Skipped by the user (real database used). The one throwaway store made (Route G, database `dcl_g_scratch` and its MinIO objects) was deleted.
- [x] **7. Result cache.** Save every Gemini result the moment it arrives, keyed by content, prompt version and model id, so a failed save or a network outage never loses paid work and a re-run reads the cache. Cache hits shown in the ledger.
  Done when: killing the gateway connection in the middle of a document and re-running it makes no repeated model call.
  Done 2026-10-24: `test_result_cache.py`; live, every route's re-run wrote only `cache_hit` rows (vision hits too).

- [ ] **8. Real ingest of the test folders.** Run all E1 to E13 on the real stack. Map every flag that fires into a table: flag → preset rule → result. Create the preset rules, resolve in the review, re-check counts. 
  Done when: no open flag is left without a decision or a rule, and the table is in `.wiki/quality`.
- [ ] **9. Sidebar tabs check.** Walk Review, Benchmark, Entities, Settings, Ops, Audit and the viewer against the real data; fix what is missing or wrong. 
  Done when: each tab shows real data and every control works, with a screenshot per tab.

- [ ] **10. Answer engine on good data.** Benchmark run 2, model comparison study results, then tune.
  Done when: pass rate and failure classes are reported against the run 1 baseline.

## Still waiting on the user
Resume the agents (the precondition above); gateway per-model prices; alert webhook rotation; Cloudflare domain question; Open WebUI fork question; channel units for the halted telemetry runs (task 8).
