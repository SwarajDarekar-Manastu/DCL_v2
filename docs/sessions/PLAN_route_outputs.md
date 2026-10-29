# Plan: self-describing outputs for routes B, C, D, E, G (and the F header)

Research and plan, 2026-10-29. Nothing built. Companion of `PLAN_route_retrieval.md`; this plan goes first,
because retrieval can only rank what a piece says about itself. Same rules as `PLAN_self_describing.md`:
generic prompts, length set in prompts and never trimmed by code, one step and one check, kept only if the
silver run holds or improves by route.

## 1. Thesis

A1, A2 and F now describe themselves: every model field is answered, each piece carries its own section's
short description, and the file's category is in every header. The other routes still label their pieces
with the first sentence of a long machine listing (cut by code), and two image readers skip the fields
that hold their content. A question can only find a piece by what the piece says, so the next gain is in
what B, C, D and E write, not in how search ranks it.

## 2. What was measured (live index and saved replies, 2026-10-29)

**About line per piece** (should be present on every piece):

| Route | Pieces | With About | Why it is missing |
|---|---|---|---|
| A1, A2 | 10,361 | 10,067 (97%) | (fixed by `PLAN_self_describing.md`) |
| F videos | 28 | **0** | header 85 tokens without About; the Path line repeats the file name (22 tokens; digit-heavy names); with the 20–23-word About it is 137 > 120, so the About goes |
| C configs, tables, rows, runs | 645 | **12 (2%)** | About = first sentence of a machine listing (`Configuration LJStreamM.cfg (ini, 15 settings): Main.FilePrefix = …`, avg 220–1,203 chars), cut at 300 chars by `first_sentence`, then dropped by the 120-token cap |
| D photos | 81 | 69 | plot summaries avg 1,884 chars; 11 of 26 plot pieces lose the About |
| E diagrams | 6 | **0** | file summary is `content[:800]` (cut by code); its first sentence does not fit |
| B code | 69 | 67 | `requirements.txt` has no summary at all |

**Fields the model skipped** (raw replies in the result cache; "skipped" = key absent, not empty):

| Reading | Replies | Skipped | Consequence |
|---|---|---|---|
| `read_schematic.v3` | 238 | `components` 237, `connections` 236, `steps` 58, `notes` 73 | the Injector 10 setup schematic's search text is literally "Schematic components:" with nothing after it; its tags cannot be found (`silver-d-inj10-setup-schematic-components`, rerank miss) |
| `inspect_hardware_photo.v2` | 292 | `components_visible` 13, `failure_modes` 13 | 4% of photos lose their parts list |
| `digitize_plot.v2` | 183 | `y_axes` 8, `series` 4, `annotations` 3 | 2–4% of plots lose axes or series |
| `classify_image`, `triage_page`, `transcribe_page`, `read_table_image` | — | none that matter | all fields required or legitimately empty |

The schema of `read_schematic` requires only `image_metadata`, so the model puts the parts into
`image_metadata.hardware` and leaves `components` out. Same cause as the enrichment fix (`parent.v3`): left
optional, Gemini skips.

**Other measured gaps.**
- Screenshots of programs, terminals and e-mails are classified `plot_or_screenshot` and read by the plot
  reader, which returns nothing for them (probe of 2026-10-28, 3 of 3).
- `ScanRate=1000.0` in the LabJack configs has no unit in the file; both scan-rate cases fail on the unit
  (`UNIT_ERROR`, 0/2 each).
- No Route G file is indexed yet.

## 3. Design per route

**All routes (header).** The Path line never repeats the file's own name: `chunker._section_path` drops the
title when it is the first element (documents) but not when it is the last (photos, videos, runs, code,
configs). Dropping it there frees about 20 tokens on every single-file piece. Video headers then fit with
their About line (about 115 tokens).

**D photos and image readings everywhere (A1/A2 figures, D, E, F).**
- Every reading field required, an empty list or null only when the image has none: the same
  `json_schema_extra` rule as `parent.v3`, on the vision `Reading` base, so plots, drawings, photos, slides
  and video readings all get it. New prompt versions state which fields are always filled and which only
  when present: `read_schematic.v4` (components with their tags, connections), `inspect_hardware_photo.v3`,
  `digitize_plot.v3`.
