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
- planned: second OCR pass and `transcribe_page`, tables QA (A1.4), figures (A1.6), handwriting (A1.7), page map (A1.0), metadata scan and assembly into `ProcessedDocument`

Tests and fixtures:
- `backend/tests/unit/routes/a1_office/` (reads S5's `backend/tests/fixtures/a1_office/`)

## Interfaces

Provides:
- `preflight(pdf_bytes) -> Preflight(page_count, repaired, pages, windows)`; `PreflightFailure.reason` (`encrypted`, `unrepairable`, `no_pages`) for the PARSE_FAILURE flag
- `triage_pages(preflight, vision, context=, doc_id=, cloud_allowed=, engine_by_script=) -> list[PageDecision]`; `PageDecision.meta()` is the triage part of `pages/{n}.meta.json`
- `ocr_groups(decisions)` → pages per (engine, language); `plan_runs(decisions)` → contiguous `Run`s with one OCR plan each
- `convert_run(pdf_bytes, run) -> RunResult(document, page_confidence)` (CPU, TableFormer accurate, no remote services)
- `build_structure(documents, pages, fallback_title=) -> Structure(nodes, mentions, furniture, title, references)`: one `child` node per paragraph with page and 0..1 top-left `PageBox`, `table` HTML nodes, `figure` placeholders; references → `reference` mentions on the first text node
- later: page/table/figure/handwriting nodes, page renders and crops as assets

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
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-22 | S2 | A1 metadata scan (origin overrides, markings, kind, tier, locale); 11 tests |
| 2026-10-22 | S2 | Docling runs by OCR plan and the structure mapping (breadcrumbs, references as mentions, furniture, tables, figure placeholders); 15 tests, Docling ones skip without cached models |
| 2026-10-22 | S2 | Pre-flight (encryption, repair, density, Unicode-aware garbage ratio, windows) and page triage (signals bound the model, OCR engine by script, no-cloud path); 19 tests on S5's fixtures |

## Related

- `.wiki/index.md`
