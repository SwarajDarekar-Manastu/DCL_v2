# Plan: quality/fixtures — propose the processing.scope allowlist

| Field | Value |
|-------|-------|
| Feature | `quality/fixtures` (map: `.wiki/quality/fixtures.md`) |
| Session | S5 |
| Branch | claude/strange-bhaskara-1dd439 |
| Opened | 2026-10-21 |
| Delete when | every slot has a folder chosen from S1's crawl and DCL Lead has recorded the table in DECISIONS.md |

## Intent

Choose the allowlist of real OneDrive folders for `pipeline_config.processing.scope` (file 10 §3, §10 item 1; file 02 §3.1a; decision H11). Decision 2026-10-21 (DECISIONS.md): the user delegates the choice to S5, no approval step. S5 fills the 13 slots from S1's folder-level listing of the real metadata crawl, by the criteria below, preferring small folders. No repository file other than this sheet, the index row and STATUS.md changes. The scope value itself is written to `pipeline_config` by S1 at M1; this task only agrees the list.

## Workspace

Files to read:
- docs/architecture/10_development_plan.md §3, §5 (M1, M2, M5, M7 accept), §7, §10
- docs/architecture/02_phase1_ingestion_sync.md §3.1a
- docs/architecture/03_phase2_processing_routes.md (route edge cases)

Files to change (exact):
- `.wiki/plans/quality__fixtures__allowlist.md` (this sheet)
- `.wiki/index.md` (Active plan sheets row)
- `docs/sessions/STATUS.md` (append)

Files explicitly out of scope:
- `docs/sessions/DECISIONS.md` (Lead writes the agreed list)
- `pipeline_config` seed / `backend/sync/scope.py` (S1)

## Slots

Entry format: root + folder path relative to the root + Graph folder id (from the crawl). One folder may fill several slots. Tie-break: fewest accepted files, then most slots filled.

| # | Slot | Root | Criteria the folder must meet | Feeds |
|---|------|------|-------------------------------|-------|
| 1 | Test-plan folder, APU Injector | APU Injector | `.dat` runs with their `.cfg` (several runs, one channel map); pressure channels | M2 Route C, telemetry cases |
| 2 | Test-plan folder, APU | APU | a full test plan: `.dat`+`.cfg`, the report, ideally the JSON section set | M2 Route C, A2 |
| 3 | Test-plan folder, APU Heater | APU Heater | `.dat`/`.tdms` runs with temperature channels | M2 Route C |
| 4 | Optional 2nd test-plan folder (any root) | any | adds a `.tdms` or a `.dat_fail` if slots 1–3 lack them | M2 Route C |
| 5 | A `.dat_fail` run | any | must sit in one of slots 1–4 (only 2 exist in the corpus) | failed-run handling |
| 6 | Handwritten run sheets | any | scanned PDFs of test-cell run sheets with pen entries, ideally including a calibration/tare value (critical field) | M5 handwriting ≥ 90% |
| 7 | LaTeX project + compiled PDF | any | master `.tex` with `\documentclass`, at least one `\input`/`\include`, figures, and the compiled PDF with the same stem | A2 assembly, A1.0 visual twin, page map |
| 8 | FMEA workbook | any | `.xlsx` FMEA/risk register (matrix table, ideally with merged cells or several islands) | C.4 matrix tables, row children |
| 9 | HEIC photos | any | a photo folder with `.heic`, ideally post-test hardware and a burst of shots within 60 s | M7 Route D, burst clustering |
| 10 | Rev C diagram | any | the thruster configuration Rev C `.drawio` | M7 Route E path queries |
| 11 | One test video | any | short test-cell camera video; best if its run's telemetry is in slots 1–4 | M7 t0 within 0.5 s |
| 12 | One `.npy` | any | a `.npy` array (file 06 example: `APU Heater/Test Plan 30/T01.npy`) | SCHEMA_UNKNOWN HARD path |
| 13 | Library folder | APS - Library | ≥ 2 non-English brochures/datasheets (German preferred) and ≥ 1 paper with a DOI on page 1 | A1.12, MULTILINGUAL, LIBRARY_VS_INTERNAL |

Answers from DCL Lead (2026-10-21):
- Q1 unanswered: telemetry benchmark numbers are verified with S5's own Python over the raw `.dat`, not Excel.
- Q2 unanswered: assume nothing is marked; rely on the Tier-4 marking scan; nothing proprietary enters git.

Listing requested from S1 (per folder): root, path, Graph folder id, accepted-file counts by extension, and presence of `.cfg`, `.dat_fail`, `.tdms`, `.heic`, `.drawio` (and "Rev C" in a name), `.tex` containing `\documentclass` with a same-stem `.pdf`, `.npy`, `.mp4`/`.mov` with size, `.xlsx` with FMEA/Risk in the name; for `APS - Library` PDFs, title/filename language hints and a DOI on page 1 if known from metadata.

## Steps

1. Draft the slot table (done; sent to DCL Lead 2026-10-21).
2. Ask DCL S1 Backend for the folder-level listing once the crawl exists; stay idle until it arrives.
3. Match folders to slots by the criteria; build the table with a reason per slot; report unfillable slots.
4. Send the table to DCL Lead for DECISIONS.md; update `.wiki/quality/fixtures.md`; delete this sheet and its index row.

## Rubric for this task

