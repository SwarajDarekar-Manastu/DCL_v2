# Benchmark baseline: scored run 1 (M10)

Run `05a0b3a7` on the stack, 2026-10-22, 56 active cases over six suites (the three hold-outs excluded and
not reported). Stack state at the time: 18 A1 PDFs and 18 Route C documents indexed, A1 with Gemini off,
22 LabJack/TDMS runs HALTED, the 8 ECSS standards halted as encrypted, Route B and Route D not processed.
Classified by S5 (one class per case). Classes: pipeline gap (document not indexed or halted), gold error,
runner/metric bug, engine error.

Totals: engine error 15, pass 1, pipeline gap 14, runner/metric bug 26

Runner findings for S2 (column "runner class"):

1. 38 cases errored with a null failure class: 24 `RuntimeError: Event loop is closed` / `... bound to a different event loop` (the runner reuses an asyncio object across cases), 14 `WorkflowTimeoutError` at 300 s in the answer step. Both need a class (TOOL_ERROR or a timeout class) instead of null.
2. `classify` reaches RETRIEVAL_MISS only through `retrieval_gold_anchors`; cases without anchors whose expected citation is never cited (recall 0) fall through to SYNTHESIS_ERROR. Proposal: citation recall 0 with no anchors gives RETRIEVAL_MISS.
3. `must_label_external` counts only web citations; LIBRARY_VS_INTERNAL cases are about external_kept library evidence (file 08 §5), so the moog case fails although the provenance judge passed.
4. `must_state_insufficient_evidence` is mode-only; a decline in chitchat mode fails it. The answer text decides whether this is a gold error.
5. HALTED-data numeric cases end as SYNTHESIS_ERROR; the halted state is not visible in the class.

