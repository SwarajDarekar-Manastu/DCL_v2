# Plan: self-describing sections and videos

Agreed with the user on 2026-10-28. A step of `PLAN_query_routing.md` (its pattern "files don't describe
themselves: chunk headers built from thin summaries"), measured the same way. One build, one check; kept
only if the check passes.

## 1. Thesis

Search hands the answer writer only what processing made findable. A section is found by its own text plus
what enrichment adds: the About line in its search header, its entities, and its 3–5 questions (their own
search entries). If every field is answered and every piece carries its own section's description and the
file's category, the right section reaches the writer more often.

## 2. The problem (measured 2026-10-28)

1. **Skipped fields.** The enrichment reply schema requires only `summary` and `section_kind`. 1,958 of
   2,935 saved replies (67%) leave out entities, numbers and questions, all with a normal finish. Only
   1,099 of 3,006 sections in search have question entries. A/B on 20 such sections with every field
   required: 20/20 complete, entities 44 → 159, numbers 34 → 74, questions 6 → 20 of 20.
2. **One About line per file.** Every piece's About line is the first sentence of the first two
   sections' summaries. Atlas: 1,663 of 1,718 entries say "…cleared for public release…".
3. **Category unused.** The file's main kind is computed and read by nothing.
4. **Videos are sorted before anything looks at them.** The share of speech in the first minute picks
   the reading; only a video without speech gets a kind. A meeting is never recognised as one.
5. Not a cut-off problem: no cut reply ever reached search. Reply length is set in the prompts; code never
   trims a model's text.

## 3. The solution

- **Every field answered.** Always filled: summary, section kind, 3–5 questions. Filled when the section
  has it, otherwise empty: entities, numbers, test IDs, standards, status markers, claims, publication type.
  Same 10 fields, one generic prompt (`parent.v3`), no file names or word lists.
- **Each piece carries its own section's description.** The About line is the section's summary as the
  model wrote it; the prompt keeps it short, code does not cut it. Pieces, tables, figures and question
  entries under a section use that section's. The file summary stays the fallback.
- **The file's category in every header** and in the file card: a video's recording kind, else the main
  section kind.
- **Videos: one look decides and describes.** Every video gets the one `video_timeline` call (frames of
  the whole clip, the file's details, the first minute of speech). It says what the recording is,
  `meeting` included, and describes it. A meeting is then transcribed (sections, slides); every other kind
  keeps the timeline. No separate classify prompt or call. Without cloud processing, the speech share
  decides as before.

## 4. Files and changes

| File | Change |
|---|---|
| `backend/llm_engine/enrichment/extract.py` | Every schema property required (lists may be empty, nullable stays nullable); defaults kept so saved replies parse. `PROMPT_VERSION = "parent.v3"`. |
| `backend/llm_engine/prompts/enrichment/parent.v3.md` (new) | Fields grouped "always" / "when the section has it, else empty"; what each is for; summary one sentence of at most 25 words (it must fit the 120-token header). |
| `backend/indexing/index_document.py` | Section summaries and the category passed to the header and card builders. |
| `backend/indexing/chunker.py` | `build_embed_texts(..., about_by_ref, category)`: About = own section's summary, else the file's; category in the Doc line. |
| `backend/indexing/card.py` | Category in the card's Kind line. |
| `backend/llm_engine/prompts/vision/video_timeline.v4.md` (new) | v3 plus the kind `meeting` and the first minute of speech; a meeting leaves events empty. |
| `backend/llm_engine/vision/schemas.py`, `service.py` | `RecordingKind.MEETING`; `video_timeline(..., first_minute_speech)`; task uses v4. |
| `backend/routes/f_video.py` | `_look` makes the one call for every video; `meeting` → transcript reading with the kind and summary in the catalog; others → timeline reading from the same reply. |
| Tests | `test_extract.py`, `test_chunker.py`, `test_index_document.py`, `test_f_video.py`. |
| Manuals | 03 §10 (route F), 04 §3.2, §3.4, §4.2. |

## 5. Check

1. Unit tests and ruff on the changed files.
2. **Before:** Step 2b's silver run, 125/164 (the engine code is back to that state).
3. Deploy the images to the route workers and the api (the api serves Open WebUI; it also gets the
   routing steps 1 and 2b, both kept by their checks).
4. Pilot 3–5 files; by SQL: every section has questions, About lines differ per section, category in the
   headers, no stuck replies.
5. Re-process the enriched files (A1, A2, F; about 62).
6. **After:** silver run, 82 cases × 2. Kept if document, library and visual do not drop, at least one
   improves, and no other route drops; otherwise revert and re-process.
7. **Open WebUI:** ask a few questions by hand from document, library and video cases and check the
   answers and their sources.
8. **Meeting:** after the user uploads the recording to the APU test folder, check it is classified
   `meeting`, transcribed, and its sections have descriptions and questions; add 3–5 silver cases.

## 6. Results

**Pilot (3 documents, 2 videos).**

| File | Sections with questions | Distinct About lines | Entity mentions |
|---|---|---|---|
| Heater bed test plan (A1) | 10 → 23 of 23 | 1 → 23 | 79 → 196 |
| Ariane datasheet (A1, Library) | 4 → 11 of 11 | 1 → 11 | 11 → 67 |
| TC2 TP6 report (A2) | 7 → 18 of 18 | 1 → 18 | 23 → 76 |

The two videos kept their kinds (firing, inspection), now shown in every header.

**Two corrections found by the pilot and the re-run.**
1. The first prompt allowed one or two sentences (median 34 words). The header cap of 120 tokens then
   dropped the About line from most pieces (24 of 108 kept it in the test plan). The prompt now asks for
   one sentence of at most 25 words; after it every piece of the pilot kept its About line.
2. Deep paths (videos: 7 folders) still pushed the About line out, because the cap dropped it before the
   start of the path. The order is now: entities, then the start of the path, then the About line.

**A crash the new extraction exposed.** With every number extracted, Atlas had a value in dB²; the unit
library parses it but cannot convert it, and the error stopped the whole file. `common/units.parse_unit`
now treats a unit it cannot convert as unreadable, so the number is kept with `needs_unit` (manual 04
§3.2). Regression test in `test_numeric_facts.py`.

**Re-processing (A1 38, A2 23, F 4 files).** Every section has its question entries (2,865 + 111 + 4);
every piece is embedded. 2,956 enrichment calls, $10.21 (all model calls of the re-run: $11.60), no
reply hit its cap (largest 5,728 tokens). One file failed on a gateway outage (HTTP 502) and was queued
again.

**Open WebUI (2026-10-29, test user, by hand).**

| Question | Before (silver, 2 runs) | Open WebUI answer |
|---|---|---|
| Objectives (JSON): catalyst with the inclined injector | 0/2 | right: 38 mm La-stabilized Pt catalyst, 30° injector; cites the plan's overview section |
| TP7 expected thrust at 22 barg | 0/2 | right value, 158.18 N, "answer verified"; cites the Setup workbook, not the `.tex` the case expects |
| ECSS-E-ST-35-10C galvanic corrosion method | 2/2 | right: ASTM G 71-81, clauses 4–7, clause 6.5.2 |
| TP9 de-integration video (6.7 s) | 2/2 | right: a spoon probes and stirs the catalyst pellets, six timed steps from the v4 reading |

Seen in passing: the video's source is labelled "internal report" (routing plan step 4, labels by kind).

**Silver, 82 cases × 2 (2026-10-29), against Step 2b's run.**

| Route | Before | After |
|---|---|---|
| document | 29/42 | **32/42** |
| library | 12/14 | 12/14 |
| visual | 28/32 | 28/32 |
| source | 17/24 | 18/24 |
| diagram · measured · table | 13 · 10 · 12 | 13 · 10 · 12 |
| **total** | **125/164** | **129/164** |

- Better: JSON overview EOL target 0 → 2, de-integration outer diameter 0 → 1, TP12 Test 01 max firing
  temperature 1 → 2, debug max runs 1 → 2, TP23 retainer material 1 → 2. Worse: de-integration handwritten
  date 1 → 0 (tool misroute), RevC overall length 2 → 1 (Route E, not re-processed).
- Passed both repeats: 60 → 63; no case that passed both before fails both now.
- Retrieval recall unchanged (recall@8 0.929, recall@30 0.964 on 112 anchored runs).
- One case corrected (version 2): `silver-f-tp07-video-pellets` required the literal word "tool"; the
  v4 reading names the tool (tweezers), the answer cited the right video with faithfulness 1.0. Without the
  correction visual read 26/32; with it, 28/32 (re-run of that case: 2/2).
- Median answer time 28.6 s → 48 s: every engine call slowed alike (chitchat 2.0 → 3.5 s on the same
  input), the gateway that night (it also returned HTTP 502 on one paper's plot reads); the writer's input
  is the same size (10,499 against 10,498 tokens).

**Kept**: document improves, library and visual hold, no other route drops.
