---
name: Document summary
description: A summary of one document, with its key numbers cited.
intents: [document_summary]
tools: [get_document, search_documents]
---

# Document summary

A summary of one document, with its key numbers cited.

## When to use

"Summarize the TP37 report"

## What the engine does

1. Find the document.
2. Read it section by section (up to about 40,000 characters per pass).
3. Summarize, with every key number cited to its page.

## Tools

`get_document`, `search_documents`

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
