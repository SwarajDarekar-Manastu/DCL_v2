# Plan: metadata in search, cards, and a catalog before the planner

Agreed with the user 2026-10-26. It continues task 10 of `PLAN_data_first.md`.
Rule: each step ends with its check, and the next step does not start until that check passes. Line numbers are as of commit `b1e6aff` plus the uncommitted working tree on 2026-10-26.

## Where we start (measured 2026-10-26)

- **Silver run `9b468dcd`:** 35 of 81 correct (43%). By route: D 9/10, B 7/9, F 4/6, A1 6/12, A2 5/12, E 1/7, C 1/12, behaviour 2/13. Median 25 s, p95 69 s.
- **Retrieval replay** (57 silver cases with gold anchors): recall@8 0.789, recall@30 0.912.
- **Labels on documents, excluding failed:**

| Route | Files | Plan | Run | Hardware | Date |
|---|---|---|---|---|---|
| A1 | 39 | 9 | 0 | 0 | 0 |
| A2 | 23 | 18 | 0 | 5 | 0 |
| C | 40 | 19 | 18 | 21 | 23 |
| D | 81 | 66 | 0 | 15 | 12 |
| F | 4 | 4 | 0 | 0 | 0 |

- **Header on pieces today** (`chunker.py:466` `contextual_header`): `Doc: title (kind, origin, plan, date)`, `Section: breadcrumb`, `Entities: …`. There is no run, hardware, piece type or summary line.
- **Keyword search** (`retrieval.py:183` `lexical_leg`) matches `content`, `breadcrumb`, `content_en` and `content_codes`. It does not match the title, the labels or the summary.
- **Document level.** `documents.search_text` (title, section summaries, entity names) exists on 115 of 196 documents and is in `bm25_documents`, but nothing searches it. No document-level vector exists.
- **Summaries.** `enrichment.doc_summary` exists only for A1, A2 and F. Routes B, C, D and E have none.
- **Run summary** (`series.py:678` `_summary`): file, start time, Hz, duration, rows, and channels by stored name and SI unit with peak or max. Missing: run ID, hardware, the channel name as recorded, the unit as recorded, and whether review is pending. Halted runs have no run summary node.
- **Catalog.** `catalog_lookup` (`tools/documents.py:164-242`) is a plain SQL filter. It runs only as one tool among others, after planning, and cannot filter by run or hardware. It doesn't search the question at all, so it can't tell what the user means. The user's decision (2026-10-26): delete it and write a metadata index search that runs first (step 5).
- **Photo summaries (Route D).** The vision model already writes a 2–4 sentence description of each photo (`inspect_hardware_photo.v1`, field `description`). It becomes the start of the photo piece (`d_photos.py:165` `render_photo`), but never reaches the document's metadata: `doc_summary` is empty for every D file. Plots and schematics have no prose description, only axes, series with a one-line trend note each, or a component list.

## Step 0: tidy what is already coded (no new behaviour)

| What | Where | Change |
|---|---|---|
| Revert the table-row and video-event grouping (not agreed; lowered recall@30) | `backend/indexing/retrieval.py:66` | `COLLAPSING_TYPES` back to `{CHILD, QUESTION_PROXY}`; drop the comment above it |
| Keep: planner type names fixed, guesses as boosts | `analysis.py:27,77-115`, `prompts/engine/query_analysis.v2.md`, `playbooks.py:59-73`, `retrieval.py:101,397` | none |
| Keep: "Source: title · page · breadcrumb" on evidence | `synthesis.py` `_location` | none |
| Keep for now; replaced in step 2 | `retrieval.py:236` `_summaries`, `:247` `_rerank_text` | none |
| Commit the deployed fixes already live: console sign-in, MinIO public links, Open WebUI titles | the files listed in DECISIONS 2026-10-26 | one commit, with the user's OK |

**Done when:** the engine unit tests pass and the retrieval replay is at least 0.789 for recall@8 and 0.912 for recall@30.