- The About line of an image piece is its reading's `image_metadata.subject`, which every reader already
  returns. The image-context prompt asks for one sentence of at most 25 words. No new field.
- Screenshots get their own class in `classify_image.v2` (`screenshot`: a program, terminal, web page,
  e-mail or spreadsheet on a screen) and are read as a page (`transcribe_page`), not by the plot reader.

**C configs, workbooks and runs (no model call today; none added for the About line).**
- The About line is one short sentence that the route builds from its fixed facts: what the file is, how
  many settings, tables or channels it has, and its rate and duration. No lists, so nothing has to be cut.
  Examples:
  - "LabJack stream configuration with 15 settings, file prefix Test_01."
  - "Workbook with 4 tables: Temperature, Pressure, Mass flow, Summary."
  - "Telemetry run, 2 Hz, 57 s, 6 channels."
- The full listing stays in the piece text and the file card.
- Units the file does not state (`ScanRate`) need a source: see decision D1.

**B code and requirements.**
- `requirements.txt` and other tooling text files get the same built sentence, for example "Python
  requirements file pinning 12 packages".
- Code files keep `code_summary`, used as the About line only when it fits; otherwise the module line.
- Route B stays model-free (manual 03 §6) unless decision D1 says otherwise.
- The xlwings miss is a search filter, not an output gap: see `PLAN_route_retrieval.md`.

**E diagrams.** The file summary is no longer `content[:800]`. The About line is the diagram's title plus
its component and connection counts, built by the route.

**G archives, CAD, simulation packages.** The card already says what the file is, what it holds and where it
sits. Nothing to change until a G file is indexed; unit tests only.

## 4. Build steps (each kept only if its check passes)

| Step | Files and changes | Check |
|---|---|---|
| O1 Path does not repeat the title | `backend/indexing/chunker.py` `_section_path`: drop the title when it is the last element too; test in `test_chunker.py` | SQL: About on F pieces 0 → 28; silver by route (re-index F, D, C, B: cache only) |
| O2 Every reading field answered | `backend/llm_engine/vision/schemas.py` (`Reading` config, the same helper as `enrichment/extract.py`, moved to one place); prompts `read_schematic.v4`, `inspect_hardware_photo.v3`, `digitize_plot.v3`; `vision/service.py` versions; tests | skip counts on the re-read replies (target 0); the Injector 10 schematic text names its burst disk, valve and transducer tags; silver diagram and visual routes. Re-reads all drawings, photos and plots: about $5 |
| O3 Image About = subject | `backend/indexing/index_document.py` (About for figure, photo and video-event pieces from `image_metadata.subject`); prompt `image_context.v3` (subject: one sentence, at most 25 words) | SQL: About on D and figure pieces; silver visual |
| O4 Screenshots read as pages | `classify_image.v2` with the `screenshot` class; `backend/routes/d_photos.py` routes it to `transcribe_page` | the three probe screenshots return their text; silver visual |
| O5 Built About for C, B, E | `backend/routes/c_telemetry/config_file.py`, `tables.py`, `series.py`; `backend/routes/b_code/route.py`, `text_docs.py`; `backend/routes/e_diagrams/route.py`: a `DocumentFields.about` sentence built from fixed facts; `index_document.py` prefers it over `first_sentence(doc_summary)` | SQL: About on C pieces 2% → ~100%; silver table, measured, source, diagram |
| O6 Units for unit-less settings (only if D1 says so) | either a reviewed unit table in `config/` read by `config_file.py`, or one model description per config file (the 3b prompt, restored from the backup) | the two LabJack scan-rate cases |

Order: O1 and O2 first (largest measured gaps, cheapest), then O3–O5, O6 last. Each step is checked by the
silver run, 82 cases × 2, by route against `after_final.jsonl` (129/164), and kept only if the target
routes improve and none drops. Watched by name: `silver-d-inj10-setup-schematic-components`, both LabJack
scan rates, `silver-b-requirements-xlwings`, `silver-d-nav-burned-mesh-photos`.

## 5. Open decisions

