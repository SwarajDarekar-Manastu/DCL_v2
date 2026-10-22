---
name: Navigational
description: Which documents, runs or tests exist for something, with links.
intents: [navigational]
tools: [catalog_lookup, search_documents]
---

# Navigational

Which documents, runs or tests exist for something, with links.

## When to use

"What tests used the ADN catalyst?", "Where is the heater calibration?"

## What the engine does

1. List matching documents and runs from the catalog (document kind, test plan, entities), including halted ones with their review case.
2. Search where the topic is discussed.
3. Answer with a list of links to the viewer.

## Tools

`catalog_lookup`, `search_documents`

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
