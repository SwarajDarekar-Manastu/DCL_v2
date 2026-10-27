# UX review of the Review area (2026-10-27)

Written by a UX-engineer agent after a CTO-agent briefing; screenshots under the session scratchpad `ux/review/`.

## 1. Verdict

The plan needs changes before sign-off. Its principle ("the answer happens where the evidence is") and diagnosis are right. I reproduced the plan's W2–W8 findings independently. Its backlog ordering and three load-bearing choices are wrong.

**Keep:**
- The principle.
- Page-by-page checking.
- Grouping the queue by file.
- Open flags first, with decided ones folded.
- The registry plus its enumeration test.
- Server-owned actions.

**Change:**
1. Make doubtful entries the unit of work, with the whole page as a secondary view.
2. Store corrections per entry, anchored to the entry. Do not store a whole-page `correct_page {text}`.
3. Resolve the contradiction between "unchanged: one Apply per case" (§2) and "one Apply per file" (§5).
4. A preselected model reading must not count as an approval, because it is stored as `human`.
5. Move the cheap global fixes and the unit-flow correctness ahead of the backend rework. About 186 of the ~202 decisions people have made are units; handwriting is 11 flags, all open.
6. Add what is missing: keyboard and focus handling, persisted drafts, a focus mode for width, grouping by question, and a small benchmark with real reviewers.

## 2. Walkthrough findings

Screenshot folder `D` = `/tmp/claude-1001/-home-ai-Desktop-Swaraj--dcl-v2/7ea4b5a5-2aab-4e0c-90fd-69ede2ac1d39/scratchpad/ux/review`

The live queue holds 10 cases and 21 flags, not the 6 and 17 in the brief. It has 4 extra open CONFLICT cases. I read three of them: Test_01_0, Test_01_priming_i_0 and Test_01_purging_0 are the same "run label renamed at commit" collision (`TP07_T01` renamed to `_2`, `_3` and `_4`). The fourth, Temperature_1, is a different check.

