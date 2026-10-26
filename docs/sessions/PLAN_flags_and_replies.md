# Plan: flags that should not be flags, and model replies that fail their schema

Date: 2026-10-26. Status: **approved by the user on 26 Oct ("yes to all")**, including every recommendation in section 3.

This plan covers four points from the user's message of 26 Oct: structured replies, unit ambiguity, the video
conflict, and SCHEMA_UNKNOWN. The fifth point, cost on the Ops page, is done (commit 5dcd92a, prices loaded).
Every number below was read from the live database on 26 Oct.

---

## 1. What is wrong today

### 1.1 Model replies that fail their schema

Every Gemini call that needs structured data already sends a Pydantic model as the reply schema
(`response_json_schema`, built in `gemini_adapters.py:368`). ADK's `output_schema` does the same thing, so
switching to ADK would not fix anything. The failures have three other causes:

| Task | Model | Failed replies | Output tokens per failure | Cost | Cause |
|---|---|---|---|---|---|
| `engine.repair` | 3.8 Flash | 15, all today | about 2,034 | $0.14 | The cap is 2,048 tokens, and the model's thinking counts toward it. The reply is cut off, so the JSON is incomplete. |
| `suggest.unit` | 3.1 Flash-Lite | 15, on 24 Oct | 65,520 (the maximum) | $1.48 | No cap was set. Flash-Lite repeated itself until the hard limit. This was the model trial; production now uses 3.8 Flash, but there is still no cap. |
| `vision.digitize_plot`, `enrichment.parent` | 3.8 Flash | 1 each | about 3,000 | $0.03 | The reply broke a field rule that Gemini does not enforce (e.g. a maximum number of items). |

Why it matters:
- **The repair failures hurt answers.** When a repair fails, the claims it was meant to fix are deleted from
  the answer. They are not corrected.
- **The log reports a cut-off reply as "does not match the schema."** That hides the real cause.

### 1.2 Unit ambiguity

**What a unit is used for:**
- **Time series (Route C channels).** Values are converted to standard units (bar, N, K, g/s) in
  `normalized.parquet`. The telemetry tool reads them for maxima, comparisons and sanity checks. A channel
  with no unit cannot be converted, so its flag is HARD and the file stops.
- **Tables (C workbooks, A1, A2).** The unit goes into the table's metadata: `units` in C, `units_by_column`
  in A1, and `column_units` after a review. The answer checker uses it to confirm numbers, and numeric facts
  use it for their converted value. A table column with no unit only gets a SOFT flag: the numbers stay as
  text and the file is still indexed.

**The 250 open unit flags:**

| Flags | Where | What is really there | Verdict |
|---|---|---|---|
| 176 HARD | 22 logger files | Channels named `y0`–`y7` and `AI0`–`AI7`. The name carries no information. | Real. No wording can help. One folder rule (already built) can answer a whole rig at once. |
| 50 SOFT | Test 01–04 `_Data_Analysis` statistics sheets | Each row states its own unit in the Parameter cell: "Pressure Suppy N2 [barg]", "Thrust [N]", "Mass Flow Rate [grams/s]". | False. The reader only looks for units in column headers. |
| 10 SOFT | "Injector 10" | Tank Pressure, Thrust, Mass Flow Rate… with no unit. Another table in the same campaign states the same names with units: "Tank Pressure [gauge] (bar)", "Mass Flow Rate (g/s)", "Thrust (N)", "Test Duration (s)". | Answerable from that sibling table, with good confidence. |
| 7 SOFT | "Setup" sheet | A register of other files (File Number, Part ID, Revision, "Exists? (Y/N)"). | False. This file describes other files and needs no units. |
| 7 SOFT | A2 LaTeX reports | "Preheat (\textdegree C)" | False. The LaTeX degree sign is not read. |
| 1 SOFT | Risk register | "Likelihood (1-5)" is a scale. | False. A scale has no unit. |

**Wrong with no flag at all:** in the Test 0x workbooks, "Pre Heat Temperature [ C ]" is stored as
**coulomb**. `C` is a valid unit symbol, so nothing complained. This is worse than a flag.

### 1.3 SCHEMA_UNKNOWN (9 flags)

All nine come from one TP07 report folder.
- **What the files are.** Each JSON file is one section of the report: `{id, title, order, enabled, level,
  content.text, …}`. The text is placeholder text, e.g. "This section details the test procedures."
