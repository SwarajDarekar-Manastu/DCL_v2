---
name: Run comparison
description: The same metrics for two or more runs side by side, aligned on time from ignition.
intents: [run_comparison]
dcl-playbook: run_comparison
tools: [catalog_lookup, query_telemetry, search_documents]
---

# Run comparison

The same metrics for two or more runs side by side, aligned on time from ignition.

## When to use

"Compare TP07 T01 and T02 bed temperature", "Which run of Test Plan 7 had the highest thrust?"

## What the engine does

1. Resolve every run named (or every run of the test plan).
2. Compute the same metrics over the same kind of window for each run, in one query.
3. Search the reports' tables to cross-check stated values.
4. Answer with a table, one row per run, and an overlay plot on request.

## Tools

`catalog_lookup`, `query_telemetry`, `search_documents`

## Limits

- At most 12 runs per answer.
- Halted runs are listed with their review case instead of a value.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
