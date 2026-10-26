---
name: Navigational
description: Which documents, runs or tests exist for something, with links.
intents: [navigational]
dcl-playbook: navigational
tools: [search_documents]
---

# Navigational

Which documents, runs or tests exist for something, with links.

## When to use

"What tests used the ADN catalyst?", "Where is the heater calibration?"

## What the engine does

1. Find the matching files and runs in the metadata of every file (title, path, summary, labels, entities), including halted ones with their review case; ask back when the question fits several tests.
2. Search where the topic is discussed.
3. Answer with a list of links to the viewer.

## Tools

`search_documents`

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