- **How they get matched.** They are compared with `test_report_sections`, which expects one file holding
  every section plus a `test_id` key. The flag says "test_id missing."
- **First problem: test_id.** The folder already gives the test, TP07, and the document carries it as
  `test_plan_id`. Demanding the key inside the file is wrong.
- **Second problem: the shape.** The real shape, one section per file, is not on the list of known shapes.
  The closest wrong shape is reported instead.

### 1.4 Video CONFLICT (2 flags)

- **What the two videos show.** Both are short phone clips from "De-Integration" folders (TP07 and TP09):
  someone probing the catalyst bed with a tool. The model described this correctly.
- **Why they were flagged.** The path also contains "APU-Firing", so the route treated them as firing
  recordings. It looked for an ignition, found none, and raised "no ignition found."
- **The cause.** The prompt (`video_timeline.v2`) assumes every clip is a rocket firing. The ignition check
  then runs on every clip.

---

## 2. What I propose

### Step A: replies that keep their shape (gemini_client, synthesis, suggestions)

1. Give every structured call an output cap that leaves room for thinking:
   - Repair: drop thinking to low and raise the cap to 8,192.
   - Unit suggestion: 1,024.
   - Others: sized from what they really use (the ledger shows this).
2. A reply cut at the cap gets its own error, "cut at the output cap," instead of "does not match the schema."
3. One retry, never more:
   - A cut reply is retried once with thinking off.
   - A reply that breaks a field rule is retried once with the validation error added to the request.
   - Today that is 2 calls in 6,000, so the extra cost is small.
4. Keep the existing fallbacks, such as a figure keeping its caption when its reading is unusable.
5. Free-text fields get length limits in the schema (e.g. a rationale of at most 300 characters).

Not doing: moving to ADK. It sends the same schema we already send.

### Step B: units read with a confidence score (one shared reader)

One function in `backend/common/units.py` reads a column (or a row label) and returns a unit, a confidence
and the reason. C tables, the C series adapters, A1 tables and A2 tables all use it, in place of the four
readers they have today.

| What the reader finds | Example | Confidence |
|---|---|---|
| A unit symbol that fits the words of the column | "Tank Pressure [gauge] (bar)" | 0.95 |
| A symbol read through the column's words | "Pre Heat Temperature [ C ]" → °C, not coulomb | 0.90 |
| A unit written as a word, or notation fixed by an alias | "Temperature in Celsius", "(\textdegree C)" | 0.90 |
| The unit in the row's own label (statistics sheets) | "Thrust [N]" in the Parameter cell | 0.90 |
| The same column name with a stated unit elsewhere in the same file or campaign, and values that fit it | Injector 10 "Thrust" → N | 0.80 |
| Only the column's words, with the lab's usual unit | "Thrust" alone → N | 0.50 |
| Nothing | `y3`, "column 5" | 0 |

- **At or above the threshold (proposed: 0.75).** The unit is saved with its confidence and reason
  (`units` and a new `unit_basis` per column). No flag.
- **Below the threshold.** A SOFT flag, with the best guess already filled in. The reviewer only confirms.
- **Time series.** A channel is converted only from a stated unit or a sibling unit (0.80 and above). A
  guess from the usual unit never converts telemetry; it is only offered as a suggestion. A wrong conversion
  corrupts every number in the run.
- **Columns that are not measurements are never flagged.** These are dates, IDs, file numbers, revisions,
  Y/N, and scales such as "(1-5)". This covers files that only describe other files.
- **"No unit needed" becomes a visible choice in the Console.** It exists underneath today: an empty unit
  keeps the numbers as text. The form hides it behind an empty input box. I'll make it a button, and check
  that it also works for a HARD channel: the channel is kept raw and the file continues.
- **Aliases.** Add the LaTeX degree forms to `config/units.txt`.

Expected effect on the 74 SOFT flags: about 66 close by themselves. The ones left are "column 5" and the
instrument list's "Error" column, which need a person. The 176 HARD logger flags stay. I'll show you the folder
rule that answers each rig in one go.

### Step C: SCHEMA_UNKNOWN relies on metadata, not on keys inside the file (A2 JSON)

