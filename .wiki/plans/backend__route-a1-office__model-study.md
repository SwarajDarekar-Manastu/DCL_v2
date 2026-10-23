# Plan: backend/route-a1-office — document-model comparison study

| Field | Value |
|-------|-------|
| Feature | `backend/route-a1-office` (map: `.wiki/backend/route-a1-office.md`), `backend/vision-service` |
| Session | S2 (runs it), S5 (gold) |
| Branch | claude/infallible-swartz-58c96b |
| Opened | 2026-10-23 |
| Decision | DECISIONS 2026-10-23 (4b4d3c5): model choice settled by a study on our own pages; the winner per job is the default, the loser the configured fallback; a preview id is never the only option |
| Delete when | the five jobs are scored, the defaults are set in config, the map pages are updated |

## Intent

Measure, on our own pages and against S5's gold, which model does each of five document jobs best, at what cost and time, and make the measured winner the default with the other as the configured fallback. Nothing in the production path changes until the numbers are in and the Lead has accepted them; the study code and its third-party models stay out of the parse image unless a winner needs them.

## The five jobs

| Job | Candidates | Pages / items (S5 gold) | Primary metric | Secondary |
|-----|-----------|-------------------------|----------------|-----------|
| (a) Layout regions | Docling layout model (as in A1 today) vs PP-DocLayoutV3 (PaddleX, CPU) | ~30 pages: report pages with tables and figures, ECSS pages with equations, brochure pages, TP7 sheets with handwriting, one rotated scan | per-class precision and recall at IoU ≥ 0.5 (table, figure, equation, caption, handwriting, section header, text), one-to-one matching per page and class | mean IoU of matched boxes; boxes that cross a column (the crop bleed of 2026-10-23); seconds per page on CPU |
| (b) Tables | Docling TableFormer ACCURATE vs gemini-3.8-flash reading the table crop (200 dpi) plus the PDF characters inside the box | ~25 tables, at least 6 each borderless, merged-cell, rotated, plus 5 plain | cell accuracy: share of gold cells whose text matches after whitespace and number normalisation, by position | TEDS (tree-edit similarity of the HTML); numeric cells exact; header rows right; seconds and tokens per table |
| (c) Equations | the `.tex` source where a twin exists (ground truth itself, no model); otherwise Docling CodeFormula vs UniMERNet (CPU) | ~40 equations from ECSS pages and the DOI paper; gold LaTeX from the `.tex` twins and S5's transcriptions | exact match after LaTeX normalisation (spacing, `\left`/`\right`, braces, `\mathrm` vs text) | normalised edit distance; rendered-image match on disagreements; seconds per formula (CodeFormula measured at ~30 s on CPU) |
| (d) Handwriting | gemini-3.8-flash at media resolution medium vs high; gemini-3.1-pro-preview at high as a candidate | S5's two TP7 sheets plus the other handwritten run sheets: ~40 regions with gold values, units and illegible marks | exact value (after unit and decimal normalisation) | character error rate; illegible called correctly; confidence calibration (expected calibration error); tokens and seconds per region |
| (e) Charts | `digitize_plot` on gemini-3.8-flash vs Docling's chart extraction | ~15 line/bar/scatter plots with gold key points (S5 reads them from the source data or the plot grid) | key points within 2 % of the axis range | axis labels and units right; series count right; seconds and tokens per chart |

Decision rule per job: the higher primary metric wins; within 2 points the cheaper or faster one wins. A preview id (gemini-3.1-pro-preview) can win only with a GA model configured as the tested fallback, so a retired id never stops a route.

## Where the code and results go

- Study driver: `backend/llm_engine/vision/study.py` (S2; one function per job, each returning per-item rows) and a CLI that writes `data/benchmark/doc_models/{job}.jsonl` and `summary.json` (git-ignored, like the golden values; S5's gold lives there too).
- Gold format (to agree with S5): per page `{sha256, page_no, regions[{class, bbox 0..1}]}`; per table the gold HTML; per equation the gold LaTeX; per handwriting region `{bbox, value, unit, illegible}`; per chart `{series[{name, points[[x, y]]}], x_axis, y_axis}`.
- Gemini calls go through the gateway client with prompt versions as today (`read_table_image.v1`, `transcribe_handwriting.v1`, `digitize_plot.v1`); `llm_calls` rows (once S1's table exists) carry purpose `study.*`.

## Packages (pins requested, study only)

Both conflict with the parse group, so they run in isolated, throwaway environments (`uv run --isolated --with …`) on the stack host, never in `pyproject.toml` or an image until one wins:
- PP-DocLayoutV3: `paddlex==3.7.2` with `paddlepaddle==3.3.1` (CPU wheel, cp312 manylinux). paddlex pins `PyYAML==6.0.2` and `numpy<2.4`.
- UniMERNet: `unimernet==0.2.3` (last release 2024-12-26). It pins `transformers==4.42.4`, which conflicts with Docling's transformers, and needs `torch>=2.2.2` (CPU build) and ImageMagick through `wand`.
- If a winner needs one of them in production, I come back with a pin request for the parse group or a separate worker image.

## Cost and time (estimate, before running)

| Job | Model calls | Tokens (approx.) | CPU time |
|-----|-------------|------------------|----------|
| (a) | none | 0 | 30 pages × 2 models ≈ 5 min, plus PaddleX model download (~200 MB) |
| (b) | 25 × gemini-3.8-flash | ~5k per table → ~125k | TableFormer ~25 tables ≈ 5 min |
| (c) | none | 0 | CodeFormula 40 × ~30 s ≈ 20 min; UniMERNet 40 × ~5–10 s ≈ 5 min |
| (d) | 40 regions × 3 configurations = 120 | ~2–3k per call → ~300k | — |
| (e) | 15 × gemini-3.8-flash | ~4k per chart → ~60k | Docling chart extraction ≈ 5 min |

About 500k Gemini tokens in all, and about 45 minutes of CPU on the stack host, run outside the cpu_parse worker so the A1 re-run is not slowed. Each job runs once; a rerun only after a gold correction.

## Steps

1. Agree the gold format with S5; S5 delivers gold per job (they are preparing it now).
2. Probe the gateway for gemini-3.1-pro-preview (one call; record the id and GA fallback).
3. Write `study.py` with unit tests on two hand-made items per job (metrics checked against hand-computed values).
4. Run (a)–(e) on the stack host; write `summary.json`; one table per job with the primary and secondary metrics, cost and time.
5. Send the numbers to the Lead; on acceptance, set the defaults and fallbacks in config (`pipeline_config` keys per job, proposed with the numbers), update the map pages, delete this sheet.

## Rubric

- [ ] Gold format agreed with S5; item counts per job as in the table above (or the shortfall stated)
- [ ] Metrics unit-tested against hand-computed values
- [ ] Every job scored for every candidate, with cost and seconds per item
- [ ] Results and gold stay git-ignored; no new dependency in `pyproject.toml` or an image
- [ ] Winner and fallback per job proposed to the Lead with the numbers; a preview model never configured alone

## Risks and open questions

- (Lead) Accept running PaddleX and UniMERNet in isolated environments on the stack host for the study only?
- (Lead) Accept `backend/llm_engine/vision/study.py` as the study's home and `data/benchmark/doc_models/` for gold and results?
- (S5) Rotated tables and handwriting regions are the scarcest; if fewer than six rotated tables exist, the table result is reported per type with the count.
- Docling's chart extraction may not exist for every chart class; a chart it skips is scored as missed.
