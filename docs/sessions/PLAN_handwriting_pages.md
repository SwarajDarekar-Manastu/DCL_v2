# Plan: handwritten pages are read whole; handwriting crops are deleted

Status: **done and deployed 2026-10-27; approved the same day** with all three decisions: flag every doubtful entry, delete the old crop images, and the manual edits in section 7. Section 5 was widened the same day so that skip and junk act on what each flag is about.

## 1. The problem, with evidence

A1 finds handwriting in three ways today. Two of them work. The third, handwriting crops, is the one that fails.

| What reads it | Box comes from | Crops | Review flags | Result |
|---|---|---|---|---|
| Figure and photo reader | Docling, full-resolution page | 672 in 31 files | 1 | good (TP23 tags: "Visible text: 17/04/26, TC-2, TP-23") |
| Table reader | Docling | 243 in 31 files | 0 | good (TP07 p1, TP24 p10 handwritten tables) |
| Whole-page reader (`transcribe_page`) | none: the whole page | – | – | good (TP24 p8 and p9 temperature sheets, read in full) |
| **Handwriting crops** | **triage guess on a 768 px thumbnail** | **87 in 5 files** | **24** | about 5 of 25 crops show handwriting; 8 of 12 search entries say "[HW illegible]" |

The crop step fails for three reasons:

- **Wrong boxes.** The boxes come from the cheapest page-sorting call (Flash-Lite, low detail, 768 px). It invented 11 boxes on the typed Catalyst-3mm page, drew a grid of empty columns on TP07, and put TP24 boxes on black background. On TP24 p12 the call ran away listing boxes and failed the whole file.
- **No "nothing here" answer.** The crop reader cannot say "no handwriting in this crop", so every empty crop becomes an "illegible" flag.
- **Copies.** On pages the whole-page reader or the photo reader had already read (TP24 p6–p9, TP23), the crops add copies and "[HW illegible]" entries.

The crops also miss data. TP07 DE p2 is a phone photo of a filled catalyst table. Docling's OCR read the table as two header cells, its OCR score passed, and so no whole-page read ran. "Greyish Black", 32.306, 36.706 and 6.8 % are in no search entry today.

## 2. The strategy

**A page whose content is a photo or scan of a hand-filled form goes once to the whole-page reader.** That reader reads printed and handwritten text together, keeps tables as tables, and lists the entries it is unsure of. Nothing is cropped for handwriting. Each other kind of handwriting stays with the reader that already handles it.

| Page | Example | Reader |
|---|---|---|
| Scan or photo of a filled form or notes | TP07 sheets, TP24 p6–p12 | whole-page reader (new trigger) |
| Scanned page whose OCR stays low | old scans, Japanese pages | whole-page reader (unchanged) |
| Typed page with photos that contain handwritten tags | TP23 report p34–p51 | photo reader (unchanged) |
| Typed page with a photo of a handwritten table | – | table reader through the figure step (unchanged) |
| Typed page | everything else | Docling (unchanged) |

### Which pages go whole to the reader

A page goes whole to the reader when **triage calls it a handwritten form or notes** (`scanned_form_with_handwriting`, `handwritten_notes`) **and images cover at least 25 % of the page**.

The image check is needed because triage alone is wrong too often. It called three typed pages "handwritten form". All three have almost no image area, while every real case is 35 % or more:

| Page | Text characters | Image cover | Triage says | Really |
|---|---|---|---|---|
| TP07 DE p1–p2, PreHeat p1 | 0 | 0.94 | handwritten form | photo of a filled form |
| TP24 p6–p12 | 83–237 | 0.35 | handwritten form | photo of a filled sheet |
| ECSS-E-ST-35-06C p90 | 75 | 0.57 | handwritten form | picture of a blank form (a harmless read) |
| Thruster Integration Sheet p2 | 644 | 0.01 | handwritten form | **typed** |
| TP23 test plan p1 | 1307 | 0.00 | handwritten form | **typed** |
| Catalyst-3mm p1 | 602 | 0.07 | handwritten form (once) | **typed** |
| TP23 report p36, p41, p51 | 400–900 | 0.31 | photo page | photos with tags (stays with the photo reader) |

The image check also covers a scanner-OCR'd PDF. Its full-page image covers the page, so it is read whole even though it has a text layer.