Search already finds these files through their metadata. Their card reads "Test: plan TP07", the path
reads "Test Plan 7", and the generic reader has already turned their fields into searchable text. Only
the flag still asks for `test_id` inside the file (user, 26 Oct: use the metadata instead).

1. Delete the "required key" rule from the flag check (`json_sections.sniff`, `a2_source/route.py`). The test
   comes from the folder labels, as on every route.
2. A JSON file gets SCHEMA_UNKNOWN only when the reader gets no readable text out of it, such as a bare list of
   numbers with no names, where a person has to say what the columns are.
3. No new layout is added to `config/report_json_schemas.yaml`.

Expected effect: the 9 flags close when those 9 files are re-run.

### Step D: one general video prompt (Route F)

A new `video_timeline.v3`:
- **What the model receives each time.** The file name, folder path and breadcrumb, the labels (plan, run,
  hardware), the date, the duration, the names of nearby files, whether there is sound, and how the frames
  were picked.
- **What the model says first.** What the recording is (firing, cold flow, leak check, inspection or
  de-integration, assembly, setup walkthrough, other) and a short summary.
- **Then events from a general list.** Ignition and shutdown are reported only for a firing.

In the route, the ignition time and the "no ignition" check run only when the model says the clip is a
firing. A de-integration clip gets a summary and events, with no t0 and no flag.

Expected effect: the 2 flags close. 4 videos would be re-read, at 1 call each.

### Step D2: photos and flowcharts get the same general treatment (A1 figures, Route D)

What the audit of every vision prompt found (26 Oct; the user asked for it):

- **Photos.** `inspect_hardware_photo.v1` gets every standalone photo, plus every photograph inside a
  document (185 of them). The prompt assumes damaged hardware ("often after a hot-fire test or a failure"),
  and its main output is a list of damage.
  - Vendor marketing photos came back with damage. A Moog brochure product shot got "discoloration 0.85"
    and a Rafael datasheet thruster got "discoloration 0.95". Of the 36 photos from outside documents, 7 came
    back with damage.
  - Readings on gauges, scales and screens have no place in the output.
  - The low-confidence flag is based on how sure the damage findings are.
- **Flowcharts.** All 50 flowcharts in documents go to `read_schematic.v2`, which expects parts joined by
  lines carrying a fluid or a signal. Each box became a component of type "other". Decisions such as "Is leak
  hazardous?" became parts, and the order of steps and the yes/no branches were lost.
- **Missing context.** Docling already records each figure's page, section heading and the text around it,
  but the call (`figures.py:202`) sends only the folder path, file name and caption. A Route D photo is sent
  without its date taken (read from the camera data, then dropped) and without the names of its
  neighbouring photos.
- **Already general, no change:** page sorting, page transcription, handwriting, slides, the answer-time
  "look again" step, and the shared metadata preamble. Plots were all read correctly (26 of 26 in Route D);
  only a note on multi-panel figures and log scales is missing. Table images are covered by Step B (units
  in row labels).

The changes:

1. A general photo prompt (`inspect_hardware_photo.v2`):
   - The model first says what the photo is: an inspection after a test, a setup or installation, an
     assembly or de-integration step, a new or as-received part, an instrument or display reading, a
     material sample, a vendor or product image, or other.
   - It then describes the photo and copies all visible text and readings, including displays.
   - It lists damage only when damage is visible. A vendor or product image never gets damage.
   - The low-confidence flag applies only to inspection photos.
2. `read_schematic.v3` first decides between a schematic, a mechanical drawing and a process flowchart. A
   flowchart is read as steps, decisions with their yes/no branches, and their order.
3. `digitize_plot.v2`: one entry per panel for multi-panel figures, and log axes stated as such.
4. Context sent with every image:
   - A document crop gets its page number, section heading, the sentences that refer to it, and the
     document kind.
   - A Route D photo gets its date taken and the names of nearby photos in the same folder.
   - Docling does not need to change; the data is already on the figure node when the call is made.

Cost of re-reading on 3.8 Flash, at about $0.009 per image: about $2 for 235 photos and about $0.50 for 50
flowcharts. The new input bypasses the cache. The exact count is reported before running.

### Step E: re-run only what changed, and check

- **Before any re-run:** I report the number of files and the expected paid calls. Most should come from
  the result cache.
- **What gets re-run:**
  - C workbooks and A1/A2 tables: units.
  - The 9 TP07 JSON files: schema.
  - The 4 videos.
