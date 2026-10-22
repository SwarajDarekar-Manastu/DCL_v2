---
name: Diagram traversal
description: What is upstream, downstream or between components in our P&IDs and block diagrams.
intents: [diagram_traversal]
dcl-playbook: diagram_traversal
tools: [inspect_code_and_diagrams, search_documents]
---

# Diagram traversal

What is upstream, downstream or between components in our P&IDs and block diagrams.

## When to use

"What is upstream of the injector in Rev C?", "Path from the tank to SV-1?"

## What the engine does

1. Load the diagram's components and connections into a graph.
2. Find the path between two tags, or the neighbours of one tag.
3. Search the diagram text for labels and notes.
4. Answer with the linearized path (Tank → F-101 → SV-1 → INJ-14) and the diagram page.

## Tools

`inspect_code_and_diagrams`, `search_documents`

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
