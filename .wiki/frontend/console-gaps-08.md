# Console against file 08: what the manual names that the Console lacks

| Field | Value |
|-------|-------|
| Purpose | Tracking list for the build-out command (DECISIONS 2026-10-23): every function file 08 names that the Console does not have yet, in manual order, with what blocks it |
| Owner session | S3 |
| Spec | docs/architecture/08_frontend_openwebui.md §3.2, §4.2, §4.4, §5.5, §6 |
| Last updated | 2026-10-23 |

Status: **build** = S3 builds it now (one merge request each, in this order); **API** = the Console part waits for another session's API (the Console calls it as soon as it exists); **done** = shipped.

| # | § | Function the manual names | Console today | Status |
|---|---|---------------------------|---------------|--------|
| 1 | 3.2 | "Rollback to version" per **section** | per key and per section | done 2026-10-23 |
| 2 | 3.2 Sources | roots, auth status, "start device-code sign-in", webhook status, live counts (items held, blobs waiting), "download/process everything" with Gemini cost | scope keys edit with preview counts; cost shown when S1 returns it | API: S1 sync/ops routes (`backend/api/sync.py` has none); cost needs S1's llm_calls price ledger |
| 3 | 3.2 Routes | "re-process affected documents" button with count | `routes.<X>.enabled` edit with S1's parked-count preview | API: S1 re-dispatch route |
| 4 | 3.2 Models | "requires re-embedding N nodes" before an embedding-model change | generic JSON edit, no impact | API: S1/S2 impact for `models.*` |
| 5 | 3.2 Prompts | versioned prompt texts, diff viewer, "run on sample" | key list only | API: S2 prompt registry routes |
| 6 | 4.2 QueueList | saved filters | named saved filters per user (this browser) | done 2026-10-23 |
| 7 | 4.2 EvidencePane | PageViewer (page render, bbox per flag, zoom, crop lightbox, OCR text toggle) for `low_confidence`; TablePreview (A/B side by side, cell diff) for `json_schema` / table conflicts; panes for `unit_fact`, `file_facts`, `sensitive`; PhotoView | dedicated panes for `unit_telemetry`, `array_schema`, `conflict`, `parse_failure`; the other five kinds fall back to a generic JSON pane | done 2026-10-23 (component tests; no live flags of these kinds yet). OCR-text toggle waits for OCR text in the evidence (S1) |
| 8 | 4.2 ResolutionConsole | "preview conversion" (dry run) | wired to `POST /review/dry-run` | API: S1 (answers 501) |
| 9 | 4.2 CaseHeader | "undo last resolution" | wired to `POST /review/cases/{id}/undo` | API: S1 (answers 501) |
| 10 | 4.2 RulesPage | "simulate" | wired to `POST /review/rules/{id}/simulate` | API: S1 (answers 501) |
| 11 | 4.2 RulesPage | export YAML | "Export YAML" in S1's RulesFile format | done 2026-10-23 |
| 12 | 4.2 EntitiesPage | search canonicals, merge/split aliases, counts | placeholder | API: S1 (`backend/api/entities.py` has no routes) |
| 13 | 4.2 OpsPage | queue depths, token/cost today, halted/soft counts, last benchmark pass rate | `GET /ops/summary` and overview panels | done 2026-10-23 (tokens/cost today show a note until S1's llm_calls lands) |
| 14 | 4.2 OpsPage | sync status per root; failed-task retry | missing | API: S1 sync status; retry needs S4 to store replayable task args |
| 15 | 5.5 Suites | import JSON, clone a suite | export only | build: import button (API exists) and clone (export → import under a new suite name) |
| 16 | 6 Viewer | handwriting regions with confidence as a pane; plot and diagram renders; page navigation (`GET /docs/{id}/pages/{n}/render`) | handwriting drawn as overlays; plots/diagrams fall back to text; one page only | build: handwriting pane from regions, `image` view for figure/diagram assets, previous/next page |
| 17 | 6 Viewer | on-the-fly translation when `content_en` is missing | toggle shows `content_en` only | API: S2 translation |

Order of the S3 builds: 1, 6, 7, 11, 13, 15, 16.