- **Checks:**
  - Unit tests for each step.
  - Flag counts before and after.
  - The retrieval replay and the silver benchmark, compared with 43.2%.
  - The repaired answers in Open WebUI.

Order: A, then B (the largest), then C, then D and D2, then E. A and C are small.

---

## 3. Decisions (answered 26 Oct: yes to all)

1. **Unit threshold:** 0.75. A unit stated in the file, a symbol read through the column's words, a unit in a
   row label, or a sibling-table unit is saved without a flag. A guess from words alone is flagged with the
   guess filled in.
2. **Telemetry:** a guessed unit never converts a time series. It is only offered as a suggestion.
3. **"No unit needed" on HARD logger channels:** allowed. The channel stays as raw numbers and the file
   continues.
4. **Photo re-read scope:** all 235 photos, so every photo also gains the new context.
5. **Re-runs:** allowed one route at a time, after the file count and expected paid calls are reported.

---

## 4. Exact locations (for the agent making the changes)

Line numbers are from commit 5dcd92a. If a line has moved, search for the function name given next to it.
Read the wiki page listed for each step before editing; it explains the code around the change.

Rules that apply to every step:
- Run `ruff format` on changed files only.
- Never edit `processing.scope`.
- Route B sends nothing to Gemini.
- Run the step's tests before moving to the next step.

### Step A: replies that keep their shape
Wiki: `.wiki/platform/gemini-gateway-client.md`, `.wiki/backend/answer-engine.md`

| File : line | Change |
|---|---|
| `backend/llm_engine/gemini_types.py:93` (`StructuredOutputError`) | Add `OutputCutError(StructuredOutputError)` next to it: "the reply was cut at the output cap". |
| `backend/llm_engine/gemini_client.py:528` (`_result`, parse at :536) | Before `parse_structured`: when `parsed.finish_reason` says the cap was reached (check the value the adapter gives in `gemini_adapters.py`), raise `OutputCutError`. |
| `backend/llm_engine/gemini_client.py:632` (`generate`) and `:654` (`generate_sync`) | One retry, never two, in one shared helper. For `OutputCutError`, retry with thinking at the lowest level the model accepts (Flash has no "minimal"; see `suggestions.py:83`). For any other `StructuredOutputError`, retry with the validation error added as a last user message. The retry is recorded in `llm_calls` like any call. |
| `backend/llm_engine/vision/service.py:116` (`Task`) | Add a `max_output_tokens` field, set it for each task in the table at `:131–156`, and pass it in the call at `:401`. |
| `backend/llm_engine/suggestions.py:30` (`UnitProposal.rationale`) | Add `Field(max_length=300)`. |
| `backend/llm_engine/suggestions.py:76` (the `generate_sync` call) | Add `max_output_tokens=1024`. |
| `backend/llm_engine/engine/synthesis.py:32` | `REPAIR_MAX_OUTPUT_TOKENS = 8192`. |
| `backend/llm_engine/engine/synthesis.py:225` | `thinking=ThinkingLevel.LOW` (was MEDIUM). |
| `backend/llm_engine/enrichment/extract.py:167` (the `generate_sync` call) | Add a cap sized from the ledger: `select purpose, max(output_tokens) from llm_calls where status='ok' group by 1`. Use the same query to size the vision caps. |
| `backend/routes/a1_office/figures.py` (`_readable`) | No change. The figure fallback stays. |

Tests: `backend/tests/unit/llm_engine/gemini/test_gemini_client.py`:
- a cut reply raises `OutputCutError`;
- a cut reply is retried once with low thinking;
- a rule-breaking reply is retried once and carries the error text;
- a second failure is raised, not retried.

`backend/tests/unit/llm_engine/engine/test_analysis_synthesis.py`: the repair call uses the new cap and thinking level.

### Step B: units read with a confidence score
Wiki: `.wiki/backend/route-c-telemetry.md`, `.wiki/backend/route-a1-office.md`, `.wiki/backend/route-a2-source.md`,
`.wiki/backend/review-backend.md`, `.wiki/frontend/review-ui.md`

**The shared reader**