| # | Screen | What happened | Heuristic | Sev. | Screenshot |
|---|---|---|---|---|---|
| 1 | Queue | Rows say "CONFLICT (1)" or "LOW CONF (2)", never the question. TP24 appears four times, told apart only by "· 6 / 7 / 9 / 11". The flag-type filter lists raw enum names. Filters take about 30% of the height, about 50% with "More filters" open. | Information scent; match with the real world | major | `D/r01_queue.png`, `D/r25_more_filters.png` |
| 2 | Queue | The header "0 HARD 21 SOFT" ignores filters. An empty filter result says "No cases match" with no "Clear" button, while the right pane still says "Select a case". | System status | minor | `D/r28_empty_queue.png` |
| 3 | Case top (PreHeat p1) | The first screen is a RESOLVED table card with OCR garbage. The open questions start about 1,150 px down. | Minimalist design; efficiency | major | `D/r02_preheat_top.png` |
| 4 | Decided telemetry files | Test_01_0 is 6,400 px tall, Test_01_priming_i_0 6,300 px and Temperature_1 8,200 px. The one open CONFLICT is last, after 8 raw-JSON cards. The "decided" row hides the 8 decisions. | Recognition over recall | blocker | `D/r16_test01_case.png`, `D/r17_test01_conflict.png` |
| 5 | Handwritten card | The "crop" is a 110 px thumbnail of the whole page, identical for both flags, with no marker of where the entry sits. The reading cannot be checked at that size. | Visibility; recognition | blocker | `D/r03_preheat_open_flags.png`, `D/r09_tp24p9_top.png` |
| 6 | Zoom | The zoom shows the whole page at 1240×1755 inside a 900 px viewport with overflow visible, so it cannot scroll. The lower ~855 px is unreachable: "Notes bottom right" (p9) and "Notes below table" (p6) cannot be inspected. Escape does nothing because focus stays on the trigger button. | User control; error prevention | blocker | `D/r10_tp24p9_zoom.png`, `D/r04_zoom.png` |
| 7 | Viewer round trip | "Open in viewer" opens in the same tab. Coming back clears the "Type the value" draft and resets scroll. The viewer has no link back and no entry box. The breadcrumb shows a hash. The image is clear (`D/r07_viewer.png`) but the notes are tiny (`D/r11_tp24p9_viewer_bottom.png`). | User control; recognition | major | `D/r11_tp24p9_viewer_bottom.png` |
| 8 | Answer form | The dropdown has one real option, so it costs two interactions before typing. The form shows a "Unit" field for text. It is prefilled with the model's guess and Apply is already enabled. One click approves an unchecked reading as `human`. | Error prevention; efficiency | major | `D/r05_type_value_form.png` |
| 9 | "?" guide on handwriting | It offers "Choose table A/B", "Keep as read" and "Junk" (only "Type the value" exists). It says "its label is on the page". | Help; match | minor | `D/r06_guide_lowconf.png` |
| 10 | Reading fidelity | The sheet says "discountinued", the reading says "discontinued" (85%), and the alternatives omit the written spelling. "minets" is read at 95%. One reading contains markup: `Test-~~2~~<sup>1.2</sup>- Empty chamber Baseline` (p7). Confidence shows as 0.85 in one place and 85% in another. | Consistency; system status | major | `D/r12_tp24p6.png` |
| 11 | Keyboard | After Enter on a queue row, focus falls to `BODY`. The first Resolution select on p9 is tab stop 38 of 45. | Flexibility and efficiency | major | not captured |
| 12 | Channel map, Injector 10 | "First values" is empty on all rows. "suggested · confidence 40%" sits under empty pickers. Mass Throughput is preselected "g · 50%" while the label says 40% (two numbers). A throughput is a rate, and the picker also offers g/s and kg/s. | Consistency; recognition | major | `D/r13_injector_top.png` |
| 13 | Channel-map gate | "Preview all" returns "no converted values" on both picked rows, yet it enables "Apply all and resume". The file was never halted. | System status; error prevention | major | `D/r14_injector_preview.png` |
| 14 | Per-flag fallback | 10 cards, 4,790 px. Each repeats the header row and the stats. There are no sparklines. | Minimalist design | minor | `D/r15_injector_perflag.png` |
| 15 | Decided units | The review side shows raw JSON. The Audit page shows the same 8 channels on one screen with approver, time and "proposed by a rule". | Recognition | major | `D/r19_audit_case.png` |
| 16 | Run-label conflict | The guide says "Two sources state different values". The case is a system rename. Three files carry the identical question, each decided separately. | Match with the real world | major | `D/r18_conflict_guide.png` |
| 17 | Rules | The wizard fills the first 580 px; saved rules start at 618 px. 12 of 14 rows are `channel_proposal` for one folder and look identical until the JSON Body is opened. Simulate ("Reaches 6 files…") is good. "Stop proposing" sits beside it at equal weight. | Recognition; error prevention | minor | `D/r23_rules_list.png`, `D/r24_rules_simulate.png` |
| 18 | Audit | The raw log shows UUIDs ("undo / flag / ea7aef6b…"). "Find a file" and the per-file page work well. | Recognition | minor | `D/r20_audit.png`, `D/r21_audit_find.png` |
| 19 | 1280×800 | Nav (240) plus queue (366) leave a case pane of about 670 px, and the header buttons wrap. A side-by-side image and grid gets about 330 px each. | Flexibility | major | `D/r26_1280_tp24p9.png` |
| 20 | Home and p11 | The home page says "Resolve, reject, undo" and shows no counts. A decided p11 card shows a broken "Crop 1" image reading "no reading · 0%". | Consistency | minor | `D/r29_home.png`, `D/r27_tp24p11.png` |

My estimate is 10–12 actions per handwritten entry (scroll, zoom, failed Esc, click out, viewer, find, back, dropdown, edit). That makes over 100 actions for the 11 entries, with a lost draft on each viewer trip.

## 3. Plan review

