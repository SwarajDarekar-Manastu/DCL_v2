# Plan: a review screen shaped by the question each flag asks

Status: **revised after the UX review of 2026-10-27** ([UX_REVIEW_review_area.md](UX_REVIEW_review_area.md)); waiting for sign-off. No code has been changed. Sections 1–4 are the first draft; section 6 holds what changed.

## 1. What a reviewer meets (walkthrough, 2026-10-27, 1440 × 900, test reviewer)

Task: clear the queue, starting with TP07 PreHeat and TP24, which hold 11 open handwritten entries on 5 pages. I stopped short of Apply. Screenshots are in the session scratchpad (`ux/01–11`).

| # | Where | What happened | Cost to the reviewer |
|---|---|---|---|
| W1 | Home | No count of waiting work. The Review card still says "Resolve, reject, undo"; reject no longer exists | An extra click; stale words |
| W2 | Queue | "17 SOFT" in the header, 6 rows below (flags against cases). "· 1", "· 11" are page numbers, unlabelled. "LOW CONF (2)" and a bare sparkle icon. **One file (TP24) is four rows**, one per page | Unclear how much is left; one file means opening four cases |
| W3 | Case, top | The first full screen is a **RESOLVED** table comparison from an older version ("Reading A" OCR garbage). The open questions sit below the fold. The header reads "route A1 · document ACTIVE_WITH_SOFT_FLAGS". Six buttons in a row | Scroll; internal words |
| W4 | Open flag | The page appears as a ~110 × 160 px thumbnail. The label is the reader's ("Table 6 Test 1, Temperature [C]") and can only be checked after zooming. Two flags for the same page look identical. "Suggested" names no value | The question cannot be answered from this view |
| W5 | Zoom | Readable, but it is a modal over the answer controls: look, memorise, close, answer. **Escape does not close it.** It opens at the top of the page with no marker of where the entry is ("Notes bottom right" is off-screen) | Memory and search work, every entry |
| W6 | Answer | Dropdown → "Type the value" → a form with Value, **Unit** (meaningless for a text cell) and Illegible. Alternatives are not clickable. "Apply & resume" on a file that is not paused. Nothing fits "partly readable" (a header cut off at the photo edge) | Retyping; wrong words |
| W7 | Fidelity | The sheet says "**discountinued**" (the writer's spelling). The reader wrote "discontinued", against the prompt ("Do not correct"). The old table reading had it right | A wrong value looks right |
| W8 | Viewer | The page image is clear, but it is a separate page: the review context is lost. "Show text" *swaps* image and text instead of placing them side by side. The page text appears **twice** (parent and child). The breadcrumb names the file by hash | Back and forth |
| W9 | Search copy | The page reader's pipe tables are stored on **one line**: rows run together ("| Test 1 | … | | Test 2 | …"). Cause: [chunker.py:200](../../backend/indexing/chunker.py#L200) treats each line break as a sentence end and rejoins with a space | The handwritten tables search holds are broken (TP07 PreHeat, TP24 p8, p10) |
| W10 | Channel map | Works: one row per column, range, unit picker, preview, apply. "suggested · confidence 40 %" under an **empty** picker; the "First values" column is empty | A suggestion that suggests nothing |
| W11 | Ops | Injector 10 sat in PROCESSING because the Route C worker was stopped; once started, the rebuild FAILED: **MinIO storage full** (host disk 100 %, 5 GB free) | Every processing run fails until space is freed |

**What a reviewer actually does:** check a document page by page against its image. The screen makes it handle one cell at a time, across several cases, with the image hidden behind a modal.

## 2. The principle

**The answer happens where the evidence is.** Each kind of question gets a profile with five parts:

1. **The target:** one line on what the flag is about. For example "Reading of page 1", "Table 3 on page 5", "Unit of channel AIN0", "Test plan id of this file", "The whole file".
2. **The original next to what the system made of it:** page image and reading, table image and both tables, number in its sentence, A next to B.
3. **The answer inside that view:**
   - one click for a closed question (A, B, keep, junk, accept);
   - inline editing for an open one (correct the reading, fix cells, pick or type a unit).
4. **The suggestion as the preselected answer,** marked "suggested", instead of a separate box.
5. **Help that lists only the choices on screen.** Each button names its reach: "Junk this table", "Skip whole file".

**Unchanged:**
- **One Apply per case.** A choice marks a draft, and Apply sends every decision of the case together. That means one rebuild per case, not one per click.
- **The server decides what is allowed.** It keeps `allowed_actions` and `subject`; a profile only arranges them.

## 3. The profiles

Counts are from `review_flags` on 2026-10-27.

| # | Question (flag type · what it is about) | Seen | Screen | Answers |
|---|---|---|---|---|
| Q1 | Unit of telemetry channels (UNIT_AMBIGUITY · channel) | 176, all by people | **Channel map**, as today | Unit per channel, suggestion preselected; apply all; propose to the folder |
| Q2 | Unit of spreadsheet columns (UNIT_AMBIGUITY · sheet column) | 68 | **Channel map** when there are two or more columns (as today); a single column gets Q3's chips | Unit, or "No unit needed" |
| Q3 | Unit of a number in text (UNIT_AMBIGUITY · line) | 7 | **Number in its sentence**, the number highlighted | Candidate unit chips, the suggestion preselected; "Type a unit"; "No unit needed". All are `set_fact_unit`, which fixes the bug. |
| Q4 | Reading of a page (LOW_CONFIDENCE · page): unsure handwriting, a refused page read, or low OCR | 11 open | **Page check:** the page image (zoom) beside the text read from it. Tables are drawn as grids and the unsure cells are amber, with confidence and alternatives. | "Reading is right"; "Edit the reading" (every cell and block editable; clicking an alternative fills its cell); "Junk page N" |
| Q5 | Reading of a table (LOW_CONFIDENCE · object, two readings) | 5 by people | **Table check:** the table region of the page above readings A and B, with the differing cells marked | "A is right"; "B is right"; "Edit cells" (the chosen reading as an editable grid → `choose_table: edited`); "Junk this table" |
| Q6 | Reading of a figure or photo (LOW_CONFIDENCE · object, image) | 22 auto | **Image check:** the image, large, beside what the reader made of it (series, components, caption) | "Keep as read"; "Junk this image" |
| Q7 | Two sources disagree (CONFLICT · sources_disagree) | 4 | **A beside B**, with where each came from and links | "A is right"; "B is right"; "Both are valid"; "One supersedes the other" (pick which) |
| Q8 | A check failed (CONFLICT · check_failed) | 9 | **Found beside expected** | "Accept as it is"; "The check does not apply" |
| Q9 | A note to confirm (CONFLICT · note) | 3 | **The note** | "Right"; "Not relevant" |
| Q10 | Unknown layout (SCHEMA_UNKNOWN) | 9 auto | **Sample with the mapper inline:** column or key next to its sample values | Map the columns or keys; "Junk whole file" |
| Q11 | Whole-file problem (PARSE_FAILURE, UNSUPPORTED_FORMAT, HELD_LARGE_FILE) | none yet | **File card:** name, size, type, error, first KB, "Open in OneDrive" | "Skip whole file" or "Junk whole file" (asks, naming the file); "Notify when readable"; "Approve download" |
| Q12 | Sensitive content (SENSITIVE_CONTENT) | none yet | **Redacted preview** | "Approve for internal use" (admin); "Exclude" |
| Q13 | Information only (CLOUD_RESTRICTED; the formula cap) | – | **One line** saying what happened | "Got it" |

## 4. How it is built

| # | Where | Change |
|---|---|---|
| R1 | New `review/profiles.ts` | The profile registry: `profileOf(flag)` picks the profile from `flag_type`, `subject`, `evidence.kind` and `relation`. A profile gives the target line, the view component, the answer controls (label, action, button style, confirm), the help lines and the preselected suggestion. A test enumerates every flag kind the server can raise and fails if one has no profile, or if a profile shows an action the flag does not allow. |
| R2 | [FlagConsole.svelte](../../frontend/console/src/lib/components/review/FlagConsole.svelte) | Renders the profile: target line and help in the header, the view with its answer controls, the chosen answer as the flag's draft. The generic dropdown stays only as a fallback, which R1's test keeps unused. |
| R3 | New view components in `components/review/` | `PageCheck` (Q4); `TableCheck` (Q5: page region + A/B + editable grid); `ImageCheck` (Q6); `ChoiceCards` (Q7–Q9: one-click cards); `NumberInContext` (Q3); `FileCard` (Q11). The existing unit, array, JSON and sensitive panes become the views of Q1, Q10 and Q12 unchanged. |
| R4 | [CaseView.svelte](../../frontend/console/src/lib/components/review/CaseView.svelte) | Open flags first; decided flags under a closed "Decided earlier (n)". |
| R5 | [FlagGuide.svelte](../../frontend/console/src/lib/components/review/FlagGuide.svelte) | Shows the profile's help: only the choices on screen. |
| R6 | [contract.py](../../backend/dispatcher/contract.py) `LowConfidenceEvidence` | Q4 needs `page_image_uri`, `page_reading` (the page text as indexed: Markdown with HTML tables) and `doubtful` [{label, value, alternatives, confidence}]. `page_ocr_text`, which nothing fills, is removed. Q5 and Q6 show the page region from the existing anchor box over the page render, so no new asset is needed. |
| R7 | [contract.py](../../backend/dispatcher/contract.py) `Resolution`, `allowed_actions` | New `correct_page {text}` for page flags: `{correct_page, ignore, mark_junk}`. `set_value` is no longer offered; no stored decision uses it. |
| R8 | [handwriting.py](../../backend/routes/a1_office/handwriting.py), [route.py](../../backend/routes/a1_office/route.py) | One flag per page with the evidence of R6, replacing one flag per entry. A refused page read or low OCR gets the same page flag, with its OCR text. `process_pdf(page_corrections=…)`: a corrected page is indexed from the person's text (source `human`, no model call). |
| R9 | [office_run.py:44](../../backend/dispatcher/office_run.py#L44) | Loads the document's decided `correct_page` texts next to `critical_field_patterns`. |
| R10 | [overlays.py](../../backend/indexing/overlays.py) | `_set_value` deleted; no other change, since `choose_table` already applies edited cells. |
| R11 | Manual 06 §6, manual 08 §4 | The review screen by question kind (this table). |

## 5. Phases, ordered by the walkthrough

0. **Disk (W11, blocking).** Free space with the user's OK, re-run Injector 10.
1. **Check a document page by page (W2–W9), the task that exists now:**
   - **Queue:** grouped by file ("TP24 HTRCHAR — 4 pages, 9 entries"); labelled page numbers; one count unit.
   - **Page check view:** the page image beside the reading in the case itself, with zoom and pan in place. The reading is drawn with its tables as grids and the unsure cells amber. Selecting a cell moves the image to its spot. The page reader returns a box for each doubtful entry; the box experiment showed Flash places them well. Inline edit, alternatives as chips. "Page is right" / "Save corrections" / "Junk page", then the next page. One Apply per file, so one rebuild.
   - **Backend:**
     - one flag per page (R6–R10);
     - `transcribe_page.v4`: copy spelling exactly as written, and a box for each doubtful entry;
     - page-reader tables become table nodes, with pipe tables converted to HTML, so search keeps rows (W9).
   - **Clean-up:**
     - decided flags folded, with their decision in words, not JSON;
     - plain words for status and route;
     - help listing only the offered choices;
     - the home page shows counts;
     - "reject" wording gone;
     - the button says "Apply" unless the file is paused.
2. **The other question kinds (section 3):** tables with their image region, figures, one-click conflicts, unit in text (and its bug), file cards.
3. **Polish what works:** the channel map shows the suggested unit in its picker or says "no suggestion"; the column mapper goes inline.

Tests per phase:
- **The registry test (R1).**
- **Each view:** renders its evidence and sends the literal resolution its buttons name.
- **Backend:** a corrected page is indexed from the person's text with no model call; page-reader tables keep one row per line in the index.

## 6. After the UX review (2026-10-27)

### Kept from the first draft
- The principle.
- Page-by-page checking.
- Grouping the queue by file.
- Open flags first, decided flags folded.
- The profile registry and its enumeration test.
- The server deciding which actions are allowed.

### Changed
| From the first draft | Now | Why |
|---|---|---|
| A whole-page correction (`correct_page {text}`) | Corrections **per entry or per cell**, anchored to it. `set_value` stays; a cell edit gets its own anchor (table, row, column) | A page-text override freezes the page: a later, better read can never improve a cell, and one stray keystroke changes data silently. Per-entry decisions keep "anchored and replayed" |
| The model's reading preselected | An **explicit confirm** per entry ("○ unconfirmed" until Enter, edit, unreadable or partly readable) | A decision is stored as `human`, so a person must have looked |
| "One Apply per case" (§2) vs "one Apply per file" (§5) | **One Apply per page**, and the file rebuilds once, after its last page | Safe commits, visible progress, a single rebuild |
| 13 profiles | **About 5 answer shapes**: confirm or edit a reading; choose one; unit table; mapper; acknowledge | Fewer components; conflicts, checks and notes differ only in wording |
| Channel map last | **Unit correctness first.** About 186 of the ~202 decisions people made are units | `set_unit` on a sheet column changes no data; "First values" are empty; suggestion labels contradict the preselected unit; the empty preview still enables Apply |

### Added (the UX review found them)
- **The zoom can't scroll.** The lower ~855 px of a page can't be reached, and Escape does nothing.
- **Drafts are lost** on a trip to the viewer.
- **Focus falls to the page body** after opening a case.
- **No live refresh:** no `case` events are published.
- **Questions shown as type codes.** The queue should show the question in words ("Run label already used · 3 files"), group the same question across files, and decide it once.
- **No rebuild status** after Apply.
- **No benchmark with real reviewers.** Planned: 3 reviewers × the 11 entries, timed, against known answers.

### Phases
1. **1a: global fixes, every flag kind.**
   - Open flags first; decided ones folded into sentences (the Audit table).
   - The zoom scrolls and Escape works.
   - Drafts persist; focus moves into the case.
   - "Apply" unless the file is paused.
   - Help lists only the offered choices; home counts; no "reject".
   - Queue rows say the question.
2. **1b: units you can trust.**
   - A sheet column's unit goes through `set_fact_unit` (or `set_unit` gets an overlay).
   - Real "First values".
   - One confidence beside the picker; no preselection below a threshold or for a quantity that does not fit.
   - "Labels only" when nothing converts; "Save n units".
3. **1c: entry-first page check**, on today's flags.
   - The page image is sticky, with pan and zoom.
   - Entries in page order: confirm, edit, unreadable, partly readable; chips fill the field.
   - The whole page as read, with tables as grids, edited cell by cell on click.
   - Apply per page; focus mode; keyboard; drafts kept.
4. **1d: backend.** The chunker fix (W9, its own ticket, now). Then `transcribe_page.v4`: spelling verbatim, a box per doubtful entry (loupe crops), and page-reader tables as table nodes. Per-page Apply with a deferred rebuild.
5. **2.**
   - Queue by question and by file, with bulk decisions for identical questions (the 3 run-label conflicts).
   - Table and image checks.
   - The reviewer benchmark.

## 7. Pipeline issues in the same update (traced 2026-10-27)

| # | Issue | Root cause, with evidence | Fix | Proof it worked |
|---|---|---|---|---|
| B1 | **Decided files that never moved on.** 22 telemetry files stayed HALTED after people approved all 176 channel units; the case showed "decided" next to "document HALTED" | The step after a decision is a one-shot task message, and nothing checks that it happened. `resume_route_c` failed on MinIO "storage full" ([tasks_process.py:98-107](../../backend/celery_redis/tasks_process.py#L98)). The error is not in `RETRYABLE` ([:62](../../backend/celery_redis/tasks_process.py#L62)), and `_fail` marks only PROCESSING files FAILED, so the rollback left them HALTED **silently**. The nightly sweep ([routing.py:610](../../backend/dispatcher/routing.py#L610)) covers only deleted, superseded and quarantined files. A stopped worker leaves the task waiting just as silently | (a) Storage and connection errors from MinIO count as transient: retry with backoff. (b) A resume that fails for good marks the file FAILED with the error, never silently HALTED. (c) A **reconciler** in beat every 30 min resumes HALTED files with no open HARD flag (Route C: covered by an active approval; others: `resume_staged`) and re-sends PROCESSING files older than 2 h. (d) The case header says "Decided · waiting to resume" or "Resume failed: <reason>" whenever the file has not moved on. (e) An alert when MinIO free space nears its threshold | Fill a test bucket's quota (or stub the error): the file retries and does not stay silently HALTED. With the telemetry worker stopped, apply a unit, start the worker: the reconciler resumes the file in ≤ 30 min |
| B2 | TP23 photo readings missed the cache ($0.20) | **Not a defect.** TP23 was last read on 26 Oct with `inspect_hardware_photo.v1`; yesterday's v2 prompt changes the cache key, so each photo is read once more | No code change. Before a prompt version bump, estimate its re-read cost from `llm_calls` (calls per prompt version) and write it in the commit | – |
| B3 | Chart readings run away: `digitize_plot` hit the 24,562-token cap twice (TP23 p14; "Test 04 Thrust and MFR vs Time"), $0.095 each, and again on every re-run (a failed reply is not cached); complete readings take 9–13k tokens | The prompt says "at most 20 points per series", but the schema enforces no limit ([schemas.py:117-131](../../backend/llm_engine/vision/schemas.py#L117)), and the number of series is unbounded. A cut reply is retried with **twice** the cap ([gemini_client.py:724](../../backend/llm_engine/gemini_client.py#L724)) | Schema limits the model must obey (`series ≤ 12`, `key_points ≤ 20`); cap 12,288. A cut chart is not retried with a doubled cap; it keeps its caption and is flagged once | Re-read the two charts: both complete under 12k tokens and give usable series |
| B4 | Typed pages get OCR when triage calls them handwritten forms (Integration Sheet p2, TP23 plan p1, ECSS-Q-70 p81) | `combine` ([triage.py](../../backend/routes/a1_office/triage.py)) bounds only `scanned_printed` by the text layer, not the handwritten types | The same image-cover rule as `read_whole`: a page with a good text layer and image cover < 0.25 is digital, so no OCR | Those 3 pages have `source=printed`, not `ocr` |
| B5 | Re-runs never delete old asset rows (87 crop rows had piled up) | `commit._asset_ids` upserts by image path and never removes what the new version no longer produces ([commit.py:144-165](../../backend/indexing/commit.py#L144)) | On commit, delete this blob's asset rows the new version did not produce, unless a node or a review flag still points at them; delete their MinIO objects on the same condition. Count the existing orphans before a one-off clean-up | A re-run that drops a figure leaves 0 orphan rows; a flag's picture still opens |

**Where they go in the phases:**
- **B1 first, before 1a.** A decision that never reaches search is the worst failure of the review loop. It needs (d) from the UI.
- **B3 and B4 with 1d** (backend).
- **B5 with 1d.**
- **B2 is a written practice only.**