### Image detail: high

18 test reads, $0.115 in total, of 5 handwritten pages and 3 control pages, with the draft prompt. Every disputed value was checked by eye against the image.

| Setting | Input tokens | TP07 p2 (simple form) | TP24 p7 (13 × 10 handwritten numbers) |
|---|---|---|---|
| low | 1,607 | one word wrong ("New" for "Now") | many digits wrong (23.90 → 20.94, 339.52 → 330.52, 308.35 → 318.35) |
| medium | 1,873 | correct | 3 wrong (2026 → 2020, 283.53 → 289.53, 277.20 → 277.70), **none marked doubtful** |
| high | 2,433 | correct | correct |

High costs about $0.0003 more per page than medium. Medium miscopies digits silently. **Keep high**, which is what `transcribe_page` uses today. A read costs $0.005–0.010 per page, depending on how much is written. That compares with $0.0028 per crop today, and TP24 p7 alone got 21 crops.

### Uncertain entries go to a person

- **One flag per entry.** Each entry the reader lists as doubtful becomes one LOW_CONFIDENCE_EXTRACTION flag. It is SOFT, or HARD when its label matches `critical_field_patterns`.
- **The flag shows the page.** It carries the printed label, the reading and its alternatives, and the **whole page image** instead of a crop.
- **Every listed entry is flagged,** not only those under 0.75 confidence. In the test the reader gave its doubtful entries 0.80–0.90, so the old cut-off would flag none of them. At high detail, 6 entries were listed across 5 pages, and each was a real question: "Now 11.36" or "11.38"; date 2026 or 2024; bed length "17.8 m", where the unit could be m, mm or cm.
- **A person's answer replaces the reading.** "Set value" replaces the reading in the page text, including an "[illegible]".
- **Where the doubts come from (decided 2026-10-27).** The `doubtful` list is the model's own self-report, not a computed probability. A second read compared cell by cell would also catch confident misreads (on TP24 p7 every medium-vs-high difference was an error), but it was not taken: one read at `high` instead, because a second read adds latency and cost.

## 3. What to delete

Line numbers are from `main` at 189d7b8.