| Plan element | Verdict | Why / what instead |
|---|---|---|
| Principle | Keep | Direct, evidence-adjacent answering fixes #5, #6 and #7. |
| Part 4, suggestion preselected | Change | Preselect only where other evidence is on screen (units). For readings, show "unconfirmed" and require an explicit confirm, because `human` provenance must mean a person looked. |
| Profile registry (R1) and test | Keep | The enumeration test is the best idea in the plan. |
| 13 profiles | Change | Use about five answer shapes: confirm/edit reading, choose-one, unit table, mapper and acknowledge. Q7–Q9 and Q11–Q13 are one component with different copy. |
| Q1/Q2 "as today" | Change | Q2 is not fine as is. The brief's code trace says `set_unit` on a sheet column changes no data, and the preview already says "no converted values" (#13). The Apply may be a no-op. Route sheet columns to `set_fact_unit`, or give `set_unit` an overlay. Also fix #12. |
| Q3 number in sentence | Keep | Small, and it fixes a bug. |
| Q4 page check | Change | Keep the image-beside-reading idea, amber cells, chips and boxes. Add: an entry-first list, per-entry corrections, a focus mode, keyboard, "unreadable", "partly readable" and persisted drafts. Detail in §4. |
| R7/R8 `correct_page {text}`, delete `set_value` | Change | A whole-page text override freezes the page. A later re-read cannot improve any cell on it, and a stray keystroke in an editable grid changes data silently. It also bypasses "decisions anchored and replayed" (brief §4). Store corrections anchored to the entry or cell. Then R6–R10 shrink to boxes, verbatim transcription and tables-as-nodes. |
| Q5 table check | Keep | When reading A is garbage (32 cells differ), default to B and show only the differing cells. |
| Q6 image check | Keep, defer | Those flags are auto-resolved today and no person has decided one. |
| Q7–Q9 choice cards | Keep, extend | Add bulk by question (3 of 4 open conflicts are one collision) and fix the guide copy (#16). |
| Q10–Q13 | Keep, defer | No volume yet. |
| R4, open first and decided folded | Keep, do first | Render the folded part as the Audit table plus sentences, not cards. Add "N open" in the header. |
| R5, help of offered choices | Keep | Fixes #9. |
| Group queue by file | Keep, extend | Also group by question and show the question sentence (#1). |
| One Apply per file | Change | It contradicts §2. A new batch endpoint would need batch-level undo. Use per-page Apply (safe commit, visible progress) plus a deferred-rebuild flag so the file rebuilds once on the last page. Bulk across files is k independent POSTs, each undoable. |
| Phase 0 disk | Keep | Blocking infrastructure. |
| Phase 1 bundle | Change | Split it. 1a: cheap global fixes. 1b: page-check UI on existing data. 1c: boxes, v4 transcription and the W9 chunker fix. Ship the chunker fix as its own ticket now, since it affects search quality regardless of UX. |
| Phase 3, channel map last | Change | Move the correctness fixes into 1a. Units are about 90% of decisions. |
| Home counts, "reject" wording | Keep | Trivial. |
| Missing | Missing | Keyboard and focus flow; persisted drafts; a live refresh (the brief says no `case` events are published); a rebuild-status line after Apply; the Rules page clutter; viewer entry boxes and a "back to case" link; a usability benchmark. |

## 4. Recommended design

### Flow 1: Handwritten page check

Entering it collapses the nav and queue to a rail. A "Focus" toggle makes this reversible.

```
 TP24 HTRCHAR · page 9 of 12   pages with entries: 6 7 [9] 11    entry 1 of 3   [Esc] queue
┌─ PAGE (sticky, pan/zoom) ────────────┬─ TO CHECK · 3 ─────────────────────────────────┐
│  ┌──────────────────────────┐        │ 1 Notes, bottom right            ○ unconfirmed │
│  │ photo                    │        │  ┌ loupe (box +30%, 3x) ───────┐               │
│  │        ┌─────────┐◄─ box  │        │  │ handwriting crop            │               │
│  │        │ notes   │        │        │  └─────────────────────────────┘               │
│  └────────┴─────────┴────────┘        │  [5% pt/Al2O3 Ce-032 -> 25.418 gm        ]     │
│  [-][+][Fit]   no box? row/col band   │  also: [Ce.032] [Ce-032]  (differing chars bold)│
│                                       │  [Enter ✓ matches] [u unreadable] [p partly]   │
│                                       │ 2 Test name …   3 Actual time, 40 min …        │
│                                       │ ▸ Whole page as read (tables as grids)         │
├───────────────────────────────────────┴────────────────────────────────────────────────┤
│ 1 of 3 checked   [Apply page 9 → page 11]      j/k entry · Enter ✓ · type to edit · ⌘↵ apply │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Layout:** the image is sticky while the right side scrolls. At 1280 wide it takes 50%.
- **Order:** entries are listed in page order, not by confidence. The numbers mislead (#10), so show bands ("unsure"), not percentages.
- **Entry label:** it carries row and column ("Test 1 · Temperature [C]").
- **Answers:** Enter confirms. Typing replaces the reading. `u` marks the entry unreadable. `p` marks it partly readable, stored with a truncation marker. A chip fills the field. Alternatives show the characters that differ.
- **Keyboard and focus:** focus lands in the first entry's input. After Apply it moves to the first entry of the next page. Tab goes input, chips, confirm, next entry. Esc closes zoom or leaves focus mode.
- **Apply:** enabled only when every entry is confirmed, edited or unreadable. The footer shows "n of m checked". After Apply, a toast offers "Undo (30 days)".
- **Whole-page tab:** it exists to catch confident errors. Empty rows are collapsed (PreHeat has 2 of 15 filled). Cells open for edit only on click.
- **Drafts:** persisted, so a trip to the viewer or a reload loses nothing.
- **Empty and error states:**
  - No box for an entry: show the whole page with the row and column band, plus "Position not found".
  - Image fails to load: show a retry and a text-only mode that blocks Apply ("cannot verify, leave open").
  - Apply fails: keep drafts and show an inline error.
  - Last page done: "File complete, 9 confirmed, 2 edited", with a link to the next job.

### Flow 2: Queue triage

```
 Queue · 10 files · 21 questions                                     [Rules]
 [All 21] [Handwriting 11] [Units 6] [Run labels 3] [Checks 1]    sort: oldest ▾   ⌄ more
 ─────────────────────────────────────────────────────────────────────────────────────
 ▣ TP24 heater test               Handwriting · 9 entries · pages 6 7 9 11   1h   ▸ Start
 ▣ TP07 PreHeat sheet             Handwriting · 2 entries · page 1           3d
 ▣ Injector 10 · Steady State     Units · 6 columns without a unit  ✨ ready  5d
 ▣ Run label already used · 3 files   Test_01_0 / _priming_i_0 / _purging_0   5d
     same question on each → decide once, review the 3 source pairs below
```

- **Tabs:** they replace the enum dropdown, carry counts and respect filters. The header reads "showing 3 of 10".
- **Rows:** each row is a job with a question sentence, not a flag type.
- **Repeated conflicts:** one bulk screen lists each A/B pair. Apply sends one POST per case.
- **Filters:** saved filters and "More filters" move to a secondary menu, since 10 cases do not need them.
- **After Apply:** the next job opens automatically.
- **Empty queue:** "Nothing waiting. Last decision 2 h ago." With filters active it shows "Clear filters".

### Flow 3: Unit decisions (channel map, about 90% of decisions)

```
 Injector 10 · Steady State Values — 6 columns without a unit (file stays searchable)
 Column          Values (first 5 · range)       Siblings say   Unit
 Chamber PT 1    1.13 1.2 1.4 … 2.78  ▁▂▃▅▇    —              [ choose ▾ ]  suggest: bar (name "PT")
 Mass Throughput 1280 … 2064          ▇▇▆▅▅     g/s ×3         [ g/s ▾ ]    ← needs a person
 Chamber PT 2q   0 … 0 (constant)      ───       —              [ No unit needed ]
 Also propose to: (•) none ( ) other files in folder (4 · preview)
 [Save 2 units · 4 stay open]
```

- **Evidence:** show real first values, the sparkline and the sibling-file units. Per-flag cards already carry the sibling units.
- **Suggestions:** show one confidence, as a suggestion label beside the picker. Preselect only above a threshold, and never preselect a quantity that does not fit.
- **Gate:** drop "Preview all" for columns whose preview is empty. Say "labels only, nothing converts" instead.
- **Button:** use "Save n units", not "Apply all and resume", on a never-halted file.
- **Decided state:** reuse the Audit table.

## 5. Top 5 priorities

1. **Global fixes (phase 1a).** Open flags first, with decided ones folded into words. Fix the zoom (scroll, Esc, focus). Persist drafts. Move focus into the case after Enter. Say "Apply" unless the file is paused. This removes 5–8 screens of scrolling and the lost work for every flag kind.
2. **Entry-first page check with real crops and a loupe**, built on the existing flags, with boxes added when v4 ships. This should cut about 100 actions to about 30 for the 11 entries, and every answer is actually verified.
3. **Make the unit flows trustworthy.** Confirm what Q2's `set_unit` does on a sheet column. Fix the empty "First values", the stale suggestion labels, the empty-preview gate and the preselected "g". This protects the highest-volume decisions.
4. **Queue by question and file**, with tabs, question sentences and bulk for the three identical run-label conflicts. Ten rows become about four jobs, and the three collisions get one decision.
5. **Backend, in this order:** the chunker fix (W9), then verbatim transcription (v4) and boxes. Then decide the correction storage (per entry, not per page text), and add per-page Apply with a deferred rebuild. Run a 3-reviewer benchmark on the 11 entries against known answers, measuring time per entry and error rate.

## 6. Could not verify

- **Any write path.** I could not run Apply, Undo, bulk behaviour, rebuild time, whether four sequential rebuilds of TP24 would collide, or whether `set_unit` on a sheet column really changes no data. These rest on the brief's code trace.
- **Box accuracy.** The plan says "Flash places them well", but I saw no box output. The two photographed pages I opened are rotated and perspective-distorted, so box quality there is a risk.
- **The Stop proposing confirm.** I did not click it.
- **Tab count.** The 38-stop figure counts focusable elements in DOM order on p9, not a real Tab sequence.
- **The Temperature_1 conflict.** It is a different question (a t0 alignment check). I did not read its guide.
- **Light theme and narrow viewports.** Only dark theme at 1440×900 and 1280×800.
- **Reviewer population.** I have no data on how reviewers actually work. The 10–12 actions per entry is my own walk.