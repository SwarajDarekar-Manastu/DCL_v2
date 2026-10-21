# Test fixtures (owner: S5, feature `quality/fixtures`)

Layout: `backend/tests/fixtures/<route>/<fixture>/` holds the fixture file(s) and one
`expected.yaml`. Route folders: `dispatcher`, `a1_office`, `a2_source`, `b_code`,
`c_telemetry`, `d_photos`, `e_diagrams`, `f_video`, `g_archives`.

Two kinds of fixtures:

- **synthetic**: produced by `make_synthetic.py` (fictitious content only). Regenerate with
  `uv run python backend/tests/fixtures/make_synthetic.py`; the integrity test checks that
  regeneration reproduces every fixture marked `byte_stable: true`.
- **real**: small copies of corpus files chosen from the allowlisted folders and approved by
  the user. Nothing proprietary or export-controlled is ever copied here.

Some fixtures are deliberately hostile (`c_telemetry/malicious_pickle`, `g_archives/*`). Never
`pickle.load` a fixture and never extract an archive fixture outside a guarded test.

## expected.yaml

| Field | Meaning |
|-------|---------|
| `fixture`, `edge_case`, `origin`, `generator`, `byte_stable` | identity; `origin` is `synthetic` or `real` |
| `files` | the fixture files, relative to the fixture folder |
| `simulated_location` | `{root, folder}` the pipeline test must use as the OneDrive location (folder context, source-origin default). Assumes the folder is in `processing.scope` and the route is enabled |
| `spec` | manual sections that prescribe the outcome |
| `expected.route` | `A1` … `G`, or `null` when no adapter exists |
| `expected.detected_mime` | type resolution result (content wins over extension) |
| `expected.documents` | number of logical documents (default 1) |
| `expected.document_status` | `ACTIVE`, `ACTIVE_WITH_SOFT_FLAGS`, `HALTED`, `WAITING_FOR_ROUTE`, `QUARANTINED` |
| `expected.flags` | flags that must be raised: `{type, severity, reason}`; `flags_exact: true` means no other flag may appear |
| `expected.metadata` | L1/L2 document fields that must hold (language, source_origin, trust_tier, doc_kind, …) |
| `expected.text_contains` | strings present in the file's text layer (checked by the integrity test) |
| `expected.ocr_text_contains` | strings the pipeline must recover by OCR (image-only pages; not checkable here) |
| `expected.numeric_facts` | `{quantity, value, unit, source?}` the pipeline must extract (`source` for external documents: `vendor_claim`, `literature`) |
| `expected.never` | actions the pipeline must never take on this file |
| `open_questions` | points where the manual is ambiguous; raised with DCL Lead |

These expectations are at document level. CIR snapshot comparisons are added once S1
publishes the CIR snapshot format.