| # | Where | What | Why it can go |
|---|---|---|---|
| D1 | [handwriting.py](../../backend/routes/a1_office/handwriting.py) whole file (`transcribe_regions`, `nearest_label`, `label_text`, `page_units`, `region_box`, `render_reading`) | handwriting crop step | replaced by the whole-page reader; the file is rewritten for step A3 |
| D2 | [route.py:60](../../backend/routes/a1_office/route.py#L60), [route.py:308-322](../../backend/routes/a1_office/route.py#L308-L322), handwriting parts of [route.py:323-338](../../backend/routes/a1_office/route.py#L323-L338) | the handwriting stage, its assets, crops, flags and `handwriting_rejected` QA count | as above |
| D3 | [schemas.py:60-75](../../backend/llm_engine/vision/schemas.py#L60-L75) `HandwritingKind`, `HandwritingRegion`; [schemas.py:14-21](../../backend/llm_engine/vision/schemas.py#L14-L21) `Box2D`, `check_box` | triage box types | boxes are no longer asked for; `Box2D` has no other user |
| D4 | [schemas.py:82-83](../../backend/llm_engine/vision/schemas.py#L82-L83), [schemas.py:88](../../backend/llm_engine/vision/schemas.py#L88) `PageTriage.has_handwriting`, `has_tables`, `handwriting_regions` | triage fields | `handwriting_regions` caused the TP24 p12 runaway; `has_tables` is read by nothing; `has_handwriting` was read only by D1 (`has_figures` stays: `combine` uses it) |
| D5 | [schemas.py:97-105](../../backend/llm_engine/vision/schemas.py#L97-L105) `PageTranscription.illegible_regions` | boxes the whole-page reader returns | read by nothing; replaced by `doubtful` (A2) |
| D6 | [schemas.py:108-146](../../backend/llm_engine/vision/schemas.py#L108-L146) `HandwritingReading`, `_raw_states_number` | crop reader's answer, `value_number` | replaced by the smaller `HandwritingDoubt` (A2); `value_number` was stored and never read (numbers come from the text) |
| D7 | [service.py:68](../../backend/llm_engine/vision/service.py#L68), [:81](../../backend/llm_engine/vision/service.py#L81), [:138-140](../../backend/llm_engine/vision/service.py#L138-L140), [:282-297](../../backend/llm_engine/vision/service.py#L282-L297) | `TRANSCRIBE_HANDWRITING` capability, task, method | no caller after D1 |
| D8 | `backend/llm_engine/prompts/vision/transcribe_handwriting.v1.md` | crop reader prompt | capability gone (old versions of live prompts stay, as today) |
| D9 | [triage.py:45-47](../../backend/routes/a1_office/triage.py#L45-L47), [:63](../../backend/routes/a1_office/triage.py#L63), [:120-122](../../backend/routes/a1_office/triage.py#L120-L122) | `PageDecision.handwriting_regions`, `has_handwriting`, `has_tables` and the CIR meta field | follow D4 |
| D10 | [crops.py:88-119](../../backend/routes/a1_office/crops.py#L88-L119) `Quality`, `crop_quality`, `inside_any`; constants [crops.py:21-24](../../backend/routes/a1_office/crops.py#L21-L24) | crop size gate | used only by D1. The corpus has 2 figure crops below the gate, both on TP07 p2, which is read whole after this change, so figures don't need it |
| D11 | [viewer.py:327-353](../../backend/api/viewer.py#L327-L353) `_handwriting_regions`, its call at [viewer.py:401](../../backend/api/viewer.py#L401), `"handwriting"` in `Region.kind` [viewer.py:74](../../backend/api/viewer.py#L74) | viewer boxes around handwriting | the new readings have no box; this only ever drew the crop boxes |
| D12 | [DocumentViewer.svelte:34-38, :93, :169-191](../../frontend/console/src/lib/components/viewer/DocumentViewer.svelte#L169-L191); `--handwriting` colours in [app.css:185-186, :251-252](../../frontend/console/src/app.css#L185); [ImageWithRegions.svelte:17-20](../../frontend/console/src/lib/components/viewer/ImageWithRegions.svelte#L17-L20) | "Handwritten on this page" list and box colour | follows D11 |
| D13 | [overlays.py:107-131](../../backend/indexing/overlays.py#L107-L131) box matching in `_set_value` | finds a reading by its crop box | replaced by key matching (A4) |
| D14 | `transcribe_handwriting` in the FakeVision stubs: [a1_office/conftest.py:33-34](../../backend/tests/unit/routes/a1_office/conftest.py#L33-L34), `d_photos/conftest.py:33-34`, `f_video/conftest.py:33-34` | test stubs | capability gone |
| D15 | handwriting tests in `test_figures_tables_handwriting.py:368-477`; `inside_any` and `crop_quality` tests in `test_crops.py`; `handwriting_regions` in [test_route.py:42](../../backend/tests/unit/routes/a1_office/test_route.py#L42); `transcribe_handwriting` and `HandwritingRegion` cases in `test_vision_service.py` | tests of deleted code | replaced by the tests in step 6 |

`AssetKind.HANDWRITING_CROP` stays in the enum. Removing a Postgres enum value means rebuilding the type, and after step 8 no row uses it.

## 4. What to add or change

| # | Where | Change |
|---|---|---|
| A1 | [preflight.py:37-48](../../backend/routes/a1_office/preflight.py#L37-L48), [:149-161](../../backend/routes/a1_office/preflight.py#L149-L161) | `PageSignals.image_cover`: the share of the page covered by image objects (pdfium `get_bounds`, clipped to the page). Pre-flight already walks these objects to count them. |
| A2 | [schemas.py](../../backend/llm_engine/vision/schemas.py) | `HandwritingDoubt {field_label, value_raw, unit, alternatives, confidence, illegible}`. The illegible rule stays: no value, confidence ≤ 0.5. `PageTranscription` gets `doubtful: list[HandwritingDoubt]` in place of `illegible_regions`. |
| A3 | new prompt `transcribe_page.v3.md`; [service.py:132-137](../../backend/llm_engine/vision/service.py#L132-L137) | v3 is the prompt from the test (appendix): printed and handwritten text, photo background left out, handwritten tables as HTML tables, `~~old~~ new` for corrections, `[illegible]`, the `doubtful` list. Settings stay Flash, high. New `triage_page.v2.md` without the box list and the two unused fields; its output cap drops from 12,288 to 1,024 (a complete reply is about 100 tokens; the cap only stops a runaway). |
| A4 | [triage.py](../../backend/routes/a1_office/triage.py) | `HANDWRITTEN_TYPES = {scanned_form_with_handwriting, handwritten_notes}`, `PAPER_IMAGE_MIN_COVER = 0.25` with the evidence above, and `PageDecision.read_whole: bool` = handwritten type and `image_cover ≥ 0.25`. It is written to `pages/{n}.meta.json`. |
| A5 | [route.py:234-283](../../backend/routes/a1_office/route.py#L234-L283) | The existing whole-page loop runs over `still_low ∪ read_whole` pages, not `still_low` alone. Nothing else in the loop changes: a refused call keeps the OCR text and flags the page, as today. The page-render loop ([route.py:357-370](../../backend/routes/a1_office/route.py#L357-L370)) moves before it, so each flag can point at its page image. |
| A6 | `handwriting.py` (rewritten, about 60 lines) | `doubt_flags(page_no, doubts, page_uri, critical)`: one flag per doubtful entry. Anchor `FlagAnchor(page, content_sha256=hash(label))`, the same pattern A2 uses for table flags. Evidence is the page image, label, reading and alternatives; the suggestion is `SetValue`. `annotate(nodes, page_no, doubts)`: each entry goes into `metadata.handwriting` of the page node that holds its text, with the same key. |
| A7 | [overlays.py:107](../../backend/indexing/overlays.py#L107) `_set_value` | Finds the reading by `key == anchor.content_sha256`. Replaces the reading, or `[illegible]`, in the node text with the person's value. Today an illegible entry keeps "[HW illegible]" even after a person types the value. |
| A8 | [route.py:1-14](../../backend/routes/a1_office/route.py#L1-L14), [crops.py:1-12](../../backend/routes/a1_office/crops.py#L1-L12), [triage.py:1-11](../../backend/routes/a1_office/triage.py#L1-L11) docstrings | Say what the code does now. The route docstring still says crops are made at 300 dpi; the code uses 200. |

## 5. Review screen: skip and junk act on what the flag is about

### What the screen does today

Checked in the console on 2026-10-27:

| Case | What its flags are about | Footer buttons | What they do |
|---|---|---|---|
| Telemetry `Test_01_0` (HARD, 8 channels) | the unit of each channel | Skip file | quarantine the whole file |
| `Injector 10 · Steady State Values` | the units of 6 columns on one sheet | Skip file | quarantine the whole workbook |
| TP23 report p44 | 2 crops | Mark junk, Skip file | quarantine the whole report and its OneDrive item |

There are three faults:

- **The buttons ignore the case.** The footer buttons ([CaseView.svelte:212-213](../../frontend/console/src/lib/components/review/CaseView.svelte#L212-L213), [ChannelMapView.svelte:204, :322](../../frontend/console/src/lib/components/review/ChannelMapView.svelte#L204)) call `reject_case` ([cases.py:785](../../backend/review/cases.py#L785)), which acts on the whole file whatever the case holds. The server never checks that a flag allows it.
- **Two paths that disagree.** Skip and junk chosen as a flag's answer through resolve ([cases.py:735](../../backend/review/cases.py#L735)) only record the answer and change nothing.
- **Decisions don't reach search.** A decision on a SOFT flag reaches search only when the file is next rebuilt; resolve never rebuilds it (undo does). Of the 9 value, table and unit decisions people made, 8 never reached search.

### The rule

Each flag has a subject. The server works it out in one function, `flag_subject`, in [contract.py](../../backend/dispatcher/contract.py) next to `ALLOWED_ACTIONS`, and sends it with the flag.

| Subject | Flags | Skip | Junk |
|---|---|---|---|
| **file** | PARSE_FAILURE, UNSUPPORTED_FORMAT, HELD_LARGE_FILE, SCHEMA_UNKNOWN | "Skip whole file": the file leaves search; its OneDrive item is kept | "Junk whole file": the same, and the OneDrive item is quarantined so it is never processed again |
| **page** | LOW_CONFIDENCE_EXTRACTION anchored to a page only (the page could not be read well) | "Keep page as read" (`ignore`) | "Junk page N": that page's text leaves search; the rest of the file stays |
| **object** | LOW_CONFIDENCE_EXTRACTION on a figure or table (page + box) | "Keep as read" (`ignore`); for a table, "Choose table version" | "Junk this image" or "Junk this table": that one image or table leaves search |
| **value** | units (channel, column, line), conflicts, handwritten entries, the formula cap | not offered: the flag's own actions (set unit, pick a source, type the value, accept both, ignore) | not offered |

Only a flag whose subject is the file can touch the file.

### Changes

| # | Where | Change |
|---|---|---|
| R1 | [contract.py:352-362](../../backend/dispatcher/contract.py#L352-L362) | `flag_subject(flag_type, anchor, evidence)` and `allowed_actions(flag_type, anchor, evidence)`, which narrows `ALLOWED_ACTIONS` by subject. LOW_CONFIDENCE_EXTRACTION gains `ignore` and `mark_junk`: a page or figure gets `{ignore, mark_junk}`, a table `{choose_table, mark_junk}`, a handwritten entry `{set_value}`, and the formula cap `{ignore}`. |
| R2 | [api_models.py:136-181](../../backend/review/api_models.py#L136-L181) | `allowed_actions_for` and `check_actions` use R1 per flag. `FlagView` carries `subject`. |
| R3 | [cases.py:693](../../backend/review/cases.py#L693) `resolve_case` | Skip or junk on a **file** flag runs the whole-file step that `reject_case` holds today: the file's open flags close as REJECTED_FILE, the document is QUARANTINED, and junk also quarantines the OneDrive items. Every other decision on a committed file (ACTIVE or ACTIVE_WITH_SOFT_FLAGS) sets it PROCESSING and rebuilds it, as undo does, so the decision reaches search at once. That includes junking a page or an object, and also set value, table choice, unit, keep and ignore. The rebuild is skipped when the file is already PROCESSING; that running build reads the decision when it commits. |
| R4 | [overlays.py:154](../../backend/indexing/overlays.py#L154) `overlay_plan` | `mark_junk` on a page or object flag drops the nodes it names, with their child nodes, numbers and entity mentions: every node of the page, or the node whose box matches. Undo brings them back, because undo already rebuilds. |
| R5 | `reject_case` ([cases.py:785](../../backend/review/cases.py#L785)), `POST /cases/{key}/reject` ([review.py:140](../../backend/api/review.py#L140)), `RejectRequest` ([api_models.py:329](../../backend/review/api_models.py#L329)), the console's `rejectCase`, and the footer and channel-map buttons | **Deleted.** Every skip and junk is a decision on one flag, made through resolve, so there is one path. |
| R6 | [resolution.ts](../../frontend/console/src/lib/components/review/resolution.ts) `actionLabel` | Labels follow the subject: "Skip whole file", "Junk whole file", "Junk page 8", "Junk this image", "Junk this table", "Keep as read". The console lists only the server's actions, so "Choose table version" no longer appears on a handwritten entry. |
| R7 | [CaseView.svelte](../../frontend/console/src/lib/components/review/CaseView.svelte) `apply` | A whole-file choice asks first, naming the file ("Junk whole file *Test Plan 23 Analysis Report.docx*? It leaves search and is not processed again. Undo can bring it back."). |
| R8 | [flag_guide.ts:44-50](../../frontend/console/src/lib/components/review/flag_guide.ts#L44-L50) | Guide text per subject: "Find the label on the page and type the value", "Junk this image if it shows nothing useful", and so on. |

## 6. Tests (behaviour, literal expected values)

- **Typed page left alone:** a page triage calls `scanned_form_with_handwriting` with image cover 0.01 is not read whole; the calls are `["triage_page"]` only.
- **Photo of a form read whole:** the same page type with cover 0.94 and a good OCR score is read whole. Its nodes come from the reader, and Docling's figure and table nodes for that page are gone.
- **One flag per doubt:** two doubtful entries give two SOFT flags on the same page. Each has the page image URI and the label, and a critical label gives HARD.
- **Set value rewrites the text:** on a node reading "6.8%", `set_value` for that entry's key gives the person's value in the text, and `[illegible]` is replaced too.
- **Triage stays small:** the triage schema has no box field.
- **Pre-flight measures cover:** `image_cover` is 0 for the typed fixture and above 0.9 for `rotated_scan`.
- **Flag subjects:** `flag_subject` gives `file` for PARSE_FAILURE, `page` for a page-only LOW_CONFIDENCE_EXTRACTION, `object` for one with a box, and `value` for a channel unit or a handwritten entry. Each subject's `allowed_actions` are the literal sets in R1.
- **Junking one image:** `mark_junk` on a figure flag of a 3-page document keeps the document ACTIVE, schedules one rebuild, and the overlay drops only that figure node and its numbers. The other page nodes are untouched.
- **Junking a file:** `mark_junk` on a PARSE_FAILURE flag quarantines the document and its OneDrive item and closes the file's other open flags as REJECTED_FILE.
- **Value flags can't touch the file:** `mark_junk` on a UNIT_AMBIGUITY channel flag is refused with 422.
- **A decision reaches search:** `set_fact_unit` on a SOFT sheet-column flag of an ACTIVE document sets it PROCESSING and starts one rebuild.
- **Console:** a handwritten entry offers only "Type the value", a figure offers "Keep as read" and "Junk this image", and a file flag offers "Skip whole file" and "Junk whole file". There are no footer skip or junk buttons.

Then ruff (own files only), pytest unit, `pnpm check` and `pnpm test`.

## 7. Manual changes (need sign-off)

`docs/architecture/03_phase2_processing_routes.md`:

- **Triage row (:136):** no `handwriting_regions`.
- **Whole-page reader rows (:137, :149):** `transcribe_page` gets the second trigger and returns `doubtful` instead of boxes. The "M5 calibration may lower the handwriting default" line becomes the result above: high stays.
- **Crop reader row (:138):** `transcribe_handwriting` is deleted.
- **Page-type table (:204-205):** `scanned_form_with_handwriting` and `handwritten_notes` become "read whole when images cover ≥ 25 % of the page". The 3×3 tile reading was never built and goes.
- **Flow diagram (:167-173):** "A1.7 Handwriting regions" becomes "A1.7 Handwritten pages".
- **§A1.7 and §A1.8 (:249-260):** rewritten to the strategy in section 2. Also out:
  - the "three region sources" (only triage boxes were ever built);
  - "OCR words < 0.80 clustered";
  - the checkbox call (never built).
- **CIR list (:117):** `handwriting/{id}.json` goes; it was never written.
- **Crop resolution (:218):** says 300 dpi, but the code renders at 200.

`.wiki/backend/vision-service.md:29`: the capability list loses `transcribe_handwriting`.

## 8. Clean-up and re-runs (one heavy job at a time)

1. Deploy the workers (cpu-parse, io-light) and the console.
2. **Pilot, one file at a time, with a check after each:**
   - **TP24 HTRCHAR:** it must stop failing, and pages 6–12 must be read whole.
   - **TP07 DE Integration Sheet:** the p2 values must be in search.
   - **Thruster Integration Sheet:** must not be read whole, because its typed p2 has cover 0.01.
   - **TP23 Analysis Report:** must have no handwriting crops, with the photo tags still in the photo readings.

   Check each one's search text against the images, and its flags in the review screen.
3. **The rest:**
   - TP07 PreHeat Sheet, Catalyst-3mm, TP23 test plan;
   - ECSS-E-ST-35-06C (p90 is read whole);
   - ECSS-Q-ST-70C (p81 has cover 0.01 and stays with Docling).
4. **Remove the old crops.** Delete the 87 `handwriting_crop` asset rows; none is used by a search entry. Then delete their 87 images under `dcl-assets/crops/`. Only the closed old review flags point at those images, so their history loses the picture. Also delete the orphaned rows of the 2 tiny TP07 figure crops.
5. Expected cost:
   - about 14 whole-page reads at $0.005–0.010;
   - the re-runs' other calls, mostly cache hits.

   Under $0.50 in total.

## 9. Found on the way, not fixed here

- **A re-run never deletes the asset rows an older version made.** The commit upserts by image path and nothing removes what the new version no longer produces ([commit.py:144-165](../../backend/indexing/commit.py#L144-L165)). This is how 87 handwriting crops piled up. Nodes are replaced on every commit, but assets aren't. Fixing it means deciding what happens to images that old review flags show, so it is its own change.
- **The EasyOCR retry still runs on pages that will be read whole.** That is CPU time only, no cost.
- **The M5 acceptance check still lists `handwriting_crop`** ([m5_state.py:24](../../backend/tests/acceptance/m5_state.py#L24), M5.md row 1). It's harmless with no rows; S5 can drop it.

## Results (2026-10-27)

Deployed: api, beat, io-light, embed and cpu-parse from the new images at 13:03 and 13:16, and the console at 14:00. worker-media is stopped; its image still holds the old vision code and must be rebuilt before it is started.

| File | Before | After |
|---|---|---|
| TP24 HTRCHAR | FAILED (the triage box list ran away on p12) | ACTIVE_WITH_SOFT_FLAGS: p6–p12 read whole, 9 doubt flags with the page image, 12 triage replies of at most 55 tokens |
| TP07 DE Integration Sheet | the p2 catalyst table missing from search; "[HW …]" entries | ACTIVE: "Greyish Black", 32.306, 36.706 and 6.8 % in search; no "[HW …]" |
| Thruster Integration Sheet | – | p2 (typed, cover 0.01) stayed with Docling, as intended |
| TP23 Analysis Report | 8 open crop flags | ACTIVE, no open flags; photo tags still read (32 nodes carry the tag dates) |
| TP07 PreHeat Sheet | 1 crop | read whole; 2 doubt flags |
| Catalyst-3mm | 11 crops, 5 flags | typed page left with Docling; flags closed |

- **Not re-run:** the TP23 test plan and both ECSS standards. They never had a handwriting crop, so a re-run would change nothing.
- **Cleanup:** 87 `handwriting_crop` rows and images, plus TP07's 2 orphaned photo crops, were deleted. None was cited by a node or an open flag; 25 closed flags lose their picture.
- **Corpus now:** 0 handwriting crops, 0 "[HW …]" entries, 0 open crop flags.
- **Model spend:** $0.70 for the pilot and the batch. Most of it went to TP23's photo re-reads, which missed the cache, and the outage retry. The page reads cost $0.085.
- **Review screen, checked in the browser:** a handwritten entry offers only "Type the value" and shows the page image. The telemetry and sheet cases have no skip or junk.

Follow-ups found on the way:
- **Photo cache miss.** TP23's photo readings missed the vision cache: 54 calls, $0.20.
- **Chart runaway.** A `digitize_plot` call ran away to an error ($0.095); this is the known plot-cap item.
- **Needless OCR on typed pages.** Triage still calls some typed pages forms, which makes Docling run OCR on them. `combine` could use the image cover to bound the page type.
- **Stale assets.** The commit never removes asset rows an older version made (section 9).
- **M5 check.** It still lists `handwriting_crop`.

## Appendix: the tested draft of `transcribe_page.v3`

```text
You transcribe one full page image of an engineering document into Markdown. The page may be in any language and any script. It may be a typed page, a scan, or a phone photo of paper, and it may carry handwriting: values written into a printed form or table, corrections, notes. Your transcription becomes the page text.

Rules:
- Transcribe exactly what is on the page, printed and handwritten, in the original language and script. Do not translate, summarize, correct or complete anything.
- When the page is a photo of paper, transcribe only the paper; leave out the desk, hands and background.
- Keep the reading order. Use Markdown headings for headings, lists for lists and HTML tables (with colspan and rowspan) for tables. A form or table filled in by hand is a table too: each handwritten entry goes in its own cell.
- Copy numbers and units character for character, including decimal commas and footnote marks. A handwritten correction is written ~~old~~ new.
- Never guess a character. Write [illegible] where you cannot read an entry.
- doubtful: each handwritten entry you are not sure of, and each [illegible] one, in reading order. field_label is the printed label of the field, or the row and column headers of the table cell. value_raw is the entry exactly as you wrote it in the markdown, or null when illegible. alternatives are the other readings you considered. Leave doubtful empty when you read every entry with certainty.
- Running headers, running footers, page numbers and reference codes printed in the page margins do not go into markdown. Copy each such line exactly as printed into furniture, top of the page first, including lines that seem unrelated to the page content.
- language: the BCP-47 tag of the main language.
- confidence: from 0 to 1, how sure you are that the transcription is exact. Lower it for every illegible or doubtful entry.
--- user ---
Context: $context
Language hint from triage: $language_hint
Transcribe this page.
```
