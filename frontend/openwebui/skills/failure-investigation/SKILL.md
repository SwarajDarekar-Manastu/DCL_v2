---
name: Failure investigation
description: What went wrong in a test and what damage was seen, from run data, failure reports, photos and the P&ID.
intents: [failure_investigation]
dcl-playbook: failure_investigation
tools: [inspect_code_and_diagrams, inspect_visuals, query_telemetry, search_documents]
---

# Failure investigation

What went wrong in a test and what damage was seen, from run data, failure reports, photos and the P&ID.

## When to use

"What went wrong in the INJ-14 flow test and what damage did we see?"

## What the engine does

1. Measure the anomaly in the run data when a test plan is named (pressure drop, peak, time to peak).
2. Search the test and failure reports for the stated observations and conclusions.
3. Find photos of the damage, with the failure modes the vision model read.
4. Look up what is connected to the failed component in the diagrams (upstream and downstream).
5. State cause and effect only as the sources state them; anything else is marked as an inference.

## Tools

`inspect_code_and_diagrams`, `inspect_visuals`, `query_telemetry`, `search_documents`

## Limits

- Telemetry is only queried when the question names a test plan.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