| File : line | Change |
|---|---|
| `backend/common/units.py` (after `fits_quantity`, :193) | Add `UnitReading(unit, confidence, basis)`, `QUANTITY_WORDS` (temperature/temp/preheat → temperature; pressure/PT → pressure; thrust/force/load → force; mass flow/MFR/throughput → mass flow; duration/time → time; voltage, current, power, frequency, mass, length/diameter/roughness), `NOT_MEASUREMENT` words (date, id, no., file number, part, revision, Y/N, a range in brackets such as "(1-5)"), `UNIT_CONFIDENCE_MIN = 0.75`, and `read_unit(label, *, siblings=None, values=None) -> UnitReading \| None`. It implements the confidence table in Step B and uses `parse_unit` (:148) and `fits_quantity` (:193). |
| `config/units.txt` (the alias block at about :67–75) | Add LaTeX degree aliases: `\textdegree C`, `\textdegree{}C`, `$^\circ$C`, `^\circ C` → degC; the same for F. |

**Route C tables** (`backend/routes/c_telemetry/tables.py`)

| Line | Change |
|---|---|
| `:25` `DIMENSIONLESS_HEADERS` | Move into `NOT_MEASUREMENT` in `common/units.py`, and import it from there. |
| `:65` `header_unit` | Return `read_unit(header).unit` only when its confidence is at least the threshold. Every current caller keeps working: `delimited.py:228`, `workbook.py:203`, `pipeline.py:477`, `suggest.py:52`. |
| `:119` `Table.column_units` | Also read units from a row-label column. When the first column is named Parameter, Quantity, Measurand or Channel and its cells end in a unit ("Thrust [N]"), each row gets that unit. Return the reason for each unit as well. |
| `:176` `table_nodes` metadata | Next to `units`, add `unit_basis` (column → reason and confidence). |
| `:207` `unit_flags` | Flag only when `read_unit` is below the threshold and the column is a measurement. Put the best guess into `evidence.candidate_units` (`CandidateUnit`, `dispatcher/contract.py:380`) so the reviewer only confirms. |

**Route C units from other files**

| File : line | Change |
|---|---|
| `backend/routes/c_telemetry/pipeline.py:444` (`sibling_units`) | Keep it. Next to it, add `campaign_units(session, test_plan_id, hardware_item)`: the column units already stored in `document_nodes.metadata->'units'` of tables with the same test plan or hardware. Pass them to `read_unit(siblings=...)`. This covers the "Injector 10" case. |
| `backend/routes/c_telemetry/series.py:269` (`resolve_channels`) | A logger channel takes a unit from the file or from a sibling only (confidence at least 0.8, reason "sibling"). A guess from the usual unit never converts a channel. |
| `backend/routes/c_telemetry/suggest.py:39` (`suggest_unit`) | When nothing is stated, propose `read_unit`'s best guess with its confidence. It stays below the 0.9 auto-apply line. |

**A1 and A2 tables**

| File : line | Change |
|---|---|
| `backend/routes/a1_office/tables_qa.py:27` (`UNIT_IN_HEADER`), `:78` (`units_by_column`), `:156` | Use `read_unit` for each header cell and for row labels. Store `unit_basis` next to `units_by_column`. |
| `backend/routes/a2_source/route.py:219` (`unitless_values`), `:247` (`_unit_flag`) | Use `read_unit` for headers and row labels, and flag only below the threshold. |
| `backend/routes/a2_source/latex.py:1609` (`unit_text`) | Check that `\textdegree` survives as text, so the alias in `units.txt` can read it. |

**"No unit needed"**

| File : line | Change |
|---|---|
| `backend/dispatcher/contract.py:211` (`SetFactUnit.unit`) | Description: "null = no unit needed: these numbers are not measurements". `backend/indexing/overlays.py:87` (`_set_fact_unit`) already keeps the numbers as text when the unit is null. No logic change. |
| `frontend/console/src/lib/components/review/resolution.ts:8` | Label `set_fact_unit`: "Set unit, or no unit needed". |
| `frontend/console/src/lib/components/review/ResolutionForm.svelte:106` | Add a "No unit needed" button that sets `draft.unit = null`, with one line saying when to use it: IDs, dates, counts, or a file that lists other files. |
| Route C logger channels: `backend/review/rules.py:148` (`ChannelMapEntry`) | A halted Route C file resumes through its channel rule, not through the flag answer (`review/cases.py:768` `_resumable`, `celery_redis/tasks_process.py:250` `resume_for_rule`). So "no unit needed" writes a rule entry with `physical_quantity="other"` and `unit="dimensionless"`. First check that `parse_unit("dimensionless")` (`common/units.py:148`) works and that `routes/c_telemetry/normalize.py` keeps the values unchanged. |
| `frontend/console/src/lib/components/review/ChannelMapView.svelte:174`, `channel_map.ts` | Add a "No unit needed" choice per column that produces that entry. |

**Tests**
- `backend/tests/unit/common/test_units.py`:
  - one test per row of the confidence table;
  - "Pre Heat Temperature [ C ]" → degC, not coulomb;
  - "Likelihood (1-5)" → not a measurement;
  - "Preheat (\textdegree C)" → degC.
- `backend/tests/unit/routes/c_telemetry/test_pipeline.py`:
  - a statistics sheet with "Parameter: Thrust [N]" rows raises no flags;
  - a file register ("File Number | Part ID | Exists? (Y/N)") raises no flags;
  - "Thrust" with a campaign sibling "Thrust (N)" → N with reason "sibling";
  - "y3" stays HARD.
- `backend/tests/unit/routes/c_telemetry/test_suggest.py`: the best guess is proposed below 0.9.
- `backend/tests/unit/routes/a1_office/test_figures_tables_handwriting.py`: `units_by_column` and row units.
- `backend/tests/unit/routes/a2_source/test_latex_route.py`: `\textdegree C` is read.
- `backend/tests/unit/indexing/test_overlays.py`: a null unit keeps the numbers as text.
- Console: `npx svelte-check`.

### Step C: SCHEMA_UNKNOWN relies on metadata
Wiki: `.wiki/backend/route-a2-source.md`

| File : line | Change |
|---|---|
| `backend/routes/a2_source/route.py:831` | `if sniffed.shape == "unknown":` becomes `if sniffed.shape == "unknown" and not sniffed.flattened:`. A JSON file whose fields were read as text gets no flag. The test comes from the folder labels, as it already does. |
| `backend/routes/a2_source/json_sections.py:172` (`sniff`) | No change. `missing_keys` stays as information in the reading. |
| `backend/dispatcher/runner.py` (`_own_flag`, about :140) | No change. On re-run, the route no longer raises the flag, and the old flag closes as AUTO_RESOLVED. |

Tests: `backend/tests/unit/routes/a2_source/test_json_route.py`:
- a one-section-per-file JSON (`id`, `title`, `content.text`) raises no flag;
- a JSON with no readable fields raises SCHEMA_UNKNOWN.

### Step D: one general video prompt
Wiki: `.wiki/backend/route-f-video.md`, `.wiki/backend/vision-service.md`

| File : line | Change |
|---|---|
| New: `backend/llm_engine/prompts/vision/video_timeline.v3.md` | The general prompt. Its user part takes `$file_name`, `$folder_path`, `$labels`, `$date`, `$duration_s`, `$nearby_files`, `$has_audio` and `$frame_plan`. Keep v2; never edit a released prompt. |
| `backend/llm_engine/vision/service.py:153` | Task version `video_timeline.v3`. |
| `backend/llm_engine/vision/service.py:357` (`video_timeline`) | Take those values and put them in `variables`. |
| `backend/llm_engine/vision/schemas.py:262–272` (`VideoEvent`, `VideoTimeline`) | Add `recording_kind` (firing, cold_flow, leak_check, inspection, assembly, setup, other) and `summary`. Keep the event types general. |
| `backend/routes/f_video.py:620` (in `_test_cell`, :586) | Pass the values: `folder.breadcrumb`, the labels, `folder.siblings` names, `info.duration_s`, `info.has_audio`. |
| `backend/routes/f_video.py:632–641` (t0 from the model) and `:679` (the CONFLICT condition) | Look for t0 and raise "no ignition found" only when `recording_kind == "firing"`. When cloud reading is not allowed, keep today's luminance-only behaviour. |
| `backend/routes/f_video.py:638` (summary lines), `:705` (catalog) | Add the model's summary and `recording_kind`. |
| `backend/routes/f_video.py:60`, `:420` (`TEST_CELL_HINTS`, `_hint_test_cell`) | No change. They only choose how frames are sampled. |

Tests: `backend/tests/unit/routes/f_video/test_f_video.py`:
- a de-integration reading gives no t0 and no CONFLICT;
- a firing reading with no ignition still raises CONFLICT.

`backend/tests/unit/llm_engine/vision/test_vision_service.py`: the new variables reach the prompt.

### Step D2: photos, flowcharts, plots and image context
Wiki: `.wiki/backend/vision-service.md`, `.wiki/backend/route-d-photos.md`, `.wiki/backend/route-a1-office.md`

| File : line | Change |
|---|---|
| New: `backend/llm_engine/prompts/vision/inspect_hardware_photo.v2.md`, `read_schematic.v3.md`, `digitize_plot.v2.md` | The new prompts as described in Step D2. Keep the old versions. |
| `backend/llm_engine/vision/service.py:131–156` | Task versions for the three tasks. |
| `backend/llm_engine/vision/service.py:307`, `:319`, `:331` (`digitize_plot`, `read_schematic`, `inspect_hardware_photo`) | Take an `about` text (the context below) as a prompt variable. |
| `backend/llm_engine/vision/schemas.py:242` (`HardwarePhotoReading`) | Add `photo_kind` (inspection, setup, assembly, as_received, instrument_reading, material_sample, vendor_image, other) and `readings` (values on gauges, scales and screens). `failure_modes` stays and may be empty. |
| `backend/llm_engine/vision/schemas.py:203` (`SchematicReading`) | Add `drawing_kind` (schematic, mechanical, flowchart), plus `steps` and `decisions` (each decision with its yes and no targets) for flowcharts. |
| `backend/llm_engine/vision/schemas.py:170`, `:176` (`PlotSeries`, `PlotReading`) | Add `panel` on each series, and `log_scale` on each axis. |
| `backend/routes/d_photos.py:213–217` (in `read_photo`, :199) | Raise LOW_CONFIDENCE_EXTRACTION only when `photo_kind == "inspection"`. |
| `backend/routes/d_photos.py:336` (`context`) | Add the date taken (`Normalized.taken_at`, :79) and up to 10 names of image files in the same folder (`folder.siblings`). |
| `backend/routes/d_photos.py:166`, `:181`, `:192` (`render_photo`, `plot_summary`, `schematic_summary`) | Show the photo kind, readings and flowchart steps in the node text and summary. |
| `backend/routes/a1_office/figures.py:202` (`figure_context`) | Build `about` from `node.page_no`, `node.breadcrumb` (the section heading), `_referencing_sentences(caption, texts)` (:75, now called before the reading), and the document kind when the route knows it (`a1_office/route.py:182` builds `context`). Pass it in the calls at `:206–262`. |
| `backend/routes/a1_office/figures.py:88`, `:102` (`render_plot`, `render_schematic`) | Render panels, and flowchart steps and decisions. |

Tests:
- `backend/tests/unit/routes/d_photos/test_d_photos.py`: a vendor-image reading raises no flag; an inspection reading keeps today's rule.
- `backend/tests/unit/routes/a1_office/test_figures_tables_handwriting.py`: the call receives the page, section and referring sentences; a flowchart renders as steps.
- `backend/tests/unit/routes/vision_readings.py`: update the shared reading fixtures for the new fields.
- `backend/tests/unit/llm_engine/vision/test_vision_service.py`: the task versions.

### Step E: deploy, re-run, check
Wiki: `.wiki/platform/compose-stack.md`, `.wiki/backend/benchmark-runner.md`

1. Rebuild and restart the images of the workers that run the changed routes, then `api` and `console`. Use
   `docker compose -p dcl-v2 --env-file ../../.env -f compose.yaml -f compose.dev.yaml` from `backend/devops`.
   Use `docker stop` only, never `docker rm`.
2. `backend/dispatcher/reindex.py`: run `--route <X> --dry-run` first and report the file count and the
   expected paid calls. Then run it for real, one route at a time: C (units), A2 (JSON and units), F (video),
   D (photos).
3. The A1 figure re-read needs a file filter that `reindex.py` does not have yet: add `--doc <id>` (repeatable)
   to its `main`. Then pass only the documents with photographs or flowcharts, or the smaller set from
   decision 4.
4. Count the open flags by type before and after each route.
5. Run the retrieval replay (`retr/measure.py`, baseline run 9b468dcd) and the silver benchmark from the
   Console (compare with 43.2%). Check one repaired answer, one de-integration video and one vendor photo in
   Open WebUI.
