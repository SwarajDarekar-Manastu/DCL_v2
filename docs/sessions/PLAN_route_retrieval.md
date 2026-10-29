# Plan: route-aware retrieval for every kind of data

Research and plan, 2026-10-29. Nothing built. Builds on `PLAN_query_routing.md` (8 answer routes, what was
measured and removed) and `PLAN_self_describing.md` (129/164). Runs after `PLAN_route_outputs.md` steps O1–O2,
because the largest retrieval miss measured here is a piece whose text is empty.

## 1. Thesis

The starting idea was that images compete with text for the same top-8 slots. The live index says they
mostly do not. Search already finds the right piece for 93% of anchored questions in its top 8 (96% in its
top 30). Image pieces fill 10% of the top 8 on document questions, 16% on library and 2% on source, and they
dominate only where they should (visual 78%, diagram 83%). What fails is narrower:
- evidence that is not in the text (an empty drawing reading, a setting without its unit);
- one hard filter that hides a source file;
- the wrong piece type outranking the right one for a typed question;
- answer-time behaviour;
- test requirements that fail right answers.

So route-aware retrieval here means: let each route **prefer** its own piece types (never exclude them),
remove the one hard filter, and measure routing on its own. Per-type quotas and a second reranker stay out
until a measured displacement remains after the outputs plan.

## 2. The problem in numbers

**Silver, 82 cases × 2 (`after_final.jsonl`, 129/164), by route.**

| Route | Cases | Passed | Failing cases and why |
|---|---|---|---|
| document | 21 | 32/42 | JSON objectives and TP7 thrust: right value, a different file cited (4 runs); handwritten de-integration sheets: tool check (3 runs right in content), date wrong (2); TP6/TP7 conflict 1/2 |
| library | 7 | 12/14 | Moog price: should say "not in our files" |
| visual | 16 | 28/32 | Injector 10 schematic tags: rerank miss (its drawing text is empty); "show me the mesh photos": right photos, tool check |
| diagram | 7 | 13/14 | RevC length 1/2 (insufficient evidence once) |
| measured | 11 | 10/22 | 4 halted-data and 2 not-available behaviours |
| source | 12 | 18/24 | xlwings: `requirements.txt` excluded by the code filter (recall 0); LabJack scan rate ×2: no unit in the file |
| table | 6 | 12/12 | — |

Nine failing runs have the right content (citations, entities, numbers and faithfulness pass) and fail only
a test requirement: the expected tool list (5) or one expected file when another file holds the same value
(4). Decision T1 below.

**Search-only probe** (all 82 questions, local search and reranker, free; `types_probe.py`):

| Route | Image pieces in the top 8 | Gold in top 30 but not top 8 |
|---|---|---|
| document | 18/168 (10%) | — |
| library | 9/56 (16%) | — |
| source | 2/96 (2%) | — |
| table | 3/48 (6%) | — |
| measured | 10/88 (11%) | `tp07log-sampling-rate`: 8 table rows outrank the run summary |
| visual | 101/128 (78%) | `inj10-setup-schematic`: tables and rows outrank the drawing |
| diagram | 47/56 (83%) | — |

## 3. What the research says, and where our data agrees

- **Route first; separate lists per type fight modality bias.** A shared embedding space favours items of
  the query's modality: UniversalRAG [R1], MM-Embed [R2]. Vendors keep per-type stores or filters: LlamaIndex
  uses separate text and image top-k [R3], Azure AI Search filters by content type [R4]. *Ours:* the photo
  tool already searches photos, figures, video events and drawings on its own; text routes show no crowding.
- **An LLM router generalises better out of domain; a trained router wins in domain; measure routing on its
  own.** UniversalRAG [R1], mmRAG [R5], RAGRouter-Bench [R6]; routing works when categories are distinct
  [R7]. *Ours:* the planner's intents already map one-to-one onto routes; the benchmark already scores tools
  and route hits separately.
- **Text rerankers lean toward text candidates.** UniRank [R8]; scores are not comparable across types
  without calibration [R9]. No study found showing cross-encoders demote short structured readings.
  *Ours:* 2 rerank drops in 82 questions, both table rows or tables over another type.
- **Images: verbalised readings serve retrieval; visual vectors win on figures.** ColPali [R10], VisRAG
  [R11], M3DocRAG [R12]; Azure verbalises diagrams for citable text [R4]. *Ours:* the readings are the text
  that gets searched, so a skipped field (99% of drawings skip their components) is a retrieval loss. That is
  fixed in the outputs plan, not here.
