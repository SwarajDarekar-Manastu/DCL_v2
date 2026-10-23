# Plan: good data first, then the answer engine

User order, 2026-10-23 (reframed by the Lead). Rule for every stage: do not start the next one until the "done when" line is true.

## Tasks

- [ ] **0. Steady ground.** Network steady; agents resumed on the `dcl-role` agent (Sonnet 5.5, xhigh); gateway circuit reset; every Gemini result saved as it arrives so a failed save never repays it (S2 + S1).
  Done when: the 74 stuck and 29 failed documents re-run with no repeated model calls (cache hits shown in the ledger).
- [ ] **1. Finish steps 4 and 5 (enrichment, embed and store) for A2, B, E, G.** Audit the shared tail first: does each route's output enrich and embed correctly? Add a route-specific enrichment prompt only where the generic one fails (LaTeX sections, code symbols, diagram components, archive and CAD references). Owner S6 with S2.
  Done when: one real file per route reaches ACTIVE with embedded nodes, in a unit test.
- [ ] **2. Scratch run, all eight routes.** Throwaway Postgres and MinIO (`backend/devops/ci/test_services.sh up`, separate ports, no link to the real stack). Ingest 1 to 2 real files per route, A1 to G including the live ones. Owner S1 + S5.
  Done when: each route has run route → flags → commit → embed against the scratch store and the results are listed per route.
- [ ] **3. Review test on the scratch store, per flag type.** For every flag that fires: the help icon appears and reads right, the resolution works, undo works. Owner S3 + S5.
  Done when: each of the nine flag types is either exercised or marked "never fires on our data".
- [ ] **4. Preset rules.** From each resolved flag, create a rule the reviewer can make once and apply to every matching flag ("replace X with Y": unit by column name, column mapping, source choice, supersession). Use the dry run to show what it would change, then apply and undo. Owner S1 + S3.
  Done when: for each flag type that fires, one preset rule resolves a second, different file without a click.
- [ ] **5. Cheapest model that works for the suggestions.** Where a model suggests a unit, a column or a source, test gemini-3.1-flash-lite on the gold data; if it misses, step up to 3.8-flash, and record the choice per task. Rules themselves are deterministic; the model only proposes. Owner S2 + S5.
  Done when: each suggestion task has a measured accuracy and a chosen model.
- [ ] **6. Delete the scratch stores.** Remove the throwaway Postgres and MinIO containers and volumes after tasks 2 to 5 pass. Owner S4.
  Done when: no scratch container or volume remains; the real stack is untouched.
- [ ] **7. Real ingest of the test folders.** Run all E1 to E13 on the real stack. Map every flag that fires into a table: flag → preset rule → result. Create the preset rules, resolve in the review, re-check counts. Owner S1 + S3 + user (channel units).
  Done when: no open flag is left without a decision or a rule, and the table is in `.wiki/quality`.
- [ ] **8. Sidebar tabs check.** Walk Review, Benchmark, Entities, Settings, Ops, Audit and the viewer against the real data; fix what is missing or wrong. Owner S3.
  Done when: each tab shows real data and every control works, with a screenshot per tab.
- [ ] **9. Answer engine on good data.** Benchmark run 2, model comparison study results, then tune. Owner S2 + S5.
  Done when: pass rate and failure classes are reported against the run 1 baseline.

## Still waiting on the user
Resume the agents; gateway per-model prices; alert webhook rotation; Cloudflare domain question; Open WebUI fork question; channel units for the halted telemetry runs (task 7).
