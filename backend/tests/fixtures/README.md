# Test fixtures (owner: S5, feature `quality/fixtures`)

Layout: `backend/tests/fixtures/<route>/<fixture>/` holds the fixture file(s) and one
`expected.yaml`. Route folders: `dispatcher`, `a1_office`, `a2_source`, `b_code`,
`c_telemetry`, `d_photos`, `e_diagrams`, `f_video`, `g_archives`.

Two kinds of fixtures:

- **synthetic**: produced by `make_synthetic.py` (fictitious content only). Regenerate with
  `uv run python backend/tests/fixtures/make_synthetic.py`; the integrity test checks that
  regeneration reproduces every fixture marked `byte_stable: true`.
- **real**: corpus files from the allowlisted folders. The repository is public, so real files
  are **never committed** (DECISIONS.md 2026-10-22). They live in the git-ignored `data/samples/`.
  The committed `real_samples.template.yaml` lists them without file names (entry, registry
  sha256, size, route, purpose); the full manifest with paths is the git-ignored
  `data/samples/real_samples.yaml`.

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

## Local real samples (never committed)

`real_samples.template.yaml` lists 91 distinct files (about 400 MB) from the allowlist entries E1–E11 of
DECISIONS.md: the E1–E3 telemetry used to verify the benchmark cases, one real file per format
for every route, and the library PDFs (third-party copyright). Copy them from MinIO with S1's
read-only export, one directory per entry. `export_blobs` reads its settings from `os.environ`,
so the stack's `.env` must be loaded first; only an operator has it. From the main checkout:

```bash
alias export_blobs='uv run python -c "import runpy, sys; from dotenv import load_dotenv; load_dotenv(\".env\"); sys.argv[0] = \"export_blobs\"; runpy.run_module(\"backend.sync.export_blobs\", run_name=\"__main__\")"'
export_blobs --folder-id 01RDWVU44XRPVPLV7YQRAL5CUFXNI7FPRO data/samples/E1
export_blobs --folder-id 01RDWVU42EH7Y5QREJ4JG2L4QNOWGWUFOJ data/samples/E2
export_blobs --folder-id 01RDWVU46OPFLY26YAGREI7G3A6ZIH5CTW data/samples/E3
export_blobs --folder-id 01RDWVU42SMG6ALQAFJJG3LSYXU56T7OWJ data/samples/E4
export_blobs --folder-id 01RDWVU4ZM5TFKN7MZAJELC4TBIG5UGDC7 data/samples/E5
export_blobs --folder-id 01RDWVU43XKEVJHLVPJZCLWXDUB6B74OPS data/samples/E6
export_blobs --folder-id 01RDWVU4YQX7G7T47P6BALUPKS3BEEP5PC data/samples/E7
export_blobs --folder-id 01RDWVU44OZM3GH2XQMFHKUXPTAUSOLEWZ data/samples/E8
export_blobs --folder-id 01RDWVU46A6HDMZK253RBYAULGDACN2PZZ data/samples/E10
export_blobs --folder-id 01RDWVU457TPDUS3AFZZH3RTJTFZV2FOHJ data/samples/E11
```

The output paths are relative to the main checkout; prefix them with another worktree's path to
export there. The export copies whole subtrees (more files than the template; E3 includes a
613 MB run that no test uses). `uv run pytest backend/tests/fixtures/test_real_samples.py` then
finds every template file by sha256 in its entry directory and checks the size; entries not
exported are skipped. `data/` is git-ignored at the repository root; never move a real sample elsewhere.