- **Video and meetings: text finds videos better than frame vectors; anchor pieces in time.** VideoRAG
  [R13], Video-RAG [R14]; split transcripts at speaker or topic turns [R15]. *Ours:* transcript windows of
  60–120 s split at pauses and slides, each with a `#t=` deep link.
- **Diagrams: connectivity needs a graph; names alone are not enough.** ChatP&ID [R16], CAD-to-graph [R17].
  *Ours:* draw.io diagrams already go through the graph tool; drawings read from images do not, and their
  readings skip the connections.
- **Not found:** no study of per-type quotas in top-k, of ask versus assume, or of meeting window size.

## 4. Design per route

**Planner strategy (user, 2026-10-29).** The planner names which kinds of data hold the answer (the
routes), and each route searches its own way. Today it is half built:
- **There:** the catalog shows the planner the candidate files. The answer engine maps a file to its route
  (`answer_routes.of_document`).
- **Missing:**
  - The planner names *intents*, a mix of task types (fact lookup, procedure, failure investigation, visual
    lookup) from which `build_plan` picks searches.
  - No intent means meeting, table or archive.
  - The catalog's file lines do not show the route.
  - Step 3.0 added a routes field and removed it, because nothing searched by it.

The build completes it:
1. **The planner returns `routes`** (required, 0–3, most likely first), each described in general terms in
   the prompt (`query_analysis.v4`, starting from the backed-up Step 3.0 text, plus `meeting`).
2. **The catalog's file lines show each file's route**, so the planner grounds its choice in the files that
   exist.
3. **`build_plan` runs one method per named route** (the table below).
4. **Intents keep only what changes how the answer is built,** not where to search:
   - telemetry statistics and comparisons;
   - a physics calculation;
   - a whole-document summary;
   - a design synthesis;
   - a list of what exists;
   - small talk.
5. **The intent branches that only chose a search are deleted:** fact, procedure, failure, standards,
   code, diagram and visual lookups. A question with no route gets the document route.
6. **The benchmark scores the chosen routes against the case labels** (`chosen_ok`), so routing is measured
   on its own.

