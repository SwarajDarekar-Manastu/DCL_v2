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
| pending | Allowlist folders for `processing.scope` | S1, S5 | S5 first task |
| pending | Gateway capability probe result | S2, S4 | S4 first tasks |
