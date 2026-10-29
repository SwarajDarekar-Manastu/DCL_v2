# Plan: understand the question, route it, search each kind of data its own way

Agreed with the user on 2026-10-28. Rewritten on 2026-10-28 as one complete reference: the thesis, the problem, the solution, the build steps with their files and changes, and everything measured so far.
- **Replaces:** `PLAN_source_files.md` (the picker was tried and removed).
- **Rule:** each build step ends with its check. A step is kept only if the check passes. The next step starts after that.

---

## 1. Thesis

The Answer Engine fails mostly **before** the answer is written, and in two ways:
1. **An early step decides too much.** It locks the search or asks the user "which one?" when it should only guide.
2. **One general search serves every kind of data,** although each kind (measured runs, spreadsheets, code and configs, reports, photos, drawings, library books, archives) needs a different way of finding the answer.

Gemini 3.8 Flash writes correct answers when it gets the right files with clear context. So the work goes into two things:
- **Understanding the question and routing it** to the right kind of data and method.
- **Giving the writer clean, self-describing evidence.**

It does not go into extra checkers or hand-written rules for particular files.

The design is generic. Nothing is written for one file or one topic: no synonym lists and no per-file rules (user, 2026-10-28).

## 2. The problem

### 2.1 How it was found

The silver benchmark (82 questions over the team's own files) showed a group of failures where **the right file never reached the answer writer**. Most of them involve source files: code, `requirements.txt`, LabJack `.cfg` files, and LaTeX and JSON test-plan sources. In 62 of 63 cases the first file search had the right file in its top 15, so the files are findable. They were lost in later steps.

### 2.2 The system before

```
question
 → catalog (engine/catalog.py): finds candidate files, groups them by test plan / injector / folder,
   then LOCKS the search to one group, or ASKS "which one do you mean?"
 → Gemini analysis (query_analysis.v3): rewrites the question, picks intents
 → playbooks (playbooks.py): mostly one general hybrid search; code, diagrams and standards get hard filters
 → Gemini writes the answer → checks: Gemini claim check + a plain-code number check → answer
```

### 2.3 The pattern behind the failures

| Pattern | Where in the engine | Effect |
|---|---|---|
| The catalog acts as a gate | `catalog.decide`: a hard file filter, and "which one?" when the model says "ambiguous" | Wrong lock: objectives and overview were locked to TP12. Needless asks: three copies of `Test_plan_creator.py` tie and the engine asks instead of answering. |
| Source files are treated like Python functions | Code playbook: hard filter to function and module-header pieces | Plain text lines (`xlwings==0.33.15`, `ScanRate=1000.0`) are excluded, so `requirements.txt` never reaches the writer |
| Source files don't describe themselves | File cards and chunk headers built from thin summaries | "Which xlwings version do we pin?" cannot find `requirements.txt` by meaning. `ScanRate=1000.0` has no unit in the file, so the writer cannot say "Hz". |
| One search for every kind of data | `build_plan` | Reports, LaTeX/JSON sources, spreadsheets, the Library and archives all get the same general search |
| A plain-code number check removes correct answers | `verifier.check_numeric_claim` (now removed) | It read the word after a number as its unit ("Test **02 data**", "7 **shows**") and deleted 37 correct claims in three runs, while catching no wrong number |
| The writer gets noisy evidence | `synthesis.evidence_items` and the tool outputs | The same passages 2–3 times, "found nothing" messages as evidence, a wrong drawing, every source labelled "internal_report", storage paths |

## 3. The solution: five steps for every question

What practitioners do (sourced research, 2026-10-28): rules first and AI second; keep the user's terms; a rewrite names only things that exist; each kind of data gets its own method; filters are preferences unless the user typed the exact ID; answer with a stated assumption and ask only when the meanings differ; measure routing separately.

1. **Code reads the obvious parts of the question:** plan, run, injector, date and identifiers (`question_labels`, already existed).
2. **One AI call understands and reframes.** The existing analysis call returns:
   - the reframed question (only names that exist)
   - the **route or routes**
   - and whether to ask back, which happens only when the meanings lead to different answers.
   The catalog's file list is information, not a decision.
3. **Each route runs its own method:**

| Route | Data | Method |
|---|---|---|
| measured | telemetry runs (C) | database query over the run (T2), with documents as context |
| table | spreadsheets, engineering tables (C) | tables first, then general search |
| source | code, requirements, configs (B, C `.cfg`) | search that prefers source files, with self-describing files |
| document | reports, test plans, LaTeX/JSON sources (A1, A2) | sections first, then the whole file when sections are not enough |
| visual | photos, plots, video (D, F) | photo search (T3) |
| diagram | drawings, schematics (E) | diagram graph (T4) plus diagram search |
| library | standards, datasheets, papers in the Library (A1) | search limited to the Library |
| archive | zip, ANSYS packages, CAD (G) | answer from the file's card, say the file exists, give its link. A deeper question gets "this file type is not read in depth yet, here is the file". |

4. **The likely files are ranked first, not locked in,** unless the user typed the exact plan, run or injector.
5. **The answer starts with the assumption** when one was made ("Assumed: the question is about TP07; other matches: TP12, INJ10.").

## 4. Build order, files and changes

Each piece is built and benchmarked on its own: the silver suite, 82 questions, 2 repeats each, run from the host against the live database and models.

### Step 0: measure where we stand (done)

| File | Change |
|---|---|
| `backend/llm_engine/engine/answer_routes.py` (new) | The 8 routes; `of_document(route, doc_kind, folder_kind)` gives a file's route |
| `backend/benchmark/catalog.py` | `CaseSpec.expected_routes` |
| `backend/benchmark/metrics.py` | `route_hit` (did the answer cite a file of the expected route), `by_route` and `clarifications` in the run summary |
| `backend/benchmark/runner.py` | `document_routes`: the route of every cited or retrieved file |
| tests | `test_answer_routes.py`, `test_metrics.py` |
| labels | 82 silver cases labelled with their route: 72 from their expected files, 10 by hand. For now they live in a JSON file next to the run harness (see section 6). |

### Step 1: the catalog guides instead of gating (done, kept)

| File | Change |
|---|---|
| `backend/llm_engine/engine/catalog.py` `decide` | "Ambiguous" no longer asks. It goes on with the likeliest group (the top two when they tie). Only the two code signals still ask: a run under two plans, and a named file in two folders. `Decision.pinned` is true only when the user typed (or picked) the plan, run or injector. When the user typed a plan and a run, the group matching both wins. |
| `catalog.py` | `_likeliest` and `_assumption` write the "Assumed: …" line, using short folder names |
| `backend/indexing/retrieval.py` | `SearchFilters.prefer_doc_ids`: the chosen files are ranked higher, never the only files searched |
| `backend/llm_engine/engine/playbooks.py` | `_files`: a hard file filter when pinned, a ranking boost otherwise. This also applies to photo search. |
| `backend/llm_engine/engine/tools/visuals.py` | photo search accepts `prefer_doc_ids` |
| `backend/llm_engine/engine/workflow.py` | the answer starts with the assumption line; the old "dropped rewrite → ambiguous" switch is removed |
| tests | `test_catalog.py` (tie, copies, typed plan, run conflict, assumption), `test_playbooks.py` |

### Step 2: search with the user's words plus the rewrite (tried, removed)
The code was removed. The result is in section 5.

### Step 2b: remove the plain-code number check (done, kept: 125/164 against 119)

| File | Change |
|---|---|
| `backend/llm_engine/engine/verifier.py` | deleted |
| `backend/llm_engine/engine/synthesis.py` | claims are rejected only by Gemini's claim check (`verify.v1`, which already checks numbers and units) |
| `workflow.py` | `numeric_mismatches` is gone from the trace |
| tests | `test_verifier.py` deleted; `test_analysis_synthesis.py`, `test_workflow.py` and `test_physics.py` adjusted |
| `docs/sessions/DECISIONS.md` | entry dated 2026-10-28. Manual 07 §7 no longer holds for numbers. |

### Step 3.0: the AI names the route (removed 2026-10-28, rebuilt with route methods as P1 on 2026-10-29)

Removed before its check finished, to keep the engine simple: it added a prompt version and a field and changed no search. The table below is what it was; the code is not in the tree.


| File | Change |
|---|---|
| `backend/llm_engine/prompts/engine/query_analysis.v4.md` (new) | v3 plus `routes`: 1–3 routes, most likely first, with a plain description of what each route holds |
| `backend/llm_engine/engine/analysis.py` | uses v4; `QueryAnalysis.routes` |
| `catalog.py` | every file line the AI reads shows its route, e.g. "Test_plan_creator.py (code, route source)". `CatalogFile.folder_kind` is read from `folder_context`. |
| `metrics.py`, `runner.py` | `routes_chosen` from the trace; `chosen_ok`; `route_chosen` per route |
| tests | `test_catalog.py` (route in file lines), `test_metrics.py` |

The search does not change in this step. It measures whether the AI picks the right route.

### Step 3b: source route (not started)

Nothing of it is in the tree: the half-built search change and the unused `source_description.v1.md` were removed on 2026-10-28.


| What | File | Change |
|---|---|---|
| Self-describing source files | `backend/llm_engine/prompts/enrichment/source_description.v1.md` (exists) | Gemini writes 2–4 sentences per file: what it is and what it belongs to, what it holds (every package with its version, every setting with its unit), where it sits, and how it differs from other versions |
| | test: a script writes them into the live database and can undo them | 8 files: 3 copies of `Test_plan_creator.py`, `requirements.txt`, 4 LabJack `.cfg`. Descriptions were already generated and checked (e.g. "Python dependency list (pinned package versions) for the test-plan creator tool", "ScanRate of 1000.0 Hz"). |
| | if kept: `backend/indexing/index_document.py` `_aggregate` (~line 212) | For Route B and config files, `doc_summary` comes from this prompt. The 8 files are re-indexed. |
| Search that accepts all source pieces | `playbooks.py` code playbook (~line 184) | The hard "function and module-header pieces only" filter becomes a preference for source files (`code`, `tooling_doc`, `config`). It also runs when the AI picks the route `source`. |
| | `answer_routes.py` | `SOURCE_KINDS = {code, tooling_doc, config}` |
| tests | `test_playbooks.py` | Source questions prefer source files and exclude nothing |

**Check:** silver run, 2 repeats. Kept if the source route improves and no other route drops. The original failing cases (xlwings, both LabJack scan rates) are watched by name.

**Decision needed (user):** Route B is never sent to a model (manual 03 §6, `index_document.py:259`). The description is **one** Gemini call per Route B file: 4 files today, nothing else from Route B. The `.cfg` files are Route C, which already uses Gemini.

### Step 3c: document route
- **Descriptions** with the same prompt for the A2 LaTeX and JSON sources (they cover JSON and LaTeX already).
- **Reading:** sections first, then the whole file when the sections are not enough.
- **Targets:** objectives and overview of the first campaign (JSON), and TP7 expected thrust (`.tex`).

### Step 3d: table route
Tables-only search first for spreadsheets and engineering tables, with general search as the fallback.

### Step 3e: library route
Search limited to Library files (`folder_kind = library`). It needs the folder kind on the search pieces, or a list of the Library's document ids.

### Step 3a: archive route (Route G)
- **Answer from the card:** what the file is, what it holds, and where it sits.
- **Link:** the file's OneDrive link (`catalog_evidence` adds `web_url`).
- **In-depth questions:** "not read in depth yet, here is the file".
- **Testing:** no Route G file is indexed yet, so only unit tests for now.

### Step 4: clean evidence for the writer
- **Duplicates:** drop repeated passages.
- **"Found nothing":** keep these messages out of the evidence.
- **Source labels:** label each source by what it is (measured data, spreadsheet, code, photo, drawing, report, library).
- **Clutter:** remove storage paths.

Files: `synthesis.py` (`evidence_items`, `render_evidence`) and `tools/__init__.py` (`provenance_of`).

## 5. What has been measured (silver, 82 cases × 2 repeats)

| Run | Passed | Per repeat | Asks back | Median s | Notes |
|---|---|---|---|---|---|
| Baseline (Step 0) | 117/164 | 59, 58 | 7 | 26.7 | 56 cases passed both repeats |
| Step 1: catalog guides | **119/164** | 58, 61 | **2** | 24.6 | kept; no case that passed both baseline repeats failed both |
| Step 2: user's words + rewrite | 116/164 | 60, 56 | 2 | 33.5 | removed: no gain, +3.3 s per answer |
| Step 2b: number check removed | **125/164** | 62, 63 | 2 | 28.6 | kept; 60 cases passed both repeats; no case that passed both Step 1 repeats failed both; diagram 11→13, measured 8→10, eight cases 1/2→2/2 |
| Step 3c-1: self-describing sections (`PLAN_self_describing.md`) | **129/164** | 65, 64 | 2 | 48.0 | kept; document 29→32, others hold; 63 cases passed both repeats; slower answers came from the gateway |
| P1: the planner names routes, each route searches its own way (`PLAN_route_retrieval.md`) | **133/164** | 68, 65 | 2 | 35.5 | kept; document 32→35, visual 28→30, diagram 13→14, source 18→16 (two correct answers failing checks, same evidence); routes chosen right 156/160 |

**Baseline by route:**

| Route | Cases | Passed | Cited the right kind of file |
|---|---|---|---|
| table | 6 | 12/12 | 10/12 |
| library | 7 | 12/14 | 14/14 |
| visual | 16 | 27/32 | 30/32 |
| source | 12 | 17/24 | 23/24 |
| document | 21 | 28/42 | 40/42 |
| diagram | 7 | 9/14 | 12/14 |
| measured | 11 | 8/22 | 18/22 |

**Step 1 details:**
- Asks on diagram, visual and source questions dropped to 0. Diagram went from 9 to 11 passes, visual from 27 to 28.
- The 2 remaining asks are the "Test 04 exists under two plans" case, which is supposed to ask.
- The assumption line now appears whenever an ambiguous question goes on unpinned.

**The original failing cases are not fixed yet:**

| Case | Baseline | Step 1 | Why it still fails | Fixed by |
|---|---|---|---|---|
| xlwings version (`requirements.txt`) | 0/2 | 0/2 | The file's text is excluded by the code filter | 3b |
| LabJack scan rate × 2 | 0/2 | 0/2 | No unit in the file | 3b (description states Hz) |
| Objectives / overview (JSON) | 0/2 | 0/2, 1/2 | Thin description; ranks below other files | 3c |
| TP7 expected thrust (`.tex`) | 0/2 | 0/2 | Answered from the Setup workbook | 3c |

**Earlier tests that fed this plan:**
- **Picker (iteration 1):** failed its A/B test and was removed.
- **Descriptions alone on 11 files (2026-10-27):**
  - 25/46 against 24/46.
  - It fixed xlwings, both LabJack questions, `latex_cleanup`, the Excel-close question and the bold-header question.
  - It broke 3 code questions through "which one?" asks, which Step 1 has since removed.

**Number check audit (all 492 answers of the three runs):**
- 45 claims were rejected by the code number check.
- Gemini's check had accepted 37 of them, and all 37 were false alarms.
- No wrong number was caught.
- 72 sentences were removed from 56 answers.

**Writer evidence audit** (one real answer per route): see the last row of the table in 2.3. That is Step 4.

**Questions about files or dates the engine cannot handle yet** (seen, not in this plan):
- "Last week's firing" does not work. The AI is never told today's date. Its date fields are unused. Search has no date filter.
- The OneDrive file dates are stored but never used.

## 6. How the checks run, and what is not deployed

- **Host runs.** Runs start from the host with the working tree code: Postgres `127.0.0.1:5435`, models `127.0.0.1:8500`, `DCL_MINIO_ENDPOINT=http://127.0.0.1:9100`. The harness uses the benchmark's own `run_case`.
- **Not deployed:** the containers still run the old image (`dcl-v2-backend:local`). Open WebUI uses none of these changes yet. The image is not rebuilt now because another session has uncommitted work in the same tree, in A1 route files, ops and benchmark tasks, and `index_document.py`.
- **Route labels:** not written to the database as case versions yet. The running containers parse case specs strictly and would reject the new field. They are written after the next agreed rebuild.
- **Do not re-import** `data/benchmark/silver.yaml` or `silver.import.json`. They are stale and would revert the case edits of 2026-10-27.
- **Unit tests:** `pytest backend/tests/unit/llm_engine backend/tests/unit/indexing backend/tests/unit/benchmark`.
- **Formatting:** `ruff format` and `ruff check` on the changed files only.

## 7. Parked

- Hand-written synonyms and per-file rules (user: not wanted). `quantity_terms` in `config/aerospace_synonyms.yaml` stay unwired.
- Dates in questions ("last week"): give the AI today's date and rank by test date or file date. Not planned yet.
- Removing the `LIBRARY_VS_INTERNAL` category and `external_kept` labels (proposed 2026-10-27, not confirmed).
- `.env` `DCL_MINIO_ENDPOINT` points to the MinIO console port (9101). Host runs need `9100`.
- A trained or embedding router: rules plus one AI call are enough for 8 routes.