| Route | Evidence (pieces, metadata) | Recognised by (planner intent) | Retrieval | Answer shape |
|---|---|---|---|---|
| document | child, parent, table, figure of A1/A2 reports and plans | fact_lookup, procedure_lookup, failure_investigation, document_summary | general search, unchanged (text already wins); figures stay members of their section | value with page and section; a figure's value with its caption |
| library | the same pieces, `folder_kind = library`, standards | standards_compliance, or source_scope internal_and_library | unchanged; standards search exists | clause or table and page |
| visual: photo | photo (D), figure | visual_lookup, needs_visuals | photo tool (`inspect_visuals`, its own list); unchanged | images shown with their reading |
| visual: video | video_event with keyframe | visual_lookup about a recording | photo tool, kind `video_frame`; unchanged | time plus viewer link (`#t=`) |
| meeting | transcript_window under 10-minute sections, `recording_kind = meeting` | a question about a meeting, discussion or recording | general search **preferring** `transcript_window` and `video_transcript` when the planner names them (new names in the prompt's lists) | quote or summary with time and viewer link |
| diagram | diagram_summary, figure, photo of a drawing; draw.io graph | diagram_traversal | graph tool plus search **preferring** drawing pieces, replacing today's hard `doc_kinds=["diagram"]` | components and connections with the drawing shown |
| table | table, table_row | fact_lookup with numbers | tables-first search exists; unchanged | value with its row and column |
| measured | run_summary, telemetry | telemetry_metric, run_comparison | telemetry tool; the report-text search **prefers** `run_summary` (fixes table rows outranking it) | value with run, channel, unit |
| source | code_symbol, module_header, config, tooling text | code_walkthrough | the hard node filter (function and module pieces only) becomes a **preference** for source kinds and pieces; excludes nothing | the line or setting quoted, with the file |
| archive | the file card | navigational | card only (no G file indexed) | what it is, where it sits, its link |

Rules: a route's filter excludes nothing unless the user typed the exact ID; every route change is a
preference (`prefer_node_types`, `prefer_doc_kinds`, `prefer_doc_ids`), which adds rankings to the fusion
and hides nothing.

## 5. Build steps (after `PLAN_route_outputs.md` O1–O2)

**P1, built first (2026-10-29, user):** the planner strategy above, with the route methods of the table.
This includes R1–R4 (source, measured and diagram preferences, meeting names).
- **Files:**
  - `backend/llm_engine/engine/answer_routes.py`: `MEETING`, `SOURCE_KINDS`;
  - `analysis.py`: `routes`, v4;
  - `prompts/engine/query_analysis.v4.md`;
  - `catalog.py`: the route in file lines and in the measured-data check;
  - `playbooks.py`: route methods, the search-only intent branches deleted;
  - `workflow.py`: the gallery for the visual route;
  - `benchmark/metrics.py`, `runner.py`: chosen routes;
  - tests.
- **Check:**
  1. Silver subset: every failing case plus two passing cases per route, 2 repeats, against
     `after_final.jsonl` on the same cases.
  2. Then the full silver run.
  3. Kept only if no route drops.

| Step | Files and changes | Check |
|---|---|---|
| R0 Re-probe | rerun `types_probe.py` and the silver run on the re-read index | the two rerank drops and the per-route image shares; if the schematic now ranks, R5 is not needed |
| R1 Source preference | `backend/llm_engine/engine/playbooks.py` code branch: `node_types` filter → `prefer_node_types` + `prefer_doc_kinds` for code, tooling_doc, config (the Step 3b search change, restored from the routing backup and measured alone) | `silver-b-requirements-xlwings`; source route; no route drops |
| R2 Measured preference | `playbooks.py` telemetry branch: the report-text search gets `prefer_node_types=["run_summary"]` | `silver-c-tp07log-sampling-rate` in top 8; measured route |
| R3 Diagram preference | `playbooks.py` diagram branch: `doc_kinds=["diagram"]` → `prefer_node_types` for diagram_summary, figure, photo | diagram and visual routes; Injector 10 schematic |
| R4 Meeting names in the planner | `backend/llm_engine/prompts/engine/query_analysis.v4.md` (Appendix A): `video_transcript` in doc_kinds, `transcript_window` in node_types, one generic line on recordings; `analysis.py` version | the meeting cases once added; no route drops |
| R5 Per-type slot (only if R0 still shows displacement) | `backend/indexing/retrieval.py` `search`: when the planner prefers a type, keep up to 2 of the top 8 for its best pieces after rerank | the displaced case; every route |

Each step: silver run, 82 cases × 2, by route against the latest kept run. Kept only if its target route
improves and none drops; otherwise reverted.

## 5a. Results of P1 (2026-10-29)

**Silver subset.** Every failing case plus 2 passing cases per route (35 cases × 2), against `after_final.jsonl`
on the same cases: **35 → 41 of 70**.

| Route | Before | After |
|---|---|---|
| document | 6/16 | 10/16 |
| visual | 4/8 | 6/8 |
| diagram | 5/6 | 6/6 |
| source | 4/10 | 3/10 |
| library, measured, table | unchanged | unchanged |

- **Better:**
  - the handwritten de-integration date: 0 → 2;
  - TP7 expected thrust: 0 → 2;
  - "show me the mesh photos": 0 → 2;
  - RevC overall length: 1 → 2.
- **Worse:** debug max runs 2 → 1 (one wrong synthesis; the planner chose the source route both times).
- **The planner chose a correct route in 62 of 62 runs with a labelled route.** The table cases were
  answered by other routes and still passed.
- **One correction during the run.** The visual route first called only the photo tool, and both photo
  questions failed (2 → 0). It now also searches text, preferring photo, figure and video pieces, and the
  Skill "visual lookup" says so. After the fix both were back at 2/2.

**Full silver, 82 cases × 2, against `after_final.jsonl`: 129 → 133/164.**

| Route | Before | After |
|---|---|---|
| document | 32/42 | 35/42 |
| visual | 28/32 | 30/32 |
| diagram | 13/14 | 14/14 |
| source | 18/24 | 16/24 |
| library, measured, table | 12, 10, 12 | unchanged |

- **Routing:** the planner chose a correct route in 156 of 160 labelled runs.
- **Passed both repeats:** 63 → 65. No case that passed both before fails both now.
- **Speed:** median 35.5 s.
- **The source drop, two runs, is not caused by the change.** In `debug-max-runs` and `inj10-excel-close`,
  one run each failed with a correct answer: "at most 1 pdflatex pass" without the variable name, and a claim
  judged once unsupported. Both runs retrieved the same 16 pieces in the same order as the passing runs.
- **Kept.**
- **Still failing, outside routing** (`PLAN_route_outputs.md`):
  - xlwings: `requirements.txt` not in the plain search's top 30 (O5);
  - LabJack scan rates: no unit (D1);
  - Injector 10 schematic: empty reading (O2).
- **Deployed to the api;** checked in Open WebUI ("show me the mesh photos": photos, readings, citations).

## 6. Measurement

- **Silver run** (`route_run.py`, `summarise.py`), compared case by case.
- **Search-only probe** (`types_probe.py`): image share per route and rerank drops. Free; run before and
  after every step.
- **Routing on its own:** the benchmark's tool and route-hit fields per case (already reported).
- **Meeting cases:** 3–5 silver cases once the test recording is synced.

## 7. Open decisions

- **T1 Test requirements that fail right answers** (9 runs). (a) Make the expected-tool check
  report-only, like the route hit. (b) Accept a citation of any indexed file that holds the same value. (c)
  Keep both and treat the cases as engine work (prefer the primary source; call the photo tool and search).
- **T2 Per-type slots** (R5): only if a displacement remains after O2 and R1–R3, or as a planned step now.
- **T3 Planner prompt v4** (Appendix A): history says prompt-only planner changes moved nothing (Step 2,
  Step 3.0); R4 is kept small (two names and one line) and measured on its own.

## 8. Parked

- Answer-time behaviours: 4 halted-data and 3 not-available cases (the engine answers instead of saying
  "under review" or "not in our files").
- The handwritten de-integration date is read wrong (A1 page reading).
- Visual vectors for figure crops ([R10]); today only photos and figures carry image vectors used by the photo
  tool.
- A graph for drawings read from images ([R16], [R17]).
- Answers label a video source "internal report".

## Appendix A: planner prompt v4 (changes against v3 only)

`query_analysis.v4.md` keeps v3 and changes three lines:

- **filters.doc_kinds list:** add `video_transcript` after `video_timeline`.
- **filters.node_types list:** becomes "table, figure, photo, video_event, transcript_window,
  diagram_summary, run_summary, code_symbol, config".
- **New line after `needs_visuals`:** "A question about what was said or decided in a meeting, discussion,
  workshop or other recording is about its transcript: set doc_kinds video_transcript and node_types
  transcript_window."

The reframed question stays as in v3. Step 2 (searching the user's words beside the rewrite) added 3.3 s
per answer without gain, and Step 3.0 (the AI naming routes) changed no search. A fuller "descriptive
rewrite" is therefore not in R4. If wanted, it is its own step with its own check (decision T3).

## Sources

- [R1] UniversalRAG, https://arxiv.org/html/2504.20734
- [R2] MM-Embed, https://arxiv.org/abs/2411.02571
- [R3] LlamaIndex multimodal retrieval, https://developers.llamaindex.ai/python/examples/multi_modal/multi_modal_retrieval/
- [R4] Azure AI Search multimodal overview, https://learn.microsoft.com/azure/search/multimodal-search-overview
- [R5] mmRAG, https://arxiv.org/html/2505.11180
- [R6] RAGRouter-Bench, https://arxiv.org/html/2604.03455v1
- [R7] Anthropic, Building effective agents, https://www.anthropic.com/engineering/building-effective-agents
- [R8] UniRank, https://arxiv.org/html/2603.29897v1
- [R9] Cohere reranking best practices, https://docs.cohere.com/docs/reranking-best-practices
- [R10] ColPali, https://arxiv.org/html/2407.01449v5
- [R11] VisRAG, https://arxiv.org/html/2410.10594v2
- [R12] M3DocRAG, https://arxiv.org/html/2411.04952v1
- [R13] VideoRAG, https://arxiv.org/html/2501.05874v3
- [R14] Video-RAG, https://arxiv.org/html/2411.13093v4
- [R15] Cohere chunking strategies, https://docs.cohere.com/page/chunking-strategies
- [R16] ChatP&ID, https://arxiv.org/html/2603.22528
- [R17] Vector CAD to graph, https://arxiv.org/html/2602.11678
- Also used: Anthropic contextual retrieval (rerank depth), https://www.anthropic.com/news/contextual-retrieval;
  Elastic RRF, https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion
