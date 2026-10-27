# Plan: review wiring and review screens (2026-10-27)

**Scope, as agreed:**
1. Fix the wiring a review decision depends on, so a decision reliably reaches search.
2. Build the review screen each flag type needs.

Everything else the route audit found is parked at the end, for a later decision. This adds to [PLAN_review_by_question.md](PLAN_review_by_question.md); its steps 1b, 1c and phase 2 are the screens below.

**How every item is checked:**
- Record the live data that shows the fault (before).
- Make the change and deploy it to the running containers. No separate test containers.
- Show the same data is now right (after).
- Check screens in Chrome DevTools.
- Then delete the old duplicate rows and objects the re-run left.

Details: [specs/VERIFY.md](specs/VERIFY.md).

---

## Part 1. Wiring the review depends on

| # | What is broken today (verified on code and live data) | Fix, and where | Live check: before → after |
|---|---|---|---|
| R1 | **Decisions are applied too late.** They run in `commit` ([commit.py:253](../../backend/indexing/commit.py#L253)) after the search text and vectors were built ([index_document.py:340](../../backend/indexing/index_document.py#L340)). By then the chunker has dropped the handwriting entries ([chunker.py:262](../../backend/indexing/chunker.py#L262)). So a typed handwriting value never applies, and a chosen table B is stored while search still sees table A | Apply decisions to the route's output **before** chunking: in the indexer wrapper ([commit.py:525](../../backend/indexing/commit.py#L525)) with the rules in [overlays.py](../../backend/indexing/overlays.py). Remove the late call | ECSS 7da17eb6 p33: `embed_text` describes table A → table B. HTRCHAR p11: a corrected value appears in `content` and `embed_text` |
| R2 | **Some answers do nothing, or the opposite.** `redact` and `exclude` release a halted sensitive file into search ([cases.py:732](../../backend/review/cases.py#L732), [:788](../../backend/review/cases.py#L788)). `watch`, `use_replacement`, `approve_download` and `map_columns` have no code. Run-label and t0 answers change nothing | `exclude` takes the file out, like junk. Withdraw every answer with no code from `ALLOWED_ACTIONS` ([contract.py:355](../../backend/dispatcher/contract.py#L355)) until its screen is built. No stored decision uses them (checked) | An API resolve with `redact` → refused; `exclude` → the file QUARANTINED, not in search |
| R3 | **Flags vanish or go stale on rebuild.** Flags the commit raises (the 3 TP07 run-label questions) are closed on the next rebuild ([staged.py:96-105](../../backend/review/staged.py#L96) and [flags.py:45](../../backend/review/flags.py#L45)). 4 of 5 table choices now point at pages with no table, but still show as decided | The gate closes only the route's own flags, and a re-raise reopens a row the pipeline closed. A decision whose target is gone is shown as "no longer applies" and is not applied | Rebuild a TP07 file: its question stays OPEN. PreHeat p1: "Table version B chosen" → "no longer applies" |
| R4 | **4 decisions never reached search** (the "Setup" workbooks, decided after their last index; cause unknown) | The 30-minute check also rebuilds any file whose newest decision is newer than its last index ([reconcile.py](../../backend/dispatcher/reconcile.py)) | Count 4 → 0 within 30 minutes |
| R5 | **Burst photos skip their flags,** including the export-control marking. Members copy the first photo's reading with an empty flag list ([d_photos.py:348](../../backend/routes/d_photos.py#L348)) | Members get the first photo's flags too | A burst with a marking: every member HALTED, not only the first |

## Part 2. Review screens, one per flag type

Each screen is built from the reviewer's job, with no shared format. What is shared: one Apply per case, the server deciding the allowed answers, and help that lists only the screen's buttons.

| Order | Flag type | The job | What the screen shows | Answers | Backend it needs |
|---|---|---|---|---|---|
| 1 | **Handwritten page** (1c) | Proofread the transcription | The page image beside the whole reading. Tables are grids; unsure entries are highlighted | Confirm, correct (type or pick an alternative), unreadable, per entry; edit any other cell or text | R1; store the reader's full output per page (`pages/{n}.reading.json`, [route.py](../../backend/routes/a1_office/route.py)). Spec: [specs/1c-page-check.md](specs/1c-page-check.md) |
| 2 | **Units** (1b) | Give columns their units and be sure the numbers make sense | Keep the channel map | As today | Fix: a unit set on a sheet column changes no data; fill "First values" (empty for Injector 10); no preselected unit when the system is only guessing |
| 3 | **Figure (chart or drawing)** | The reader was unsure it could read the figure or its values. Check the values | The figure large, beside the values read (series, points, axes, units) | Values right; correct values; not interpretable (keep the image, drop the values); junk | Flag charts by their confidence, which is never checked today. Put the values read into the flag ([figures.py:268-331](../../backend/routes/a1_office/figures.py#L268)) |
| 4 | **Table read two ways** | Pick the right reading, cell by cell | The table's area of the page above A and B, with the differing cells marked | A, B, edit cells, junk table | R1 (choose the table by its box, not every table on the page) |
| 5 | **Run label already used** | Same run as an existing one? | Both runs side by side | Different run; duplicate (drop this file); replaces the old one; answer once for all | Name runs by folder + file, so priming, purging and main stop colliding. That removes most of these questions |
| 6 | **Check failed (t0)** | Where does the test start? | The signal around t0, with a marker | t0 is right; set t0 here; no start event | Serve the signal for the screen; a "set t0" answer |
| 7 | **Document fact disagrees** | Which value is right? | Each value with where it came from | A, B, type the value | Make the answer apply to more than 3 field names |
| 8 | **Page that could not be read** | Rescue the page or drop it | The page image and the OCR text | Keep OCR, junk page | The flag carries the page image, which is empty today ([route.py:307](../../backend/routes/a1_office/route.py#L307)) |
| 9 | **File problems** (unreadable, unsupported, too large) | Get a readable copy, or drop it | The error in plain words, the file facts, "Open in OneDrive" | Skip, junk (approve download and use replacement when built) | – |
| 10 | **Sensitive content** | The compliance call | The passage with the hit highlighted | Exclude, approve (admin) (redact when built) | R2 |

## Done (2026-10-27), proved on the live stack
- **R1:** decisions applied before chunking, in the gate (`indexing/overlays.py apply_decisions`). ECSS p33: search now reads table B.
- **R2:** answers with no code withdrawn; exclude takes the file out.
- **R5:** burst members keep the first photo's flags. Coded and tested; deployed with the media worker.
- **Page check (1c):**
  - Entries can be confirmed, corrected or marked unreadable.
  - Any cell or line can be corrected (`set_cell` / `set_text`, kept as decided flags of origin `review`).
  - HTRCHAR p11: a cell corrected, then undone; search followed both ways.
- **Halt and undo:**
  - Taking back a blocking decision removes the file's content from the index at once. The file halts, and deciding again re-indexes it. Test_12_10Bar_ii_1 went round the full cycle.
  - Any halt of an indexed file removes its content (`indexing/withdraw.py`).
  - Files stuck in PROCESSING are resent (`dispatcher/reconcile.py`).
- **Versions** (user's decisions: remove all and keep a record; carry over unchanged decisions):
  - an edited file is inspected again;
  - the old version stays live until the new one is searchable (`routing.replace_older`, from the commit), then is removed with one history row kept (`dispatcher/versions.py purge_replaced`, every 30 min);
  - a revert before removal brings the version back;
  - unchanged decisions carry over (`review/carry_over.py`);
  - a renamed or moved file gets its path and folder gate again;
  - a late commit cannot reactivate a replaced version.
  
  Unit-tested; no live edit has happened yet.
- **Still open:**
  - R3 (flags closed silently by rebuilds; decisions whose target is gone);
  - R4 ("decision newer than the last index" rebuild);
  - document labels after a move;
  - a delete followed by a re-upload is not linked as a new version;
  - the catalog misses REOPENED flags;
  - old document fields survive a rebuild.

## Order of work
1. **R2 and R5**: small, and they protect sensitive content.
2. **R1**: decisions applied before chunking.
3. **Screen 1**: page check.
4. **R3 and R4**.
5. **Screen 2**: units.
6. **Screens 3–10**, in the order of the table.

Re-runs start with a pilot of 3–5 files: HTRCHAR, PreHeat, one TP07 telemetry file, ECSS 7da17eb6.

---

## Parked: found by the route audit, not part of this work
Each is real; none blocks the review. To be decided later.
- A whole-page read can fail a document whose references were attached to a removed node ([structure.py:229](../../backend/routes/a1_office/structure.py#L229) → [contract.py:918](../../backend/dispatcher/contract.py#L918)).
- One unusable model reply fails a whole file (Atlas, 420 pages, failed on page 78).
- A gateway outage during a whole-page read silently keeps the poor OCR ([route.py:268](../../backend/routes/a1_office/route.py#L268)).
- Numbers in tables and figures never become numeric facts: 445 tables and 632 figures, 0 facts.
- Telemetry:
  - a CSV units row is taken as the header;
  - a one-island workbook becomes a different run on resume;
  - the run summary keeps the old label.
- Office files:
  - `.odt/.odp/.ods/.rtf` are misrouted;
  - Word embedded objects and comments are lost;
  - slide text is never enriched.
- Photos and video:
  - document photos skip the handwriting steps;
  - a slide description that falls between two transcript windows is dropped.
- Diagram readings have no image (E). The A2 twin appendix pages are never processed.
- The vision cache key leaves out the system prompt.
