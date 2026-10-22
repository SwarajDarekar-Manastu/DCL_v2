---
name: Telemetry metric
description: Peak, steady-state, mean or duration of a measured channel in a test run, computed from the run data.
intents: [telemetry_metric]
dcl-playbook: telemetry_metric
tools: [catalog_lookup, query_telemetry, search_documents]
---

# Telemetry metric

Peak, steady-state, mean or duration of a measured channel in a test run, computed from the run data.

## When to use

"What was the peak and steady-state chamber pressure in TP07 T04?", "How long was the valve open in Test 01 of Test Plan 7?"

## What the engine does

1. Resolve the runs of the test plan (and run, if named) from the telemetry catalog. A run that is halted for review is reported with its review case, never answered.
2. Map the quantity you asked for (chamber pressure, thrust, bed temperature, mass flow, heater power) to the run's measured channels.
3. Compute the metrics deterministically from the run's Parquet file with fixed SQL templates: raw peak, 50 ms peak, steady-state mean, max, min, mean, p99, duration, time to peak, value at a time, or window statistics. The window is the whole run, the stored steady plateau, the valve-open pulse, or a time range after ignition that you give.
4. Search the test report's tables for the value the report states, to cross-check.
5. Answer with each number's unit (barg or bara), the exact window, the t0 method, the sampling rate and the data file. Ask for a plot to get a chart with the window shaded.

## Tools

`catalog_lookup`, `query_telemetry`, `search_documents`

## Limits

- Only the five quantities above are mapped; other channels (for example wall thermocouples) are not answered yet.
- Gauge pressure is not converted to absolute when the run's ambient condition is unknown; the answer says so.
- A saturated sensor is flagged in the answer.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