- **D1 Units for settings a file does not state** (LabJack `ScanRate`). (a) A reviewed table of tool
  settings and their units in `config/`, used by code (no model, reviewable). (b) One Gemini description per
  config or source file (about $0.002 a file; Route B would then send code to a model, against manual 03
  §6). (c) Leave it; the two cases stay failed.
- **D2 Re-reading all images for O2** (about $5 and a few hours of worker time), or only the drawings
  first (about $1), where the skip rate is 99%.

## 6. Parked

- The planner's own reply schema (`QueryAnalysis`) also has optional fields; it is never cached, so its
  skip rate cannot be measured from saved replies.
- `first_sentence` still cuts the file summary at 300 characters for files without an About sentence.
- 3 Route G CAD card tests fail (before this work).
- Answers label a video source as "internal report" (routing plan step 4).

## 7. What the research says

- **Every field required.** Google's Gemini troubleshooting guide gives "make all output fields required"
  and "don't specify the order of fields in your prompt" as the fixes for repeated text in structured output
  [S1]. A field is optional unless it is listed as required, nullable is `["string","null"]`, and length
  limits are not enforced [S2]. OpenAI requires every field [S3]; Anthropic advises few optional fields [S4].
  Our A/B (2026-10-28) agrees: 3 of 42 replies with the optional schema ran away, 0 of 40 with every field
  required. O2 keeps each prompt's field order the same as its schema's.
- **Piece-specific context, not a generic summary.** Contextual retrieval puts 50–100 tokens of
  chunk-specific context before both the embedding and BM25 text. Generic document summaries gave "very
  limited gains" [S5]. This supports the About line per piece (O3, O5) over the first sentence of a file
  listing.
- **Exact identifiers in lexical search.** File names, symbols and versions match lexically; Sourcegraph
  weights file names and symbols higher [S6]. The built About sentences keep names verbatim.
- **Units only from a source.** No method was found for inferring a unit a file does not state; unit errors
  are a named class of extraction error [S7]. A unit comes from a reviewed table or a quoted document, else
  it stays unknown (D1).
- **Tables.** Repeat the header with units in each row chunk (Route C already does) and keep one card per
  table [S8][S9].
- **Drawings.** Tags and components are read reliably; connections are the weak point (flowchart edge F1
  0.667 for a dedicated extractor, about 0.1 for small VLMs) [S10]. `read_schematic.v4` therefore requires
  components with their tags; connections are required too, but answers treat them as less certain.
  Normalised identifiers drive drawing retrieval [S11].
- **Photos of documents and screenshots:** read as text (OCR), not as a picture [S12] (O4).
- **Unparsed files:** a card built from metadata (path, header fields, archive tree), marked "contents not
  read" [S13]. Route G already does this.

## 8. Sources

- [S1] Gemini API troubleshooting, https://ai.google.dev/gemini-api/docs/troubleshooting
- [S2] Gemini structured output, https://ai.google.dev/gemini-api/docs/structured-output
- [S3] OpenAI structured outputs, https://developers.openai.com/api/docs/guides/structured-outputs
- [S4] Anthropic structured outputs, https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- [S5] Anthropic contextual retrieval, https://www.anthropic.com/news/contextual-retrieval
- [S6] Sourcegraph BM25F, https://sourcegraph.com/blog/keeping-it-boring-and-relevant-with-bm25f
- [S7] Extraction error study (unit conversion errors), https://arxiv.org/abs/2512.22130; MeasHalu, https://arxiv.org/abs/2604.16929
- [S8] Ragie table chunking, https://www.ragie.ai/blog/our-approach-to-table-chunking
- [S9] LlamaIndex recursive retrieval over tables, https://developers.llamaindex.ai/python/examples/query_engine/pdf_tables/recursive_retriever/
- [S10] FlowExtract, https://arxiv.org/html/2604.06770v1
- [S11] Blueprint (engineering drawing retrieval), https://arxiv.org/abs/2602.13345
- [S12] OCR versus vision retrieval on degraded scans, https://arxiv.org/abs/2505.05666; Azure multimodal search, https://learn.microsoft.com/en-us/azure/search/multimodal-search-overview
- [S13] Metadata-only indexing, https://onesearch.readthedocs.io/en/latest/supported-formats/metadata-only/