| Suite | Case | Class | Runner class | Runner flag | Reason |
|---|---|---|---|---|---|
| behaviour | `moog-monoprop-thrust-external` | runner/metric bug | BEHAVIOR_FAIL | flag: BEHAVIOR_FAIL is wrong | must_label_external passes only with web citations; file 08 §5 labels external_kept library evidence, and the provenance_labeling judge passed |
| behaviour | `test01-peak-pressure-clarify` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP7 T01 pressure run HALTED |
| behaviour | `tp07-chamber-pressure-vs-vendor` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP7 T01 pressure run HALTED |
| behaviour | `tp07-t01-isp-insufficient-evidence` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP7 T01 pressure run HALTED |
| behaviour | `tp99-insufficient-evidence` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: no corpus dependency |
| behaviour | `weather-out-of-scope` | runner/metric bug | BEHAVIOR_FAIL | flag: check is mode-only | must_state_insufficient_evidence requires mode=insufficient_evidence; engine replied in chitchat mode with no tools or citations (out_of_scope passed). Gold error if the reply did not decline; needs the answer text |
| code | `code-tpc-aux-extensions` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | Route B never processed: the creator script is not indexed; mode insufficient_evidence, gold never cited |
| code | `code-tpc-excel-close` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: Route B never processed: the creator script is not indexed |
| code | `code-tpc-expectation-sheet` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | script not indexed (Route B); engine answered from other documents, cited none of the gold |
| code | `code-tpc-main-output` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | Route B never processed: the creator script is not indexed; mode insufficient_evidence, gold never cited |
| code | `code-tpc-max-latex-passes` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | Route B never processed: the creator script is not indexed; mode insufficient_evidence, gold never cited |
| code | `code-tpc-name-protect` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | Route B never processed: the creator script is not indexed; mode insufficient_evidence, gold never cited |
| code | `code-tpc-portrait-rotation` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | Route B never processed: the creator script is not indexed; mode insufficient_evidence, gold never cited |
| code | `code-tpc-rerun-trigger` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: Route B never processed: the creator script is not indexed |
| documents | `tp12-combustion-not-sustained-causes` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: TP12 report PDF apparently not indexed (to confirm) |
| documents | `tp12-customer-cumulative-firing` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP12 report PDF apparently not indexed (to confirm) |
| documents | `tp12-customer-throughput` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP12 report PDF apparently not indexed (to confirm) |
| documents | `tp12-flame-quench-time` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP12 report PDF apparently not indexed (to confirm) |
| documents | `tp12-load-cell-range` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | insufficient_evidence; TP12 report PDF apparently not indexed (to confirm) |
| documents | `tp12-monolith-cell-density` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP12 report PDF apparently not indexed (to confirm) |
| documents | `tp12-test4-tank-pressure` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | answered from other documents, gold PDF never cited; TP12 report apparently not indexed (to confirm) |
| documents | `tp12-wall-material-limit` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP12 report PDF apparently not indexed (to confirm) |
| documents | `tp23-expected-isp-mid-pressure` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP23 report is indexed (tp23-max-firing-duration passes) |
| documents | `tp23-last-test-condition` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: TP23 report is indexed (tp23-max-firing-duration passes) |
| documents | `tp23-max-firing-duration` | pass | null |  | number and citation correct |
| documents | `tp23-number-of-tests` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: TP23 report is indexed (tp23-max-firing-duration passes) |
| documents | `tp23-propellant-composition` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP23 report is indexed (tp23-max-firing-duration passes) |
| documents | `tp23-wall-temperature-abort` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: TP23 report is indexed (tp23-max-firing-duration passes) |
| documents | `tp23-worst-channel-flow` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: TP23 report is indexed (tp23-max-firing-duration passes) |
| standards | `ecss-e-st-32-02c-heat-pipe-factors` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: ECSS standards halted as encrypted |
| standards | `ecss-e-st-32-02c-pressure-vessel-factors` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | ECSS standards halted as encrypted; mode answered, gold never cited |
| standards | `ecss-e-st-35-06c-nvr-a10` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: ECSS standards halted as encrypted |
| standards | `ecss-e-st-35-10c-elevated-corrosion-testing` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | ECSS standards halted as encrypted; mode answered, gold never cited |
| standards | `ecss-q-st-70c-tin-finish` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR, expected RETRIEVAL_MISS | ECSS standards halted as encrypted; mode answered, gold never cited |
| telemetry | `inj10-t01-mass-flow-mean` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `inj10-t02-valve-open-duration` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `inj14-t01-chamber-pressure-halted` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `tp07-t01-chamber-pressure-mean` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR hides halted data | run HALTED; engine still answered (faithfulness 0.8) without naming the halted case |
| telemetry | `tp07-t01-chamber-pressure-peak` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `tp07-t01-chamber-pressure-rise-t90` | pipeline gap | SYNTHESIS_ERROR | flag: SYNTHESIS_ERROR hides halted data | run HALTED; engine answered without naming the halted case |
| telemetry | `tp07-t01-mass-flow-mean` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `tp07-t01-mass-flow-peak` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `tp07-t01-supply-pressure-mean` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `tp07-t01-t4-max-firing` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `tp07-t01-t4-preheat` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `tp07-t01-thrust-halted` | engine error | BEHAVIOR_FAIL | ok | run is HALTED exactly as the case expects; the answer does not mention the halted case |
| telemetry | `tp07-t01-valve-inlet-pressure-peak` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| telemetry | `tp07-t01-valve-open-duration` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: LabJack/TDMS run HALTED (no confirmed channel map) |
| visual | `tp07-deint-chamber-length` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: Gemini off: no handwriting transcription on the TP7 sheets |
| visual | `tp07-deint-heater-condition` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: Gemini off: no handwriting transcription on the TP7 sheets |
| visual | `tp07-deint-injector` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: Gemini off: no handwriting transcription on the TP7 sheets |
| visual | `tp07-deint-mesh-status` | engine error | null | flag: null class | answer step timed out at 300 s; underneath: Gemini off: no handwriting transcription on the TP7 sheets |
| visual | `tp07-preheat-sheet-test-plan-conflict` | pipeline gap | BEHAVIOR_FAIL | ok | sheet indexed from OCR only (Gemini off), footer and handwriting unread, no TP7 CONFLICT flag; engine also skipped inspect_visuals |
| visual | `tp07-preheat-test1-status` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: Gemini off: no handwriting transcription on the TP7 sheets |
| visual | `tp07-preheat-test2-start-time` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: Gemini off: no handwriting transcription on the TP7 sheets |
| visual | `tp07-preheat-test2-temperature` | runner/metric bug | null | flag: null class | asyncio event loop closed or reused across cases; underneath: Gemini off: no handwriting transcription on the TP7 sheets |
