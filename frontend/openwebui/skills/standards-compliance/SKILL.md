---
name: Standards compliance
description: Whether our data meets a requirement of a standard, with both the clause and our value cited.
intents: [standards_compliance]
dcl-playbook: standards_compliance
tools: [search_documents]
---

# Standards compliance

Whether our data meets a requirement of a standard, with both the clause and our value cited.

## When to use

"Does our cooling-duct FMEA satisfy the ECSS thermal margin requirement for TP37?"

## What the engine does

1. Find the requirement clause in the current revision of the standard.
2. Find our values in report and FMEA tables.
3. Compare the numbers in the same unit and give a verdict per requirement, citing the clause and our source.

## Tools

`search_documents`

## Limits

- A verdict needs both sides; if either is missing, the answer says which.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
