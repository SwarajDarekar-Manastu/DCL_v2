# Route A1: PDF, DOCX, PPTX, PPT

| Field | Value |
|-------|-------|
| Feature id | `backend/route-a1-office` |
| Status | in-progress |
| Owner session | S2 |
| Spec | docs/architecture/03_phase2_processing_routes.md §4 |
| Last updated | 2026-10-22 |

## Purpose

Pre-flight, page triage with language/script, Docling by script group, tables QA with VLM A/B, equations, figure classification, handwriting regions, DOCX/PPTX specifics, section tree, PDF twin page map, library-document specifics.

## Location

Code:
- `backend/routes/a1_office/preflight.py` (A1.1: `preflight`, `Preflight`, `PageSignals`, `PreflightFailure`, `garbage_ratio`, `windows`, `render_page`)
- `backend/routes/a1_office/triage.py` (A1.2: `triage_pages`, `PageDecision`, `combine`, `ocr_groups`, `DEFAULT_OCR_ENGINE_BY_SCRIPT`)
- `backend/routes/a1_office/convert.py` (A1.3: `plan_runs`, `Run`, `OcrPlan`, `pipeline_options`, `convert_run`, `low_ocr_pages`)
- `backend/routes/a1_office/structure.py` (A1.3/A1.11/A1.12: `build_structure` → route nodes, breadcrumbs, references as mentions, furniture)
- `backend/routes/a1_office/metadata.py` (L1 for PDFs: `extract_metadata` → `DocumentFields` + SENSITIVE_CONTENT flags; DOI/arXiv/ISBN, running head, copyright, vendors with the internal-equipment rule, markings, standard id, kind rules, tier, locale)
- `backend/routes/a1_office/figures.py` (A1.6: `read_figures`; plots, schematics, photos, table images, skip list, crops as assets)
- `backend/routes/a1_office/tables_qa.py` (A1.4: spans grid, units per column, QA reasons, VLM A/B with agreement, flag with both versions)
- `backend/routes/a1_office/handwriting.py` (A1.7: regions, nearest label, transcription node after its label, SOFT/HARD by critical field)
- `backend/routes/a1_office/route.py` (`process_pdf` → `ProcessedDocument`; second OCR pass, `transcribe_page`, page renders, CIR keys)
- planned: visual twin and page map (A1.0), DOCX/PPTX (A1.9–A1.10), rotation fix before OCR, checkbox-state call

Tests and fixtures:
- `backend/tests/unit/routes/a1_office/` (reads S5's `backend/tests/fixtures/a1_office/`)

## Interfaces

Provides:
- `preflight(pdf_bytes) -> Preflight(page_count, repaired, pages, windows)`; `PreflightFailure.reason` (`encrypted`, `unrepairable`, `no_pages`) for the PARSE_FAILURE flag
- `triage_pages(preflight, vision, context=, doc_id=, cloud_allowed=, engine_by_script=) -> list[PageDecision]`; `PageDecision.meta()` is the triage part of `pages/{n}.meta.json`
- `ocr_groups(decisions)` → pages per (engine, language); `plan_runs(decisions)` → contiguous `Run`s with one OCR plan each
- `convert_run(pdf_bytes, run) -> RunResult(document, page_confidence)` (CPU, TableFormer accurate, no remote services)
- `build_structure(documents, pages, fallback_title=) -> Structure(nodes, mentions, furniture, title, references)`: one `child` node per paragraph with page and 0..1 top-left `PageBox`, `table` HTML nodes, `figure` placeholders; references → `reference` mentions on the first text node
- `process_pdf(pdf_bytes, blob_sha256=, file_name=, folder: FolderContext, vision=, stores=Stores(put_cir, put_asset), cloud_allowed=, doc_id=, critical_field_patterns=, engine_by_script=) -> ProcessedDocument` (PARSE_FAILURE HARD document on a failed pre-flight)
- `plan_conflicts(folder, furniture_by_page, first_page_text) -> list[Flag]` (`metadata.py`, file 03 §A1.3 as amended 2026-10-22): the dispatcher's plan patterns over page furniture (Docling's headers and footers; `transcribe_page.v2`'s `furniture` for transcribed pages) and page-1 text; an id other than the folder's raises `CONFLICT` SOFT `{subject: test_plan_id, a: folder value and its source, b: printed value, page, line}` once per id; the folder value stays `test_plan_id`
- A Gemini error on `transcribe_page` (a safety block on propellant chemistry, an outage) keeps the OCR text and raises `LOW_CONFIDENCE_EXTRACTION` SOFT for the page (pass `transcribe_failed`) instead of failing the document
- CIR under `dcl-cir/{sha256}/A1/v1/`: `docling/{first}-{last}.json`, `pages/{n}.txt`, `pages/{n}.meta.json`, `page_hashes.json`; assets `pages/{sha}/{page:04d}.png` (150 dpi), `figures/…`, `crops/…` (300 dpi)
- OCR: Tesseract script models (`Latin`, `Cyrillic`, `Devanagari`, `Arabic`) and RapidOCR in S4's parse image

Consumes:
- `backend/vision-service` (`triage_page`)
- pypdfium2, pikepdf, docling 2.141.0 (`parse` group); Docling models from Hugging Face (`HF_HUB_DISABLE_XET=1` on this network)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/routes/a1_office/`
- `backend/tests/unit/routes/a1_office/`
- `backend/tests/fixtures/a1_office/` (S5's, read only)

## Rubric (what "done" means for this feature)

- [ ] Page types correct ≥95% on the SME set
- [ ] Handwritten values ≥90% correct with calibrated confidence
- [ ] Non-English scanned pages OCR'd with the engine chosen by script
- [ ] Citations open the right page and bbox
- [ ] Reference lists of papers are mentions, not body nodes
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | S2 | Owner-password PDFs (open without a password; the 8 ECSS standards) decrypted in memory and processed, `Preflight.decrypted`; PARSE_FAILURE only when a user password is needed (file 03 §A1.1 amended); 1 test |
| 2026-10-23 | S2 | NUL bytes stripped from every string of the output (`without_nul`; an Elsevier paper's text layer made the commit fail); 1 test |
| 2026-10-23 | S2 | Docling converters cached per OCR plan in the worker (measured in the parse worker: text layer 13.1 s → 2.1 s, Tesseract 5.9 s → 3.7 s per run; two converters peak 2.2 GB); Docling's OSD "Too few characters" error on near-empty scanned pages logged as INFO (OCR proceeds with the explicit script model; seen on doc 1539b6b4, the Rafael valves datasheet); 1 test |
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | Page furniture kept for the plan extractor (`transcribe_page.v2`), test-plan `CONFLICT` from furniture / page-1 text, blocked transcription degrades to OCR; 6 tests |
| 2026-10-22 | S2 | Figures, tables QA, handwriting and `process_pdf` assembly; Tesseract script models; 38 tests (route tests run real Docling on S5's digital fixtures) |
| 2026-10-22 | S2 | A1 metadata scan (origin overrides, markings, kind, tier, locale); 11 tests |
| 2026-10-22 | S2 | Docling runs by OCR plan and the structure mapping (breadcrumbs, references as mentions, furniture, tables, figure placeholders); 15 tests, Docling ones skip without cached models |
| 2026-10-22 | S2 | Pre-flight (encryption, repair, density, Unicode-aware garbage ratio, windows) and page triage (signals bound the model, OCR engine by script, no-cloud path); 19 tests on S5's fixtures |

## Related

- `.wiki/index.md`
