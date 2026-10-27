# 1c — Page check: a handwritten page next to everything the reader made of it

**The repository is public.** The page's values below (entries, readings, cells) are made up, with the same shape as the live ones; the real values stay in the database and the CIR, never in git (tests/fixtures/README.md). Doc ids and keys are real.

**Built so far (2026-10-27), and where it differs from this spec:**
- Done: the stored reading (`pages/{n}.reading.json`, `handwriting.reading_record`); `review/page_reading.py` (§4.1); `CaseDetail.page_reading`; `PageCheck.svelte` with confirm, correct (field or chip) and unreadable per entry, and Enter/Esc keys.
- The entry controls sit in a "To check" list above the reading. The highlighted cell shows the value it will be saved as and focuses its field on click. Controls inside a table cell would break the grid.
- Every Apply rebuilds the file at once, as before. The "rebuild after the last page" rule (§4.5) waits for R4 (`PLAN_wiring_audit.md`), which picks up any decision newer than the last index.
- Not yet: editing a cell or text the reader did not flag (`set_cell` / `set_text`, §4.2–4.3). Until then those cells are read-only.

Spec for phase 1c of [PLAN_review_by_question.md](../PLAN_review_by_question.md) §6, ordered as step 4 in [PLAN_wiring_audit.md](../PLAN_wiring_audit.md) §7. Follow [VERIFY.md](VERIFY.md).

**Preconditions:** these must have landed and been verified first:
- **W1.1:** the answer → effect registry;
- **W2:** decisions applied to the route output before chunking;
- **W6-A1:** `pages/{n}.reading.json`, with the shape in [W6-A1.md](W6-A1.md).

Without W2, a correction made on this screen never reaches search (P2.1). Without W6-A1, the screen has nothing to show (P6.1).

---

## 1. The fault, in plain words

A handwritten page is reviewed today as one card per entry the reader was unsure of. Each card has a small page thumbnail, the reader's value and a "Resolution" dropdown with one choice, "Type the value". The reviewer never sees what the reader made of the rest of the page:
- the printed labels;
- the other entries;
- the table the entry sits in.

So they can't judge an entry in its context, and they can't catch a mistake the reader did not mark as unsure. The data for a better screen is not kept: the reader's full output exists only in the vision cache, unlinked (P6.1). And a typed correction would not reach search (P2.1).

