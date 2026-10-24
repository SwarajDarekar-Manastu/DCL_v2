# Which model proposes a review suggestion (plan task 5, 2026-10-24)

**Choice:** a column's unit is proposed by **gemini-3.8-flash** (`backend/llm_engine/suggestions.py`, `UNIT_TIER = Tier.FLASH`). gemini-3.1-flash-lite does not work for this task. JSON key mappings and source choices are not measured: there is no labelled data yet.

## What is proposed, and when

File 06 §5: the route's deterministic hints come first (the file's own unit, a sibling file's unit for the same column, a unit in the column name). Only when they are silent does one model call propose a unit; the proposal is capped at confidence 0.5, marked `proposed_by = llm`, and a person always decides (telemetry units are never answered by a rule). It runs only for roots cleared for cloud processing.

## Test set

24 real channels whose files state the unit (`telemetry_channels.raw_unit`, live database 2026-10-24): 8 LabJack pressure channels y0–y7 (bar, gauge and absolute), 8 raw analogue inputs v0–v7 (V), 8 thermocouples T1–T8 (°C). The unit is removed from the evidence and from the name ("T7 - NW throat (°C)" becomes "T7 - NW throat"); each model sees what the pipeline gives in the hard case: column name, minimum, maximum and mean, file and folder. Prompt `suggest/unit.v1`, temperature 0, one call per channel and model. Script: the Lead's `task5/unit_eval.py` (run in an api container with the working tree mounted).

## Result

| model | right | wrong | no proposal | invalid reply | gauge/abs right (pressures) |
|---|---|---|---|---|---|
| gemini-3.1-flash-lite | 2 | 4 | 4 | 14 | 1 of 2 |
| gemini-3.8-flash | 16 | 2 | 6 | 0 | 4 of 5 |

- flash-lite's invalid replies ran away to the output limit (15 failed calls, 982,800 output tokens, about 65,000 each), so it is also the more expensive model in practice; its answers were mostly kelvin for °C.
- gemini-3.8-flash: 24 calls, 18,529 input and 1,757 output tokens in all. Its two wrong answers are kelvin for °C thermocouples; it declines (no proposal) when the name carries nothing (v4, v6, v7, some y channels), which is the wanted behaviour.
- Small set (24 items, 3 kinds of column): good enough to rule out flash-lite, not to promise an accuracy. The unit decisions people make in plan task 8 are the next test set.

## Not measured

- **JSON key → section mapping** (SCHEMA_UNKNOWN): two real JSON files, both of unknown shape, and the report schema config is an unconfirmed draft. No model proposal is built; the reviewer maps keys, and a `schema_mapping` rule repeats the mapping.
- **Source choice** (CONFLICT sources_disagree): one human decision in the database. No model proposal is built; a `source_choice` rule repeats the reviewer's choice.
