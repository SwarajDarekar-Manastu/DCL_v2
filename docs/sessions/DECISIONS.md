# Cross-session decisions

Written by `DCL Lead` only. Newest at the bottom. Each entry names the sessions it binds.

| Date | Decision | Binds | Source |
|------|----------|-------|--------|
| 2026-10-21 | The architecture manual (`docs/architecture`) is normative; deviations go through the Lead | all | README |
| 2026-10-21 | Gemini only via the Manastu Cloud Run gateway; `GOOGLE_API_KEY` never set; one client module owned by S4 | S2, S4 | file 09 §H1 |
| 2026-10-21 | Two-tier halt policy is the default | S1, S3 | file 09 §H2 |
| 2026-10-21 | No fallback model for Gemini; extractive mode on outage | S2 | file 09 §H3 |
| 2026-10-21 | Delegated Graph app; permission option read from `DCL_PERMISSION_OPTION` (A preferred) | S1, S4 | file 09 §H4 |
| 2026-10-21 | DBOS is the workflow durability runtime | S2, S4 | file 09 §H8 |
| 2026-10-21 | Download everything the gate accepts; process only the allowlist until M6 | S1, S5 | file 09 §H11 |
| 2026-10-21 | Embedding and reranker services run on the GPU; everything else CPU | S2, S4 | file 09 §H12 |
| 2026-10-21 | EmbeddingGemma 2 at 768-d (`halfvec`), local; no cloud embeddings | S1, S2 | file 04 §5 |
| 2026-10-21 | 26-table schema with authored/registry/derived tiers; new tables need Lead approval | S1 | file 05 |
| 2026-10-21 | Stable anchors everywhere; node ids never stored durably | S1, S2, S3, S5 | file 04 §4.4 |
| 2026-10-21 | Env names for service wiring fixed: `DCL_ENV`, `DCL_ROLE`, `DCL_REDIS_URL`, `DCL_MINIO_*`, `DCL_MODELS_URL`, `DCL_API_BASE_URL`, `DCL_CONSOLE_BASE_URL`, `DCL_PIPE_SHARED_SECRET` (file 01 §7.1) | S1, S2, S3, S4 | S3 interface gap |
| 2026-10-21 | Console Entra ID auth: `DCL_CONSOLE_API_AUDIENCE`, `DCL_CONSOLE_GROUP_{REVIEWERS,ADMINS,EXTERNAL_SEARCH}`, `DCL_CONSOLE_ALLOWED_ORIGINS`; role rule viewer/reviewer/admin as in file 01 §7.1; group overage → 403; SPA build names are S3's `config.ts` | S3, S4 | S3 interface gap |
| 2026-10-21 | `DCL_GEMINI_API_KEY` is a legacy alias of `GEMINI_GATEWAY_KEY` (gateway credential, not a Google key); loader uses the primary, falls back to the alias, refuses `AIza…` values | S4 | user + format check |
| 2026-10-21 | Allowlist folders for `processing.scope`: the user delegates the choice. S5 fills the 13 slots from S1's real metadata crawl (folder contents matched against the slot criteria), records the result here, and informs the user; no approval step. Gateway URL/backend values arrive later; nothing waits on them | S1, S5 | user |
| 2026-10-21 | MinIO built from the archived pinned source tag for M0–M5; maintained replacement decided before M6 (file 09 §H.1) | S1, S4 | S4 blocker |
| 2026-10-21 | Token cache: v2 keeps its own Fernet-encrypted MSAL cache file (`DCL_TOKEN_CACHE_KEY`); v1's plain cache is never touched; `DCL_TEST_OUTSIDE_DRIVE_ID` added (defaults to `DCL_DRIVE_ID`) | S1, S4 | S1 question |
| pending | Gateway capability probe result | S2, S4 | S4 first tasks |
