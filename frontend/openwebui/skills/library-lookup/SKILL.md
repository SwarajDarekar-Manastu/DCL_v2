---
name: Library lookup
description: A value or statement from a vendor datasheet or a paper in the kept library, labelled as such.
intents: [fact_lookup]
tools: [search_documents]
---

# Library lookup

A value or statement from a vendor datasheet or a paper in the kept library, labelled as such.

## When to use

"What preheat power does the Moog valve datasheet give?", "What did the 2023 ADN paper measure?"

## What the engine does

1. Search the kept library (datasheets, brochures, papers) as well as internal material.
2. Read the datasheet rows or paper sections.
3. Answer with the vendor-claim or literature label, in your language, quoting the original.

## Tools

`search_documents`

## Limits

- A vendor value is a claim, not a measurement; the answer keeps the label.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