## Step 1: labels (plan, run, hardware, date) filled for every route

All routes read their labels from one place, `backend/dispatcher/folder_context.py`, so the fix goes there. The table below lists real paths that come out empty today.

| Real path piece | Today | After |
|---|---|---|
| `Test 01_Data_Analysis.xlsx`, `Test 01_Pressure_and_MFR_vs_Time.png` | no run | T01 |
| `Injector 14 - Test01.png` | no run | T01 (hardware INJ14 already found) |
| `Test1_preheat.tex` | no run | T01 |
| `29122025 - Injector 10 Cold flow test`, `13012026 - Flow Test …` | no date | 2025-12-29, 2026-01-13 |
| `30052025 - Test Videos`, `WIN_20250530_14_01_51_Pro.mp4` | no date | 2025-05-30 |
| `2026.04.20 - Clamp Heater 1.docx`, `WhatsApp Video 2025-12-04 at …` | no date | 2026-04-20, 2025-12-04 |
| `Analog - 04-12-2025 13-25-17.6.csv` | date from file content only | 2025-12-04 as a fallback |

| Where | Change |
|---|---|
| `folder_context.py:16` `RUN_PATTERNS` | Add `(?i)(?<![a-z])Test[ _]?(\d{1,2})(?!\d)`. "Test Plan 12", "Test Campaign 2", "Test_setup" and "Table1" must still give no run (existing test `test_words_that_look_like_ids_are_not_ids`). |
| `folder_context.py` new `DATE_PATTERNS` and `_infer_date` | `YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY_MM_DD`, `DD-MM-YYYY`, and 8 digits standing alone (`YYYYMMDD` when the first four digits are a year from 2000 to 2099 and the date is valid, else `DDMMYYYY` when valid). A longer digit run (a patent number such as `DE102019119598`) gives no date. Library roots (`folder_kind == "library"`) get no path date. |
| `folder_context.py:41` `FolderContext` | Add `doc_date: date \| None` and its entry in `inferences`, with the source (`folder[i]` or `filename`). |
| `backend/dispatcher/runner.py:189` after `processed = build(ctx)`, and `:230` in `resume_staged` | New `with_folder_labels(fields, folder)` fills only the empty `test_plan_id`, `test_run_id`, `hardware_item` and `doc_date` (`date_source = "path"`). A value the route read from the file itself always wins. |

No database change; the columns already exist.

**Tests** (`backend/tests/unit/dispatcher/test_folder_context.py`): one case per row of the first table above, with the exact expected label, plus the "no label" cases: patent number, `Test Plan 12`, `Table1.csv`, library standard.

**Done when:** the tests pass. The coverage table is re-measured after step 8.

## Step 2: the same header on every piece, searchable by keyword

New header, built in one function for every route. Real example, a TP12 photo:

```
Doc: Inj_VF (hardware_photo, internal, 2025-09-16)
Test: plan TP12 · run — · hardware —
Type: photo
Path: APU › Test Campaign 1 › Test Plan 12 › APU - Firing › Figures › De-Integration
About: <first sentence of the document summary, only when one exists>
Entities: …
---
<the piece's own text or reading>
```