**Code path today:**
1. [route.py:256-300](../../../backend/routes/a1_office/route.py#L256): the whole-page read.
2. [handwriting.py:38-100](../../../backend/routes/a1_office/handwriting.py#L38) `page_doubts`: one flag per unsure entry, anchored `{page, content_sha256: key}`. Evidence: `crops=[{crop_uri: page render, model_value, alternatives, confidence, printed_label}]`. Suggestion: `SetValue`.
3. `CaseView.svelte`: one `FlagConsole` per open flag.
4. `EvidencePane` → `LowConfidencePane`, which shows the thumbnail and the reading.
5. The dropdown sends `set_value`.

## 2. Today, observable (live, recorded 2026-10-27)

Case `8c4cdfdf-8d21-4290-b09e-3d2fddbe6213:11` (HTRCHAR, "Test Plan - Heater Bed Temperature Characterisation", page 11) has two open flags:

| Key (`content_sha256`) | Label | Reader's value (exact) | Confidence | Alternatives |
|---|---|---|---|---|
| `990f59414aba02c459e88cc095c57f31` | Trial Name | `Trial 7.1 (warm-up run` | 0.90 | `Trial 7.1 (warm-up rnu`, `Trial 7.1 (warm-up run)` |
| `bd38e744b6017b861d9e6754d0d40e7e` | Sample Name | `Sample B-12 (lot 4` | 0.85 | `Sample B-12 (lot 9`, `Sample B-12 (lot 4)` |

The values have no closing bracket because the reader returned them that way; the screen does not truncate them.

The page's text, as stored in the CIR `pages/11.txt` (4,549 chars):
- a heading `### Bench Heater Trial`;
- **3 HTML tables.**

Both unsure entries are **value cells of a two-column label/value table**: `<td>Trial Name</td><td colspan="3">Trial 7.1 (warm-up run</td>`. Another cell of that table holds crossed-out handwriting, written by the reader as `~~old note~~ 42.0 Ω`.

What exists today:
- **CIR for page 11:** only `11.meta.json` and `11.txt`. There is no `11.reading.json`.
- **Indexed nodes:** 9 nodes span page 11. 0 carry `metadata.handwriting`; 2 contain `warm-up run` in both `content` and `embed_text`.
- **The case screen:** two cards, each with a thumbnail and its value. None of the three tables is shown.

## 3. Target, observable

The same case shows a **Page check**.

**Left pane:** the page image (the 150 dpi render from the flag's `crop_uri`), sticky while the right side scrolls. A click opens the existing zoom dialog, which scrolls and closes with Esc.

**Right pane:**
- A heading `Page 11 as read`.
- The status line `2 entries to check · 0 of 2 done`.
- The reading in order:
  - `Bench Heater Trial` as a heading;
  - each of the 3 tables as a grid;
  - plain text in between.
- **Each unsure entry is highlighted where it sits**, amber. Here that is the value cells next to "Trial Name" and "Sample Name". Under the cell:
  - the confidence (`90 %`);
  - the alternatives as chips;
  - three controls: a text field prefilled with the reader's value, **Confirm** and **Unreadable**.
- Crossed-out text (`~~…~~`) is drawn struck through, not as tildes.
- Every other cell and text block can be edited too: click, type, Enter. This catches mistakes the reader did not mark as unsure.

**Each entry has one state:**
- `○ to check`;
- `✓ confirmed` (the value kept as read);
- `✎ corrected` (a different value, typed or chosen from a chip);
- `✗ unreadable`.

**The Apply button:**
- It reads `Apply page 11`, or `Apply page 11 & resume` when the file is HALTED.
- It is enabled only when every highlighted entry has a state other than `○ to check`.
- Until then the blocker text says `Answer every highlighted entry: 2 left.`

**After Apply, with the reviewer choosing chip 2 for "Trial Name" and confirming "Sample Name":**
- The two flags are RESOLVED:
  - `set_value {value: "Trial 7.1 (warm-up run)"}`;
  - `set_value {value: "Sample B-12 (lot 4"}`.
- The notice reads `Saved 2 answers for page 11.`, followed by the rebuild sentence (§4.5).
- After the rebuild, the nodes of page 11 contain `Trial 7.1 (warm-up run)` in **both** `content` and `embed_text`, and no longer the version without the bracket. Search finds the corrected text.

## 4. Design

### 4.1 Backend: the reading for the screen

**New file `backend/review/page_reading.py`:**
- `Block = {key: str, kind: "heading" | "text" | "table", text: str | None, rows: list[list[Cell]] | None}`, where `Cell = {text: str, struck: list[str], span_origin: [r, c] | None}`.
- `key = sha256(<the block's source text exactly as in the reading>)[:16]`. It is stable while the reading is unchanged, and it is the anchor of corrections (§4.3).
- `parse_reading(markdown: str) -> list[Block]`:
  - Splits on blank lines, the same as [route.py:275](../../../backend/routes/a1_office/route.py#L275), so one block = one route node `vlm/p{page}/{i}`.
  - `<table>` blocks are parsed with the standard library `html.parser` into a grid. `colspan` and `rowspan` are expanded; a spanned position points at its origin cell through `span_origin`.
  - Cell and text content is **text only**: `<br>` becomes a newline and every other tag is dropped. `~~x~~` is split out into `struck`.
  - **No HTML is ever passed to the console.**
- `locate(blocks, entry) -> {block_key, cell: [r, c] | None} | None`: the first block, or cell, whose text contains the entry's `value_raw` (or `[illegible]` when the entry is illegible).
  - When the label is known, a cell in the same row as the label wins: here row `Trial Name`, value cell `[r, 1]`.
  - When the value is not found, the entry is listed under `Not found in the text` and can still be answered.

**`backend/review/api_models.py`:**
- New `PageReading`: `page_no: int`, `image_uri: str` (s3 URI of the page render), `blocks: list[Block]`, `entries: list[PageEntry]`, `corrections: list[PageCorrection]`, `reader_confidence: float | None`, `prompt_version: str`.
- `PageEntry`: `key`, `label`, `value`, `unit`, `alternatives`, `confidence`, `illegible`, `flag_id`, `status`, `decision` (the stored `Resolution` or null), `located` (the result of `locate`).
- `CaseDetail.page_reading: PageReading | None = None`.

**`backend/review/cases.py` `case_detail`:**
1. Fill `page_reading` when the case holds LOW_CONFIDENCE flags with subject `value` on one page, and the CIR has `pages/{n}.reading.json`.
2. The key is `documents.cir_uri` + `pages/{n}.reading.json`. Live `cir_uri` example: `s3://dcl-cir/450467c5…c7/A1/v1/`.
3. Read through an injected `read_cir(uri) -> bytes | None`. The API wires `BucketStore(CIR).get`; tests pass a dict.
4. Join entries to flags by `key == anchor.content_sha256`.
5. When the file is missing, set `page_reading = None` and the screen falls back to today's cards with the note `Re-run this file to check the whole page` (§6).

### 4.2 Backend: answers

`set_value` is unchanged ([contract.py:245](../../../backend/dispatcher/contract.py#L245)): `{value, unit, illegible}`.
- **Confirm** stores `set_value` with the reader's own value. A person looked, so the decision is `human`.
- **Unreadable** stores `illegible: true`.

**New in [contract.py](../../../backend/dispatcher/contract.py), part of the `Resolution` union:**
- `SetCell {action: "set_cell", block_key: str, row: int, col: int, old: str, value: str}`.
- `SetText {action: "set_text", block_key: str, old: str, text: str}`.

These two answers are for content the reader did **not** flag, so they have no flag row of their own. **Rule:** an edit of a highlighted entry's cell is always that entry's `set_value`, never a `set_cell`, so the same text never carries two decisions.

**`ResolveRequest` gets `corrections: list[SetCell | SetText] = []`.** `resolve_case` stores each correction as a new review flag:
- flag type LOW_CONFIDENCE_EXTRACTION, severity SOFT;
- status RESOLVED, with `resolved_by` the actor;
- `route = "review"`;
- anchor `{page, content_sha256: sha256(block_key|row|col)[:32]}`.

The audit records it like any other decision. Origin `review` is never closed by the gate's stale pass ([staged.py:85](../../../backend/review/staged.py#L85) leaves flags of other origins alone; W3.1 makes this explicit).

### 4.3 Effects (W1.1 registry; applied by W2 `apply_decisions` to the route nodes before chunking)
| Answer | Target | Applies when | Effect |
|---|---|---|---|
| `set_value` | The route node holding the entry: `metadata.handwriting[*].key == anchor.content_sha256`, which is present before chunking | Always | Replaces the old value text in that node's content (the value cell), the reading's metadata and its facts (source `human`). Illegible: the value becomes `[illegible]` |
| `set_cell` | The route node `vlm/p{page}/*` whose source text hashes to `block_key` | Cell `[row, col]` (after span expansion) has text equal to `old` | Writes `value` (HTML-escaped) into that origin cell and re-serialises the table |
| `set_text` | The same node, found by `block_key` | The node's text equals `old` | `content = text` |

When `old` no longer matches (for example, a new prompt version changed the reading), the decision is **not applied**. W3.3 marks it superseded, and the screen shows it under `Earlier corrections that no longer match`, to check again. A changed reading is never overwritten blind.

### 4.4 Rules for allowed answers
`allowed_actions` ([contract.py:388](../../../backend/dispatcher/contract.py#L388)) stays `{set_value}` for a value flag. `set_cell` and `set_text` are allowed only as `corrections` on a case that has `page_reading`. `resolve_case` refuses them otherwise, with InvalidAction `corrections need the page's reading`.

### 4.5 Rebuild timing: one rebuild per file, not per page
In `resolve_case`, after the decisions are stored:
- If the document has **no other open LOW_CONFIDENCE page case**, it is rebuilt now (`_rebuild_committed`, as today).
- Otherwise it is not rebuilt now. The notice says `The file is rebuilt when its last page is checked (N pages left), or within 30 minutes.` The W3.4 reconciler rule ("decision newer than the last index") picks it up at most 30 minutes later, so a reviewer who stops halfway loses nothing.
- A **Rebuild now** link in the notice starts it at once (POST `/review/cases/{case_key}/rebuild`, reviewer role).

### 4.6 Console
**New `frontend/console/src/lib/components/review/PageCheck.svelte`.** Props: `reading: PageReading`, `drafts`, `corrections` (bindable), `onApply`.

**Layout:**
- **At 1280 px and wider:** two columns, the image left (`position: sticky; top: header height`, height up to the viewport) and the reading right.
- **Narrower:** stacked, with the image collapsible (`Show page image`).

**Rendering:**
- Each block renders from `blocks`: a heading, a paragraph, or `<table>` built from `rows`.
- **Text only.** No `{@html}` anywhere in the component. A test enforces it (§9).
- Highlighted cells get an amber background and a label for screen readers: `Unsure entry: Trial Name`.

**The entry controls** sit under the highlighted cell or text, all in the same tab order:
- the text field, labelled with the entry's label;
- the chips;
- **Confirm**;
- **Unreadable**.

**Keyboard:**
- On open, focus is on the first `○ to check` entry's field (this replaces 1a's focus on the Resolution select for page cases).
- **Enter** in an entry field: Confirm when the value is unchanged, Corrected when changed. Focus then moves to the next `○` entry, or to Apply when none is left.
- **Esc** in an entry field restores the reader's value.
- A non-entry cell or text block opens an editor on click or Enter. Enter saves the draft correction; Esc cancels.

**Drafts:**
- Entry answers live in the existing `drafts` record, by flag id.
- Corrections are kept by `cell:{block_key}:{r}:{c}` or `text:{block_key}`, with the same sessionStorage persistence (`drafts.ts` extended).

**Apply** sends `resolveCase(caseKey, {resolutions, corrections, rule_scope: null})`.

**[CaseView.svelte](../../../frontend/console/src/lib/components/review/CaseView.svelte):**
- When `detail.page_reading` is set, render `PageCheck` in place of the `FlagConsole`s of the flags it covers.
- Any other flag of the case still renders as today.

**Words in [decisions.ts](../../../frontend/console/src/lib/components/review/decisions.ts):**
- `resolutionText`:
  - `set_value`: `Confirmed “…”` or `Corrected to “…”`;
  - `set_cell`: `Cell corrected to “…”`;
  - `set_text`: `Text corrected`.
- `subjectText`: `Handwritten “Trial Name” on page 11`.

**Help:** `flag_guide.ts` gains a page-check entry that lists only Confirm, Correct (field or chip), Unreadable and Edit any cell.

## 5. Must not change
- One Apply per case. Cases are per page already (`case_key = doc_id:page`).
- The server decides allowed answers.
- The shape of `set_value`, so the decisions already stored stay valid.
- Cases without `page_reading` look exactly as after 1a.
- **Undo** reopens the entry flags of the last Apply, as today ([cases.py:1420](../../../backend/review/cases.py#L1420)). The review-origin correction rows of that Apply are deleted, with the audit event kept.
- No console HTML comes from model output.

## 6. Edge cases
| Case | Expected |
|---|---|
| The file was processed before W6-A1 (no `reading.json`) | Cards as today, plus the note `Re-run this file to check the whole page` |
| An entry's value is not found in the text | Listed under `Not found in the text`; still answerable |
| The same value appears twice | The cell in the label's row wins; otherwise the first occurrence |
| An illegible entry | Its cell shows `[illegible]` highlighted; the field is empty; Confirm is disabled (only Corrected or Unreadable) |
| A spanned cell (`colspan="3"`) | One editable cell; the edit lands on the origin cell |
| Crossed-out text | Shown struck through. Editing the cell edits the visible text; the struck part is kept unless the reviewer deletes it |
| A HARD entry (label matches `critical_field_patterns`) | The file is HALTED; the button reads `Apply page N & resume`; the file resumes when no HARD flag is left |
| Another reviewer applied first | The existing error is shown: `flag … is RESOLVED, not open` |
| A new prompt version changed the reading | Old corrections become superseded and are listed to check again (§4.3) |
| A very long page | The reading scrolls; the image stays in view |

## 7. Related files to re-read before landing
- [cases.py](../../../backend/review/cases.py): `case_detail`, `_case`, `resolve_case` (the corrections path), `undo_case` and `_reopen` (deleting correction rows), `_rebuild_committed`.
- [api/review.py](../../../backend/api/review.py): the resolve and undo routes and `start_rebuild`; the new rebuild route.
- [contract.py](../../../backend/dispatcher/contract.py): the `Resolution` union, `allowed_actions`, `flag_subject` (review-origin rows are subject `value`).
- [staged.py](../../../backend/review/staged.py) `gate`: the stale pass must leave `route = "review"` rows alone.
- [overlays.py](../../../backend/indexing/overlays.py), or the W2 `apply_decisions`: the three effects.
- [handwriting.py](../../../backend/routes/a1_office/handwriting.py): keys, and the holder node choice (`text in n.content`).
- Console: [CaseView.svelte](../../../frontend/console/src/lib/components/review/CaseView.svelte), [drafts.ts](../../../frontend/console/src/lib/components/review/drafts.ts), [decisions.ts](../../../frontend/console/src/lib/components/review/decisions.ts), [flag_guide.ts](../../../frontend/console/src/lib/components/review/flag_guide.ts), `AssetImage.svelte` (presigned image), `api_schema.d.ts` (`pnpm gen:api`).

## 8. Steps
1. `page_reading.py` with `parse_reading` and `locate`, and its tests. Done when the tests pass on the real `11.txt` (3 tables, 1 heading).
2. `PageReading` in `CaseDetail`, plus `case_detail` filling it. Done when the API test sees 2 entries located in row `Trial Name` and row `Sample Name`.
3. `SetCell`/`SetText`, `ResolveRequest.corrections`, the review-origin rows, undo. Done when the resolve and undo tests pass.
4. The effects in the registry. Done when the C2 test (decision reaches `content` and `embed_text`) passes for all three answers.
5. The rebuild rule and the rebuild route. Done when the last page's Apply starts a rebuild and an earlier page's does not.
6. `pnpm gen:api`; `PageCheck.svelte`; `CaseView` integration; drafts; words; help. Done when `pnpm -s check` is clean and the console tests pass.
7. Deploy (§10), re-run the pilot, verify live, clean up (§10b).

## 9. Automated tests (each must fail before the change, with the message given)

**Backend, `backend/tests/unit/review/test_page_reading.py`:**
- `test_a_reading_splits_into_heading_text_and_tables_with_stable_keys`:
  - Input: `"### Bench Heater Trial\n\n<table><tbody><tr><td>Trial Name</td><td colspan=\"3\">Trial 7.1 (warm-up run</td></tr></tbody></table>"`.
  - Expected: blocks `[heading "Bench Heater Trial", table rows [["Trial Name", "Trial 7.1 (warm-up run", ↳, ↳]]]`, where ↳ has `span_origin == [0, 1]`, and `blocks[1].key == sha256(<the table source>)[:16]`.
  - Before the change: `ModuleNotFoundError: backend.review.page_reading`.
- `test_crossed_out_text_is_kept_apart_and_markup_is_never_passed_on`:
  - Cell `~~old note~~ 42.0 Ω` → `text == "old note 42.0 Ω"`, `struck == ["old note"]`.
  - Cell `<img src=x onerror=alert(1)>` → `text == ""`.
- `test_an_entry_is_located_in_its_labels_row`: on the live `11.txt` fixture (copied into `tests/fixtures/sample_page.txt`), `Trial Name` → `{cell: [r, 1]}`, where `r` is the row whose first cell is `Trial Name`.

**Backend, `backend/tests/unit/review/test_cases.py`:**
- `test_a_page_case_shows_the_whole_reading_with_its_entries`:
  - Setup: a document with `cir_uri`, two value flags with the keys above, and a `read_cir` dict holding `reading.json`.
  - Expected: `detail.page_reading.page_no == 11`, `[e.label for e in entries] == ["Trial Name", "Sample Name"]`, `entries[0].flag_id == <flag id>`.
  - Before the change: `AttributeError: 'CaseDetail' object has no attribute 'page_reading'`.
- `test_corrections_are_stored_as_review_rows_and_survive_a_rebuild`:
  - Resolve with `corrections=[set_cell(block, 1, 2, old "40.25", value "40.52")]`, then run `gate` twice with the route's own flags.
  - Expected: the row has `route == "review"` and status `RESOLVED` after both runs.
- `test_the_last_page_rebuilds_now_and_an_earlier_page_waits`:
  - Two open page cases on one document. Apply page 6: `rebuild_doc_id is None`. Apply page 7: `rebuild_doc_id == doc_id`.

**Backend, `backend/tests/unit/indexing/test_decisions_reach_search.py`** (C2, needs W2):
- `test_a_typed_handwriting_value_reaches_content_and_embed_text`:
  - A route node `vlm/p11/2` holds the table with `Trial 7.1 (warm-up run` and `metadata.handwriting=[{key: K, value_raw: …}]`. The decision is `set_value {value: "Trial 7.1 (warm-up run)"}` on `{page: 11, content_sha256: K}`.
  - After `apply_decisions` and `index_document` with stub models, every node of page 11 that held the old value now holds the new one in `content` and `embed_text`.
  - Before W2: the assertion fails with the old value still present.
- `test_a_cell_correction_whose_old_text_changed_is_not_applied`: the `old` mismatch leaves the content unchanged, and the decision is reported as superseded.

**Console, `frontend/console/tests/review/PageCheck.test.ts`:**
- `shows the page as read, with tables as grids and the unsure entries highlighted`:
  - The grid has a cell `Trial Name`, and the cell next to it has the accessible name `Unsure entry: Trial Name`.
  - The status text is `2 entries to check · 0 of 2 done`.
- `Enter confirms the first entry and moves to the next`:
  - After Enter, the status reads `1 of 2 done`, and the focused field's label is `Sample Name`.
- `a chip fills the field and marks the entry corrected`.
- `Apply waits for every entry, then sends the answers and the corrections`:
  - Before the last answer, the button is disabled and the blocker reads `Answer every highlighted entry: 1 left.`
  - After: `resolveCase` is called with `resolutions` `[{flag_id: "f1", resolution: {action: "set_value", value: "Trial 7.1 (warm-up run)"}}, {flag_id: "f2", resolution: {action: "set_value", value: "Sample B-12 (lot 4"}}]` and `corrections: []`.
- `model text is never rendered as HTML`: a cell with text `<img src=x onerror=alert(1)>` renders as that literal text, and the container has no `img` element.

## 10. Verification after deploy

**Rebuild and restart, one image at a time (map in VERIFY.md §4):**
- `dcl-v2-parse:local` for W6-A1 and the shared tail: `worker-cpu-parse`;
- `dcl-v2-backend:local`: `api`, `beat`, `worker-io-light`, `worker-telemetry-stream`, `worker-embed`;
- `dcl-v2-console:local`: `console`.

### Before (run now, on live data). Recorded 2026-10-27
```sql
-- B1: the two open entries of page 11 (expect 2 rows, OPEN)
select status, anchor->>'content_sha256', evidence->'crops'->0->>'model_value'
from review_flags where case_key = '8c4cdfdf-8d21-4290-b09e-3d2fddbe6213:11' and anchor ? 'content_sha256';
-- today: OPEN | 990f5941… | Trial 7.1 (warm-up run
--        OPEN | bd38e744… | Sample B-12 (lot 4

-- B2: page 11 nodes; how many carry the entries; the text with and without the bracket
select count(*), count(*) filter (where metadata ? 'handwriting'),
       count(*) filter (where content like '%warm-up run)%'),
       count(*) filter (where content like '%warm-up run%')
from document_nodes where doc_id = '8c4cdfdf-8d21-4290-b09e-3d2fddbe6213'
  and page_no <= 11 and coalesce(page_end, page_no) >= 11;
-- today: 9 | 0 | 0 | 2
```
- **B3, MinIO:** the objects under `dcl-cir/450467c5…c7/A1/v1/pages/11`. Today: `['11.meta.json', '11.txt']`, with no `11.reading.json`.
- **B4, API:** `GET /review/cases/8c4cdfdf-8d21-4290-b09e-3d2fddbe6213%3A11`. Today the response has no `page_reading` key.
- **B5, console:** the case shows 2 cards and no table. A screenshot was taken on 2026-10-27 (the user's screenshot of page 11).

### Pilot re-run
`docker exec dcl-v2-api-1 python -m backend.dispatcher.reindex --route A1 --doc 8c4cdfdf-8d21-4290-b09e-3d2fddbe6213 --doc bdc4580d-c88f-46ee-a0a4-31148419b650`
- Run it with `--dry-run` first; the dry run must list exactly these 2 files.
- **Cost check:** `select capability, count(*), sum(cost_usd) from llm_calls where doc_id in (…) and created_at > <start> group by 1`. Expect `transcribe_page` to be served from the cache (cost 0). Enrichment is re-done only for parents whose text changed.

### After
| Check | Expected |
|---|---|
| A1, MinIO | `11.reading.json` exists, its `doubtful` has 2 entries, and their `key`s are the two above |
| A2, API | `page_reading.page_no == 11`. `[e.label for e in page_reading.entries] == ["Trial Name", "Sample Name"]`. `page_reading.blocks` holds 1 heading and 3 tables. Both entries are `located` with a `cell` |
| A3, console (Chrome DevTools) | **Steps 1–11 below** |
| A4, SQL after Apply | B1 shows `RESOLVED` with `resolution->>'value'` = `Trial 7.1 (warm-up run)` and `Sample B-12 (lot 4` |
| A5, SQL after the rebuild | B2 reads `9 | ≥1 | 2 | 2`: the bracketed value is now in the text, in both `content` and `embed_text` (check `embed_text` with the same filter) |
| A6 | C6 "decisions newer than the last index" = 0 for this document 30 minutes after Apply at the latest |

**A3, step by step:**
1. Navigate to `http://localhost:8601/review?case=8c4cdfdf-8d21-4290-b09e-3d2fddbe6213%3A11` (ignore cache).
2. `take_snapshot`. Expect:
   - region `Page check`;
   - heading `Page 11 as read`;
   - text `2 entries to check · 0 of 2 done`;
   - an image named `Page 11`;
   - a table with a cell `Trial Name`, and next to it a cell named `Unsure entry: Trial Name`.
3. Screenshot `1c_before.png`.
4. `document.activeElement` is the text field labelled `Trial Name`, and its value is `Trial 7.1 (warm-up run`.
5. Click the chip `Trial 7.1 (warm-up run)`. The field now holds that value, and the entry shows `✎ corrected`.
6. Press Enter. Focus moves to the field labelled `Sample Name`, and the status reads `1 of 2 done`.
7. Press Enter (value unchanged). The entry shows `✓ confirmed`, the status reads `2 of 2 done`, and focus is on `Apply page 11`.
8. Click a non-entry cell, for example the `Date` value. An editor opens. Press Esc: the cell is unchanged and no correction draft exists.
9. Click `Apply page 11`. The notice starts `Saved 2 answers for page 11.`
   - HTRCHAR still has open pages 6, 7 and 9, so the notice continues `The file is rebuilt when its last page is checked (3 pages left), or within 30 minutes.`
10. `list_console_messages` (error, warn): empty. Screenshot `1c_after.png`.
11. At 1024 px width: stacked layout, and `document.documentElement.scrollWidth <= innerWidth`.

**Data rule for the live check:** step 5 changes real content. The bracket is the reviewer's own call on this real file, so **ask the user before step 9 on live data.** Without a yes, choose Confirm for both entries (no content change), check A4 with the reader's values, then **Undo** (`Undo last resolution`). Confirm B1 reads OPEN again, and that no `route = 'review'` row is left.

### 10b. Remove the previous duplicate versions, after the live check passes
For the two pilot files only:

```sql
-- assets of these blobs that no node and no flag points at (B5 kind)
select a.asset_id, a.minio_uri from assets a
where a.blob_sha256 in (select blob_sha256 from document_sources where doc_id in ('8c4cdfdf-…','bdc4580d-…'))
  and not exists (select 1 from document_nodes n where n.asset_id = a.asset_id)
  and not exists (select 1 from review_flags f where f.evidence::text like '%' || a.minio_uri || '%');
```
- Also list `pages/*` objects of an older `parser_version` folder under each blob's CIR prefix, if the re-run wrote a new version folder.
- **List, report, then delete** those rows and objects. The same queries must then return 0.
- **Never deleted:** `11.txt`, `11.meta.json`, the page renders (`pages/{sha}/{n}.png`, which the flags point at), raw files.

## 11. Rollback
- Revert the commit. Cases fall back to cards, because `page_reading` is gone from the API.
- Correction rows: `delete from review_flags where route = 'review' and resolution->>'action' in ('set_cell','set_text')`, after listing them. The audit events stay.
- Then rebuild the affected documents, so their nodes lose the corrections.
- `reading.json` files are harmless and may stay.