- [ ] Every one of the 13 slots has a root + folder path + folder id chosen from the crawl listing, with the matching evidence
- [ ] Slots 5 and 12 point inside a named folder or a folder of their own
- [ ] DECISIONS.md "Allowlist folders" row no longer `pending` (Lead)
- [ ] Map page change log updated; this sheet and its index row deleted

## Verification commands

```bash
grep -n "Allowlist folders" docs/sessions/DECISIONS.md
test ! -e .wiki/plans/quality__fixtures__allowlist.md
```

## Risks and open questions

- A slot the corpus cannot fill (for example no HEIC in any test folder) is reported back to the Lead, not substituted silently.

## Proposed allowlist from S1's crawl listing (2026-10-22)

Source: S1 folder listing of the real metadata crawl (872 folders, 814 library PDFs; kept outside git). A folder-id entry covers its whole subtree (`backend/sync/scope.py`). 11 entries, about 247 accepted files.

| # | Root | Folder (relative to root) | Folder id | Files | Slots filled | Evidence |
|---|------|---------------------------|-----------|-------|--------------|----------|
| E1 | APU Injector | 29122025 - Injector 10 Cold flow test | 01RDWVU44XRPVPLV7YQRAL5CUFXNI7FPRO | 29 | 1 | `.cfg` 3 + `.dat` 3 in Pressure/, report sources (.tex 14), .xlsx 3 |
| E2 | APU Injector | Injector 14/13012026 - Flow Test (No Mesh) Injector 14/Pressure_Data_Files | 01RDWVU42EH7Y5QREJ4JG2L4QNOWGWUFOJ | 22 | 4, 5 | the only `.dat_fail` folder (2 files) + 10 `.dat`; no `.cfg` (header-only channel map) |
| E3 | APU | Test Campaign 2/Test Plan 7/APU-Firing | 01RDWVU46OPFLY26YAGREI7G3A6ZIH5CTW | 79 | 2, 4 | `.cfg`+`.dat` (Pressure/), the only `.tdms` (Temperature/), LaTeX Main_Files + Sections (.tex 25) with JSON sections (11), PDF report, Test_analysed_data .xlsx, photos, 3.7 MB video; the manual's own example question (TP7) |
| E4 | APU | Test Campaign 1/Test Plan 12/APU - Firing | 01RDWVU42SMG6ALQAFJJG3LSYXU56T7OWJ | 71 | 6, 7 | `Test_plan.tex` with same-stem PDF; Catalyst Sheet/ and Integration Sheet/ scanned-sheet PDFs (handwriting probable, unverified) |
| E5 | APU | Test Campaign 2/Test Plan 23 | 01RDWVU4ZM5TFKN7MZAJELC4TBIG5UGDC7 | 5 | 8 | the only FMEA/risk workbook (Cooling Duct Risk Assesment.xlsx), plus .drawio, .docx, .pdf |
| E6 | APU | Test Campaign 2/Test Plan 22 | 01RDWVU43XKEVJHLVPJZCLWXDUB6B74OPS | 1 | 10 | the only `.drawio` with "Rev C" |
| E7 | APU | Test Campaign 2/Test Plan 9/APU - Firing/Figures/De-Integration | 01RDWVU4YQX7G7T47P6BALUPKS3BEEP5PC | 20 | 9 | 19 `.heic` post-test hardware (largest HEIC set, bursts likely) + one 7.9 MB `.mov` |
| E8 | APU | Test Campaign 1/Test Plan 01/30052025 - Test Videos/Front camera/Hot Firing | 01RDWVU44OZM3GH2XQMFHKUXPTAUSOLEWZ | 2 | 11 | test-cell hot-firing camera videos (94 and 127 MB); no telemetry of this run is in the corpus |
| E9 | APU Heater | Ground Test Heaters/450W Heater | 01RDWVU456WS3UXHOXIZF24ZSU7WERYGG3 | 4 | 3 (substitute) | APU Heater has no telemetry at all (only .docx); heater plans represent the root and cover DOCX |
| E10 | APS - Library | Similar Products Datasheets | 01RDWVU46A6HDMZK253RBYAULGDACN2PZZ | 11 | 13 (vendor half) | vendor datasheets and brochures (Moog, ArianeGroup, Bradford ECAPS, Rafael, MT Aerospace, Agena) |
| E11 | APS - Library | Preheat | 01RDWVU457TPDUS3AFZZH3RTJTFZV2FOHJ | 3 | 13 (DOI half) | three papers named by their DOI suffix (AIAA 1.B35489, Hindawi 2015/584538, Elsevier j.ijheatmasstransfer.2019.03.009) |

Unfillable or unverified:
- Slot 12 (`.npy`): no accepted `.npy` exists; all 6 are under `APU/Test Campaign 2/Test Plan 30/_to_delete` and quarantined by the gate. Proposal: drop the slot; cover the SCHEMA_UNKNOWN HARD path with a synthetic `.npy` fixture.
- Slot 3 criterion (temperature telemetry under APU Heater): not in the corpus; temperature telemetry is covered by E3 (`.tdms`, `.csv`).
- Slot 13 non-English brochures: no library file name is non-English; content is needed. Proposal: S1 adds a first-page language and DOI check over the downloaded library PDFs; any non-English folder found is added as E12.
- Slot 6 handwriting: probable from the folder names, confirmed only after download.
- Slot 11: no video has telemetry of the same run, so the M7 "video t0 within 0.5 s of telemetry t0" check has no real pair in this set.