| Where | Change |
|---|---|
| `backend/indexing/chunker.py:466` `contextual_header` | Lines `Doc` (title, kind, origin or publisher, date), `Test` (only the labels present), `Type` (piece type plus locator: `page 11`, `lines 40–62`, `00:14–00:19`, `Sheet1!B2:F9`), `Path` (the breadcrumb, renamed from `Section`), `About`, `Entities`. When over the cap, drop in this order: entities, then About, then the start of the path. |
| `chunker.py:48` `header_max_tokens` | 80 → 120. The new lines need about 40 more tokens; the 8,000-token cap on `embed_text` is unchanged. |
| `chunker.py:526` `build_embed_texts` | New parameter `about: str \| None`. Also add the identifiers of the header (title, labels) to `node.content_codes`, using the same `extract_identifiers` (`indexing/identifiers.py`), so "INJ-14", "TP12" and "T04" match a photo whose own text doesn't contain them. |
| `backend/indexing/index_document.py:332` and `:365` | Compute `_aggregate(...)` before `build_embed_texts`, so the first sentence of `doc_summary` can be passed as `about`. |
| New migration `backend/postgres/migrations/versions/0020_header_in_bm25.py` | Drop and recreate `bm25_document_nodes` (definition in `0004_bm25_indexes.py:22`) with one more field: `(embed_text::pdb.simple('stemmer=english', 'alias=embed_text_en'))`. It is rebuilt over the existing rows (about 6,500 today, seconds). |
| `backend/indexing/retrieval.py:196` `lexical_leg` | Add `"embed_text ||| :q"` to the matched fields. |
| `retrieval.py:236,247` | Delete `_summaries`; `_rerank_text` becomes `(row.embed_text or row.content)[:2400]`, since the header now holds the About line itself. |

Route B stays local: its header is built in code from the path and labels, with no model call.

**A summary for every file, including the VLM summary for photos (user, 2026-10-26).** Today the "About" line and the document summary exist only where Gemini enrichment ran (A1, A2, F, G). The route's own summary fills the gap; it comes from readings we already have, with no new model call:

| Route | Summary written by the route |
|---|---|
| D photo | the VLM `description` (2–4 sentences) |
| D plot | written in code from the VLM plot reading: "Line plot of Tank Pressure, Injector Pressure (bar) and Mass Flow rate (g/s) over time 0–40 s. Tank Pressure: constant at ~10.2 bar, dips to ~9.8 bar during flow, …" (axes plus the VLM's one-line note per series). `digitize_plot` stays unchanged, because A1 and A2 figures use it too and a new prompt would re-charge every figure. |
| D schematic | written in code from the VLM schematic reading: "Schematic with 24 components: tank, regulators, SV-3, SV-4, PT-01, …" |
| C run | the first sentence of the run summary (step 4) |
| E diagram | the first sentence of the diagram summary |
| B code | the module docstring, or "Python module with N functions: …" |

| Where | Change |
|---|---|
| `backend/dispatcher/contract.py:649` `DocumentFields` | New `summary: str \| None`: the file's own summary as the route read it. |
| `backend/routes/d_photos.py:256` `process_photo` (+ `read_photo` at `:180` for the plot and schematic text) | Set `summary` from the readings above. |
| `series.py` (C), `e_diagrams/route.py:337` (E), `b_code/route.py:458` (B) | Set `summary` as in the table. |
| `index_document.py:174` `_aggregate` | `doc_summary` = the enrichment summaries when present, else `fields.summary`. Stored in `documents.enrichment.doc_summary`, so the About line and the file card (step 3) read the same text. |

Halted files keep their summary too: the catalog index of step 5 writes it for them.

**Tests:**
- `backend/tests/unit/indexing/test_chunker.py`: the exact header text for a table on page 11 with plan, run and hardware; for a photo with no summary (no About line); and the drop order at the cap.
- `test_index_document.py`: `about` comes from the summary.
- A test-database test: the lexical leg finds an INJ14 Test 03 photo for the query "INJ-14 test 3", where the photo's own text has neither.

**Done when:** the tests pass and migration 0020 upgrades and downgrades on the test database.

## Step 3: one card per file, kept on the file's own row

The card is the file's metadata in one text, built in code with no model call. It lives on the file's own `documents` row, with a vector, so every file has exactly one card, halted files included. The catalog search of step 5 searches these cards. (An earlier draft made the card a separate piece in `document_nodes`. That would be a second copy, and halted files have no pieces, so it is dropped.)

```
<title>
Kind: test_report · internal · plan TP23 · run — · hardware — · date 2026-04
Path: APU › Test Campaign 2 › Test Plan 23
Summary: <doc_summary: enrichment, or the route's own summary from step 2 (photo VLM description, plot or schematic reading, run summary, diagram, module)>
Entities: <entities_top>
Contains: <section, table, figure and event titles from the pieces' breadcrumbs, up to the size cap>
Codes: TP23 CS-01 CS-05 MS289C …
```

| Where | Change |
|---|---|
| New `backend/indexing/card.py` | `card_text(fields, folder_path, summary, entities, contents)`: the one function that writes the card. The `Codes` line holds every identifier of the title, labels, path and contents, normalized by `extract_identifiers`. `write_card(document, text, embed)` stores it. |
| `backend/indexing/commit.py:457` | `documents.search_text = card_text(...)` and `documents.card_embedding = embed(card)` for every indexed file. Today `search_text` holds title, summary and entity names. |
| `backend/dispatcher/runner.py:189-205` (gate halts the file) and `backend/routes/c_telemetry/pipeline.py:218-236` (Route C halts) | Halted files get their card too, from the staged result: title, labels, path, route summary. If the models role is down, the card is written without a vector and step 8 fills it. |
| `index_document.py:217` and `commit.py:519` | New parameter `folder_path` (`documents.folder_context.path_cached`) for the Path line. A piece's breadcrumb inside a report is the section path, not the folder. |
| Migration 0020 | `documents.card_embedding halfvec(768)` with an HNSW index. Recreate `bm25_documents` (`0004_bm25_indexes.py:44`) with `search_text` (English stemmer), `title`, `search_text` again with a whitespace tokenizer (alias `search_codes`), `test_plan_id`, `test_run_id`, `hardware_item`, `doc_kind`, `status` and `route` as exact fields, and `doc_date`. |

Route G keeps its card as its single piece (`g_archives/card.py`); its file card is built like any other.

**Tests:**
- `card_text` exact output for a report, a photo, a halted run;
- the commit writes `search_text` and `card_embedding`;
- a halted file gets a card;
- a test-database test: "TP23 analysis report" finds that file's card first.

## Step 4: the run card (Route C) completed

The labels and path come from the step 2 header. The run summary text adds what an engineer reads:

```
Run Test_04_04Bar_ii_0 (Test_04_04Bar_ii_0.dat), recorded 2026-01-13 11:02, 1000 Hz, 12.4 s, 12,400 rows;
channels: P1 feed pressure (recorded "AIN0" in V, scaled to bar g by LJStreamM.cfg): peak 4.12 bar g; …;
status: not yet classified.
```

| Where | Change |
|---|---|
| `backend/routes/c_telemetry/series.py:678` `_summary` | Each channel shows its name as recorded (`plan.raw_name`), its unit as recorded (`plan.raw_unit`), and the stored name and unit. Max or peak is shown in the recorded unit too, converted with `backend/common/units.py` (`registry()`, `to_canonical`). The run status stays. |
| Halted runs | No node; they are never indexed (`index_document.py` `HaltedDocument`). The catalog in step 5 reports them, from `documents` (`status = 'HALTED'`) with their case keys. |

Links: nothing new. The breadcrumb path and the shared labels (plan, run, hardware) already tie a run to its config, report, photos and video, as decided on 2026-10-26.

**Test:** `backend/tests/unit/routes/c_telemetry/test_run.py`: the exact summary text of a clean run with a channel recorded in °C and stored in K.

## Step 5: understand and reframe the question first (the catalog step; the old catalog is deleted)

The user's intent (2026-10-26): the first step takes the raw question and finds what it refers to in the metadata of every file. It then rewrites the question so nothing is left open: which test, which file, which part. When it is clear, the reframed question drives everything after it: intent, tool calls, passage search, the answer. When it is not clear, the engine asks the user before doing anything else.

It can go wrong in four ways, and each one has to end in an ask-back:
- several files share a name, e.g. `Inj_CC.JPG` sits in TP12 Integration, TP12 De-Integration, TP07 and TP09;
- several files are similar in style or content (the same report template per test plan);
- the same object appears in several tests (the injector, the catalyst bed);
- the user leaves the reference incomplete ("test 4", "the report", "the video", "Rev C").

Each of these would otherwise send the planner to the wrong test, the wrong tool and the wrong answer.

The flow:

```
raw question + chat state
  → 5b catalog search: files and pieces whose metadata match (no model)
  → 5c reframe and decide: one model call (the analysis call we already make) + checks in code
        clear     → reframed question + resolved files → tools, search, answer
        unclear   → ask the user, with the real options
        halted    → say the data exists but is held, and name the case
  → 5d everything downstream uses the reframed question and the resolved files
```

### 5a. Delete the old catalog

| Where | What goes |
|---|---|
| `backend/llm_engine/engine/tools/documents.py:27-33, 47-55, 164-242` | `CATALOG_NAME`, `CATALOG_DESCRIPTION`, `CATALOG_LIMIT`, `CatalogArgs`, `catalog_lookup` |
| `backend/llm_engine/engine/workflow.py:42, 410-411` | the import and the tool dispatch |
| `backend/llm_engine/engine/playbooks.py:19, 126-131, 218-226` | the import; the catalog call of the telemetry and navigational playbooks |
| `backend/llm_engine/engine/analysis.py:61` | `"catalog_lookup"` in `ToolName` (and in the prompt's sub-question tools) |
| Tests | `tests/integration/llm_engine/engine/test_tools_db.py:20-22, 299-301`; `tests/unit/llm_engine/engine/test_playbooks.py:18`; `tests/unit/llm_engine/engine/test_workflow.py:468, 495, 590` (rewritten for the new step). Benchmark tests use the name only as sample data (`test_metrics.py`, `test_runner_db.py`) and stay. No silver or gold case expects `catalog_lookup`. |

### 5b. Catalog search: new `backend/llm_engine/engine/catalog.py`

`search_catalog(session, question, query_vector, state) -> CatalogResult`. The question is embedded once; the passage search later reuses the vector.

**File level** (the cards of step 3, every status, halted included):
1. keyword (BM25 over `search_text`, `title` and the codes field) with the question's words and identifiers;
2. meaning: the question vector against `card_embedding`.

**Piece level** (depth):

3. the existing hybrid passage search (`retrieval.py` dense and lexical legs over `document_nodes`). Its keyword side now includes every piece's header (step 2: path, type, labels, About). It runs without the reranker, takes the top 50 pieces, and scores each file by its best piece. A file whose card never says "pellets" is still found when one of its video events does.

**Labels** (only when the question has them):

4. exact match on plan, run, hardware or date read from the question with the step 1 patterns. This is an extra ranking, never a requirement.

The four rankings are fused by RRF into the top 15 files.

**Group into subjects.** A subject is one thing the user could mean: one test (its plan, run and hardware) or, for files without labels, one folder (from the path). Each subject lists its files with title, kind, status, date, open review cases, the best summary line and the best piece's breadcrumb.

**Conflict signals**, computed in code for 5c:
- same or near-same titles across different subjects (`Inj_CC` × 4);
- two or more subjects close at the top (the gap is tuned on the silver ask-back cases, not guessed);
- a reference in the question that the subjects don't settle: a test number without plan or hardware, "the report/video/photo", "Rev C", a date shared by several tests.

### 5c. Reframe and decide: one model call plus checks in code

This is the analysis call the engine already makes (`analysis.py:222`), given the catalog result. No extra model call.

| Where | Change |
|---|---|
| New `prompts/engine/query_analysis.v3.md` | Input: the raw question, the chat summary and state, and `$catalog` (the subjects with their files, summary lines, statuses and the conflict signals). Output, added to `QueryAnalysis` (`analysis.py:132`): `reframed_question` (the full question with the test, file and part named, using only facts from the catalog and the chat), `resolution` (`clear`, `ambiguous` or `not_found`) and `subject_ids` (the subjects it means). The intents, entities and filters stay as they are, but are read from the reframed question. |
| `analysis.py:184` `resolve` | Checks in code, so the model can't invent a reference: every subject ID must be one the catalog returned; every ID in `reframed_question` (by `extract_identifiers`) must appear in the question, the chat state or the chosen subjects' cards. If a check fails, the reframed question is dropped and the engine asks back. |
| `catalog.decide(analysis, catalog, state)` | **Ask back** when the model says `ambiguous`, or when it says `clear` but a conflict signal stands and the question doesn't settle it. Code builds the options from the subjects, not the model. Example: "Which Inj CC photo? TP12 integration (2025-09-04) · TP12 de-integration (2025-09-16) · TP07 de-integration · TP09 de-integration". **Halted** when the question asks for a measured value and the subject's only data for it is halted. **Not found**: search still runs on the raw question, with the note. A subject chosen earlier in the chat wins, and nothing is asked. |
| `workflow.py:173` `analyze_question` | Order: embed → `search_catalog` → `analyze(..., catalog=...)` → `decide` → stop (ask back, halted) or go on. The trace stores the raw question, the reframed question, the subjects and the decision, so the Console shows what the engine understood. |

**Chat memory (missing today).** The workflow reads a `state` (`workflow.py:197`) that nothing sends: neither the Open WebUI pipe nor `POST /engine/answer` passes one. So the engine has no memory of earlier turns beyond the history text. Fix on the server, so Open WebUI and benchmark multi-turn cases behave the same: `analyze_question` loads the latest `answer_traces` row of the same `chat_id` (`postgres/models/traces.py:16-20`), including its subjects, its decision, and its open ask-back with the options. When the new message picks one of those options ("TP12", "the first one", "de-integration"), the original question is reframed with that subject and the engine goes on. A resolved subject stays the chat's subject for follow-ups ("and the temperature?") until a new question names another.

Examples:

| Raw question | Catalog finds | Outcome |
|---|---|---|
| "peak pressure in test 4" | TP12 Test 04 (workbook, plots); INJ14 Test 04 (pressure run, halted) | ask back: "Which Test 04? TP12 or Injector 14 (held for unit review, case …)?" |
| (user picks TP12) | — | reframed: "Peak pressure in TP12 Test 04 (Test Campaign 1, APU firing): analysis workbook and pressure plot" |
| "show the inj cc photo" | four `Inj_CC` photos in four folders | ask back with the four folders and dates |
| "what happened to the clamp heater in TP24" | one report, `2026.05.14 - Clamp Heater 1 - TC2 TP24.docx` | reframed: "Results of the 450 W Clamp Heater 1 test, TP24 (report of 2026-05-14)" → go on |
| "and the temperature?" (after TP12 Test 04) | the chat's last trace holds TP12 Test 04 | reframed: "Peak temperature in TP12 Test 04" → go on |
| "Injector 14 test 3 pressure" | INJ14 Test 03, halted only | "This run exists but is waiting for unit review (case …)" |

### 5d. Everything downstream uses the reframed question and the resolved files

The retrieval method, with the metadata filtering agreed earlier:

| Where | Change |
|---|---|
| `playbooks.py:121` `build_plan` | Every tool argument is built from `reframed_question` (search queries, sub-questions, visual queries), never from the raw text. |
| `playbooks.py:59` `_filters` | **Filter:** the resolved subject's files, all of them, not only the top 15. That means every file with the subject's labels, or every file in its folder. They go in `SearchFilters.doc_ids`, which already exists (`retrieval.py:89`). **Boost:** the model's guessed kinds and passage types (`prefer_doc_kinds`, `prefer_node_types`; nothing hidden). |
| `tools/search.py:53` `widening_steps` | New first widening step, "dropped the resolved files": when a search inside the subject finds nothing, it widens to everything and says so. The existing order follows (kinds, plan, parent scope). |
| `retrieval.py` | Unchanged apart from steps 0 and 2: dense + BM25 (now with every piece's header) → RRF → reranker reading header + text. |
| `tools/telemetry.py:109` `args_for`, `:154`, `:222` | Runs come from the resolved subject's run labels (`telemetry_runs`), so runs with hardware and no plan work. `telemetry_args` reads the reframed question. |
| `playbooks.py` document summary and navigational intents | A document summary reads the resolved file (`get_document`). "What do we have on X" answers from the catalog's files, as a cited list with their summaries. |
| `synthesis.py` | The writer and checker get the reframed question (and the raw one), plus the resolved files' cards as file-level context. |

**Speed:** catalog search about 100–300 ms (two card queries, one passage query without the reranker, one label match). The reframing rides on the existing analysis call, so a clear question takes no longer than today, and an ask-back is much faster, because no tools run.

**Tests** (`backend/tests/unit/llm_engine/engine/test_catalog.py`, `test_analysis.py`, plus a test-database file):
- question labels from "Test 04", "TP7", "Injector 14", "run 4", "13 Jan 2026";
- grouping by labels, and by folder for unlabelled files;
- conflict signals: four same-name `Inj_CC` photos; close subjects; "test 4" with no plan;
- `decide` on fixed inputs, one per row of the examples table;
- the checks: a reframed question naming an ID the catalog never returned is rejected → ask back;
- downstream: the search arguments use the reframed question and the subject's `doc_ids`; an empty subject search widens once and says so;
- a workflow test: an ask-back stops before any tool runs; the next turn in the same chat ("TP12") is reframed from the stored options and goes on.

## Step 6: the right tools, and a sufficiency check

| Where | Change |
|---|---|
| `backend/llm_engine/engine/tools/telemetry.py:48` `SemanticChannel` and `:246` `channels_for` | Besides the five roles, accept any channel the run card lists (stored or recorded name). Example: T8 thrust valve outlet temperature. `prompts/engine/telemetry_args.v1.md` → v2 receives the channel names of the matched runs. |
| `telemetry.py:154` `_runs`, `:222` `_halted` | Select runs by the subject's run labels (step 5), or by hardware plus run, not only by plan. Injector 14 runs have no plan, so today they can never be asked about. |
| `playbooks.py:86` `_visuals`, `tools/visuals.py:94,146` | "Photos" asks for `hardware_photo` only; "plots" for plot figures. The kinds come from the analysis node types, not "all kinds". |
| `workflow.py:442-501` `answer` | Sufficiency: when no claim was verified as `entailed` (`synthesis.Answer.verdicts`), mode `insufficient_evidence` with what was searched, instead of the fixed `"answered"` at `:492`. A sub-question whose searches found nothing gets a "not covered" caveat. No extra model call. |

**Tests:** a telemetry args test for a recorded channel name and for INJ14 + T03; a visuals kinds test; a workflow test where every verdict is `not_supported` → `insufficient_evidence`.

## Step 7: question proxies for every document kind

| Where | Change |
|---|---|
| `index_document.py:63` `QUESTION_PROXY_KINDS`, `:315` | Make a proxy for every enriched section, whatever the document kind. The questions already come back in the same enrichment reply, so there is no new model call, only more local embeddings. |

**Test:** `test_index_document.py`: a `risk_assessment` section with questions gets a proxy node.

## Step 8: re-run what is already processed

The route outputs of finished files are not stored; only halted files keep theirs. So updating old data means running each file through its route again. The Gemini result cache (`gemini_client.py`, task 7) and the vision cache return earlier replies when the request is unchanged. The new header does not change enrichment requests: their context is title, kind, origin and plan (`index_document.py` `document_context`). Pieces are re-embedded locally.

| Where | Change |
|---|---|
| New `backend/dispatcher/reindex.py`, run as `python -m backend.dispatcher.reindex --route C --limit 5 [--dry-run]` | (1) Rebuild `documents.folder_context` with `build_folder_context` from the stored root, folder names, file name, siblings and origin. (2) Halted files: update the empty labels only; they stay halted. (3) Active files: set `PROCESSING` and queue the route task through the dispatcher's own path (`tasks_process.enqueue_release`). |

Order: one route at a time, under the memory rules.
1. C, B, E (local, fast).
2. A2.
3. F.
4. D, including the 64 photos task 8 still had pending.
5. A1 (Docling, slowest), including the 18 from task 8.

Each route starts with 5 files. Read `llm_calls` (`cache_hit` against paid calls) and report the cost before running the rest.

**Done when:**
- The coverage table above is re-measured, and no row has empty run, hardware or date where the path holds them.
- Every file, halted ones included, has a card text and a card vector.
- Every piece's `embed_text` has the new header.
- Every active run has the new run summary.

## Step 9: test

1. **First measure point, after steps 1–4, 7 and 8.** Run the retrieval replay (`retr/measure.py` in the scratchpad) on the same 57 cases. Compare against 0.789 / 0.912, listing every case that changed. Expected newly found: d-nav-burned-mesh-photos, f-tp07-video-pellets, the TP23 table.
2. **Second measure point, after steps 5 and 6.**
   - Run the full silver set in the Console Benchmark and compare with run `9b468dcd`: pass rate per route, failure classes, and median and p95 latency.
   - Run the gold set, task 10, against the run 1 baseline.
3. **Live in Open WebUI with the test account:**
   - "Test 04 peak pressure?" should ask back.
   - "Injector 14 Test 03 pressure" should give the halted notice with the case.
   - "Show the burned mesh photos from TP12."
   - "When do pellets appear in the TP07 video?"
   - "What is in Table 6 of the TP23 report?"
4. **Then commit and deploy.** One commit per step after its tests pass. Workers are deployed before step 8 runs.

## Not doing, and why

| Left out | Reason |
|---|---|
| Links between files as their own field | The user's decision 2026-10-26: the breadcrumb path and the shared labels are enough. |
| A campaign label | Already in the Path line ("Test Campaign 2"). |
| A separate card shape per route | One file card (step 3) covers every route; Route G keeps its card as its single piece. |
| The file card as a separate piece in `document_nodes` | It would be a second copy of the card on the `documents` row, and halted files have no pieces. The catalog search (step 5) finds files by their card and gives the card to the writer. |
| Another vector store or search engine | The existing hybrid search (BM25 + pgvector + reranker) is fine. The failures came from filters and from metadata not reaching search. |
| Searching `documents.search_text` as an extra leg of passage search | `search_text` becomes the file card, searched by the catalog (step 5); passage search gets the catalog's files as `prefer_doc_ids`. |
| A new prose prompt for plots and schematics | The summary is written from what the VLM already read (axes, series notes, components). A new `digitize_plot` prompt would re-charge every A1 and A2 figure. |
| New hardware patterns beyond injectors | Nothing else in the data names hardware in a pattern we can read safely. To revisit when the real folders arrive. |

## Manual changes that need the user's sign-off

- **04 §4.1:** the Document row: embedded (the file card's `card_embedding` on `documents`) instead of "no".
- **04 §4.2:** the new header lines and the 120-token cap.
- **04 §5.4:** question proxies for every kind instead of five.
- **04 §6:** `embed_text` added to keyword search.
- **04 §3.4:** `search_text` becomes the file's card (title, kind, labels, path, summary, entities, contents, codes), written for halted files too; `doc_summary` falls back to the route's own summary (photo VLM description etc.).
- **07 §3 and §4 U2:** the `catalog_lookup` tool is replaced by the metadata index search that runs before the analysis model.
- **07 §10:** ask-back, halted and nothing-labelled rules, decided in code from the catalog's subjects.
- **07 §4:** the sufficiency step decides the mode.

## Risks

- **Gold anchors.** Re-running A1 through Docling can change a passage's text, so a gold anchor falls back to its page. The replay reports these separately, so they aren't counted as misses.
- **Path dates.** One wrong guess (DDMMYYYY against YYYYMMDD) gives a wrong date. Dates read from the file still win, and every path date keeps `date_source = "path"`.
- **Early stops.** The catalog stops a question early only in the halted case. A false "nothing labelled" never stops a question; search still runs.
