---
name: Code walkthrough
description: How one of our scripts computes or validates something, with line citations.
intents: [code_walkthrough]
tools: [inspect_code_and_diagrams, search_documents]
---

# Code walkthrough

How one of our scripts computes or validates something, with line citations.

## When to use

"How does our script compute the expansion ratio and validate pressure columns?"

## What the engine does

1. Look up the named function or class, with its callers and callees one level each way.
2. Search the code for the behaviour described.
3. Explain the code with file and line citations.

## Tools

`inspect_code_and_diagrams`, `search_documents`

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
